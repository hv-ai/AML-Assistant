"""Nebius dense embeddings + Pinecone + routed BM25, fused with RRF.

Remote operations are explicit: prepare caches corpus embeddings, sync provisions
one serverless index/namespace and verifies it, then runtime queries use Pinecone.
No keys are exposed in manifests, logs, errors, or browser responses.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
import re
import threading
import time
import uuid
from urllib import request,error,parse
from aml_research import ROOT,load_index,tokens

MODEL='Qwen/Qwen3-Embedding-8B'
DIMENSION=1024
LOCK=threading.Lock()

def config():
    import assistant_service as svc
    conf=svc.settings()
    return {**conf,'embedding_model':conf.get('NEBIUS_EMBEDDING_MODEL') or MODEL,
            'index_name':conf.get('PINECONE_INDEX') or 'aml-research',
            'cloud':conf.get('PINECONE_CLOUD') or 'aws','region':conf.get('PINECONE_REGION') or 'us-east-1'}

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data));temp.chmod(0o600);temp.replace(path)

def corpus_hash(chunks):
    return hashlib.sha256(json.dumps([(c['chunk_id'],c['title'],c['heading'],c['text']) for c in chunks],ensure_ascii=False).encode()).hexdigest()

def windows(chunks,size=450,overlap=60):
    if size<=overlap or overlap<0:raise ValueError('Invalid window sizes')
    rows=[]
    for c in chunks:
        words=c['text'].split()
        for start in range(0,len(words),size-overlap):
            text=c['title']+'\n'+c['heading']+'\n'+' '.join(words[start:start+size])
            identity=hashlib.sha256((c['chunk_id']+'\n'+text).encode()).hexdigest()
            rows.append({'id':identity,'parent_id':c['chunk_id'],'source_id':c['source_id'],'text':text})
            if start+size>=len(words):break
    return rows

def embed(texts,query=False):
    import assistant_service as svc
    conf=config();model=conf['embedding_model']
    inputs=[('Instruct: Retrieve official AML guidance passages relevant to the question.\nQuery: '+t) if query else t for t in texts]
    if not inputs:return []
    if any(not isinstance(t,str) or not t or len(t)>18000 for t in inputs):raise svc.SetupError('Embedding text is empty or exceeds the input limit.')
    keys=[hashlib.sha256((model+'|'+str(DIMENSION)+'|'+t).encode()).hexdigest() for t in inputs]
    folder=ROOT/'.runtime/embeddings'
    with LOCK:
        missing=list(dict.fromkeys(k for k in keys if not (folder/(k+'.json')).exists()))
        for offset in range(0,len(missing),8):
            batch=missing[offset:offset+8]
            usage_path=ROOT/'.runtime/embedding_usage.json'
            usage=json.loads(usage_path.read_text()) if usage_path.exists() else {'calls':0,'input_tokens':0}
            if usage['calls']>=150:raise svc.SetupError('Embedding development call limit reached. Review embedding usage before increasing it.')
            usage['calls']+=1;atomic(usage_path,usage)
            response=svc.provider('/embeddings',{'model':model,'input':[inputs[keys.index(k)] for k in batch],'dimensions':DIMENSION,'encoding_format':'float'})
            vectors=response.get('data',[])
            if len(vectors)!=len(batch) or sorted(v.get('index',-1) for v in vectors)!=list(range(len(batch))):raise svc.SetupError('Nebius returned an incomplete embedding batch.')
            indexed={v['index']:v.get('embedding') for v in vectors}
            for i,k in enumerate(batch):
                vector=indexed[i]
                if not isinstance(vector,list) or len(vector)!=DIMENSION or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in vector) or sum(v*v for v in vector)==0:
                    raise svc.SetupError('Nebius returned invalid embedding dimensions or values.')
                atomic(folder/(k+'.json'),vector)
            usage['input_tokens']+=int(response.get('usage',{}).get('prompt_tokens',0));atomic(usage_path,usage)
        return [json.loads((folder/(k+'.json')).read_text()) for k in keys]

def pinecone(path,payload=None,host='api.pinecone.io',method=None):
    import assistant_service as svc
    conf=config()
    if not conf.get('PINECONE_API_KEY'):raise svc.SetupError('Pinecone is not configured. Run python3 configure.py --pinecone locally.')
    if host!='api.pinecone.io' and not re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.svc\.[a-zA-Z0-9.-]+\.pinecone\.io',host):
        raise svc.SetupError('Invalid Pinecone index host.')
    if not path.startswith('/') or '://' in path:raise svc.SetupError('Invalid Pinecone API path.')
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    req=request.Request('https://'+host+path,data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Api-Key':conf['PINECONE_API_KEY'],'X-Pinecone-Api-Version':'2025-10','Content-Type':'application/json'},method=method)
    try:
        with request.build_opener(NoRedirect).open(req,timeout=35) as r:return json.loads(r.read(3_000_000))
    except error.HTTPError as exc:
        if exc.code==404:
            if host=='api.pinecone.io':raise FileNotFoundError('Pinecone index not found') from None
            raise svc.SetupError('Pinecone query endpoint is unavailable.') from None
        messages={401:'Pinecone rejected the API key.',403:'Pinecone key lacks access to this project or operation.',429:'Pinecone quota or rate limit reached.',400:'Pinecone rejected the index configuration or vector request.',409:'Pinecone index name already exists; retry sync.'}
        raise svc.SetupError(messages.get(exc.code,'Pinecone request failed (HTTP '+str(exc.code)+').')) from None
    except (error.URLError,TimeoutError):raise svc.SetupError('Pinecone could not be reached. Keyword retrieval remains available.') from None

def prepare():
    chunks=load_index().chunks;rows=windows(chunks)
    vectors=embed([r['text'] for r in rows])
    manifest={'corpus_hash':corpus_hash(chunks),'model':config()['embedding_model'],'dimension':DIMENSION,
              'parent_chunks':len(chunks),'window_words':450,'overlap_words':60,
              'records':[{**r,'values':v} for r,v in zip(rows,vectors)]}
    atomic(ROOT/'.runtime/dense_records.json',manifest)
    return {k:v for k,v in manifest.items() if k!='records'}|{'vectors':len(rows)}

def sync():
    import assistant_service as svc
    conf=config()
    if not conf.get('PINECONE_API_KEY'):raise svc.SetupError('Save your Pinecone key with python3 configure.py --pinecone first.')
    p=ROOT/'.runtime/dense_records.json'
    if not p.exists():raise svc.SetupError('Run python3 src/hybrid_retrieval.py prepare first.')
    data=json.loads(p.read_text());chunks=load_index().chunks
    if data['corpus_hash']!=corpus_hash(chunks) or data['model']!=conf['embedding_model']:raise svc.SetupError('Corpus or embedding model changed. Prepare embeddings again.')
    name=conf['index_name']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,43}[a-z0-9]',name):raise svc.SetupError('Use a lowercase Pinecone index name with letters, digits and hyphens.')
    try:description=pinecone('/indexes/'+name)
    except FileNotFoundError:
        description=pinecone('/indexes',{'name':name,'vector_type':'dense','dimension':DIMENSION,'metric':'cosine','spec':{'serverless':{'cloud':conf['cloud'],'region':conf['region']}},'deletion_protection':'enabled','tags':{'project':'aml-review-desk'}})
    if description.get('dimension')!=DIMENSION or description.get('metric')!='cosine':raise svc.SetupError('Existing Pinecone index has incompatible dimensions or metric. Choose a separate index; no data was changed.')
    for _ in range(20):
        if description.get('status',{}).get('ready'):break
        time.sleep(2);description=pinecone('/indexes/'+name)
    else:raise svc.SetupError('Pinecone index is still initializing. Run sync again shortly.')
    namespace='aml-'+hashlib.sha256((data['corpus_hash']+data['model']+str(DIMENSION)+'|'.join(r['id'] for r in data['records'])).encode()).hexdigest()[:20]
    host=description['host']
    records=data['records']
    for offset in range(0,len(records),24):
        pinecone('/vectors/upsert',{'namespace':namespace,'vectors':[{'id':r['id'],'values':r['values'],'metadata':{'parent_id':r['parent_id'],'source_id':r['source_id']}} for r in records[offset:offset+24]]},host)
    # Pinecone is eventually consistent. Verify all records before activating.
    for _ in range(20):
        stats=pinecone('/describe_index_stats',{},host)
        if stats.get('namespaces',{}).get(namespace,{}).get('vectorCount',0)>=len(records):break
        time.sleep(2)
    else:raise svc.SetupError('Vectors were accepted but are not all visible yet. Rerun sync; deterministic IDs prevent duplicates.')
    state={'ready':True,'index_name':name,'host':host,'namespace':namespace,'corpus_hash':data['corpus_hash'],
           'model':data['model'],'dimension':DIMENSION,'vectors':len(records),'parent_chunks':len(chunks),'verified_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    atomic(ROOT/'.runtime/hybrid_state.json',state)
    return {k:v for k,v in state.items() if k not in ('host','namespace')}

def index_state():
    candidates=[]
    for p in (ROOT/'.runtime/hybrid_state.json',ROOT/'config/deployment_retrieval.json'):
        if p.exists():candidates.append(json.loads(p.read_text()))
    if len(candidates)<2:return candidates[0] if candidates else {}
    current=corpus_hash(load_index().chunks)
    return next((state for state in candidates if state.get('corpus_hash')==current),candidates[0])


def status():
    conf=config();state=index_state()
    current=corpus_hash(load_index().chunks)
    ready=bool(conf.get('PINECONE_API_KEY') and state.get('ready') and state.get('corpus_hash')==current and state.get('model')==conf['embedding_model'] and state.get('index_name')==conf['index_name'])
    return {'ready':ready,'pinecone_configured':bool(conf.get('PINECONE_API_KEY')),'embedding_model':conf['embedding_model'],
            'dimension':DIMENSION,'vectors':state.get('vectors',0),'method':'Hybrid · BM25 + semantic search' if ready else 'Keyword search · semantic index not connected'}

def eligible_sources(question):
    terms=set(tokens(question));text=' '+' '.join(tokens(question))+' '
    topics=json.loads((ROOT/'config/typology_topics.json').read_text())
    additional=ROOT/'config/additional_research_topics.json'
    if additional.exists():topics+=json.loads(additional.read_text())
    matched=[t for t in topics if any(' '+' '.join(tokens(a))+' ' in text for a in t.get('aliases',[]))]
    allowed={sid for topic in matched for sid in topic['source_ids']} if matched else None
    controls=bool(terms&{'kyc','cdd','edd','cip'}) or any(t in question.lower() for t in ('know your customer','customer due diligence','identity verification'))
    if controls:
        allowed=(allowed or set())|{'S06','S10','S12','S24'}
        if re.search(r'histor|2014|testimony',question,re.I):allowed.add('S13')
    return sorted(allowed) if allowed else None

def dense_search(question,k=12):
    import assistant_service as svc
    if not status()['ready']:raise svc.SetupError('Semantic index is not connected.')
    state=index_state()
    lookup={c['chunk_id']:c for c in load_index().chunks}
    payload={'namespace':state['namespace'],'vector':embed([question],query=True)[0],'topK':min(k*3,60),'includeMetadata':True,'includeValues':False}
    sources=eligible_sources(question)
    if sources:payload['filter']={'source_id':{'$in':sources}}
    response=pinecone('/query',payload,state['host']);results=[];seen=set()
    for match in response.get('matches',[]):
        parent=match.get('metadata',{}).get('parent_id')
        if parent not in lookup or parent in seen:continue
        score=match.get('score')
        if not isinstance(score,(int,float)) or not math.isfinite(score):continue
        seen.add(parent);results.append({**lookup[parent],'dense_score':score})
        if len(results)>=k:break
    return results

def fuse(sparse,dense,k=8,constant=60):
    scores=defaultdict(float);lookup={};ranks=defaultdict(dict)
    for channel,rows in [('keyword',sparse),('semantic',dense)]:
        seen=set()
        for rank,row in enumerate(rows,1):
            identity=row['chunk_id']
            if identity in seen:continue
            seen.add(identity);lookup.setdefault(identity,row);scores[identity]+=1/(constant+rank);ranks[identity][channel]=rank
    ordered=sorted(scores,key=lambda identity:(-scores[identity],identity))[:k]
    return [{**lookup[i],'fusion_score':round(scores[i],8),'retrieval_channels':list(ranks[i]),'retrieval_ranks':ranks[i]} for i in ordered]

def retrieve(question,k=8,index=None,method='auto'):
    import assistant_service as svc
    index=index or load_index();sparse=index.search(question,min(20,max(k,12)))
    if method=='bm25':return sparse[:k],{'method':'BM25 with topic routing','degraded':False}
    ready=status()['ready']
    if not ready:
        if method in ('hybrid','dense'):raise svc.SetupError('Connect and sync Pinecone before running dense or hybrid evaluation.')
        return sparse[:k],{'method':'BM25 with topic routing','degraded':True,'notice':'Semantic retrieval is not connected; this answer uses keyword search.'}
    try:
        dense=dense_search(question,12)
        if not dense:raise svc.SetupError('Semantic search returned no valid current-corpus passages.')
        if method=='dense':return dense[:k],{'method':'Nebius embeddings + Pinecone dense','degraded':False}
        return fuse(sparse,dense,k),{'method':'Hybrid · BM25 + Nebius embeddings + Pinecone · RRF','degraded':False}
    except svc.SetupError as exc:
        if method!='auto':raise
        return sparse[:k],{'method':'BM25 with topic routing','degraded':True,'notice':str(exc)+' Using keyword search for this answer.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','sync','status']);args=parser.parse_args()
    try:print(json.dumps({'prepare':prepare,'sync':sync,'status':status}[args.command](),indent=2))
    except (ValueError,OSError) as exc:raise SystemExit(str(exc))
