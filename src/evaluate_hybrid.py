"""Reproducible retrieval comparison and bounded answer-review samples.

Development labels are phrase-derived silver labels. Challenge passage labels
were frozen before dense/hybrid runs and are agent-curated, not expert gold.
Never equates resolving citations with semantic faithfulness.
"""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
from aml_research import ROOT,load_index
from hybrid_retrieval import embed,dense_search,fuse,status,corpus_hash

def normalize(text):return ' '.join(text.lower().replace('‑','-').replace('–','-').split())
def cases():
    chunks=load_index().chunks;rows=[]
    for case in json.loads((ROOT/'evaluation/typology_cases.json').read_text()):
        labels=[c['chunk_id'] for c in chunks if c['source_id'] in case['source_ids'] and any(normalize(p) in normalize(c['text']) for p in case['key_phrases'])]
        if not labels:raise ValueError('No source evidence for '+case['id'])
        rows.append({'id':case['id'],'question':case['question'],'relevant_passage_ids':labels,'split':'development','category':case['topic'],'label_status':'phrase-derived silver passage labels; not expert gold'})
    rows+=json.loads((ROOT/'evaluation/hybrid_challenge.json').read_text())
    ids={c['chunk_id'] for c in chunks}
    for row in rows:
        if not set(row['relevant_passage_ids'])<=ids:raise ValueError('Unknown labeled passage in '+row['id'])
    return rows

def score(hits,relevant,k=5):
    ranked=[h['chunk_id'] for h in hits[:k]];gold=set(relevant)
    positions=[i for i,c in enumerate(ranked,1) if c in gold]
    dcg=sum(1/math.log2(i+1) for i in positions)
    ideal=sum(1/math.log2(i+1) for i in range(1,min(k,len(gold))+1))
    return {'hit_at_5':int(bool(positions)),'mrr_at_5':1/min(positions) if positions else 0,
            'known_passage_recall_at_5':len(set(ranked)&gold)/len(gold) if gold else 0,
            'ndcg_at_5':dcg/ideal if ideal else 0}

def compare():
    rows=cases();available=status()['ready'];index=load_index();results=[]
    # Batch queries and reuse exact cached vectors across all methods.
    if available:embed([c['question'] for c in rows],query=True)
    for i,case in enumerate(rows,1):
        start=time.monotonic();sparse=index.search(case['question'],12);sparse_ms=(time.monotonic()-start)*1000
        runs={'bm25':(sparse[:5],sparse_ms)}
        if available:
            start=time.monotonic();dense=dense_search(case['question'],12);dense_ms=(time.monotonic()-start)*1000
            start=time.monotonic();hybrid=fuse(sparse,dense,5);fusion_ms=(time.monotonic()-start)*1000
            runs.update(dense=(dense[:5],dense_ms),hybrid=(hybrid,sparse_ms+dense_ms+fusion_ms))
        for method,(hits,latency) in runs.items():
            results.append({**case,'method':method,'scores':score(hits,case['relevant_passage_ids']),
                'retrieval_ms':round(latency,2),'retrieved_passage_ids':[h['chunk_id'] for h in hits]})
        print(f'Retrieval comparison {i}/{len(rows)}',flush=True)
    summary={}
    for split in ('development','challenge'):
        summary[split]={}
        for method in ('bm25','dense','hybrid'):
            subset=[r for r in results if r['split']==split and r['method']==method]
            if not subset:continue
            latency=sorted(r['retrieval_ms'] for r in subset)
            summary[split][method]={'questions':len(subset),**{key:round(statistics.mean(r['scores'][key] for r in subset),4) for key in subset[0]['scores']},
                'retrieval_p50_ms':round(statistics.median(latency),2),'retrieval_p95_ms':latency[max(0,math.ceil(.95*len(latency))-1)]}
    report={'status':'complete' if available else 'baseline_only','created_at':datetime.now(timezone.utc).isoformat(),
        'corpus_hash':corpus_hash(index.chunks),'dataset_hash':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
        'embedding':status(),'methods':['bm25','dense','hybrid'] if available else ['bm25'],
        'protocol':{'context_k':5,'candidate_k':12,'fusion':'reciprocal rank fusion, constant 60, equal channel weights',
          'baseline':'Existing BM25 with domain topic routing; same source routing used by dense search.',
          'timing':'Single sequential run; query embeddings precomputed/cached. Excludes generation and cold embedding latency.',
          'labels':'Development: phrase-derived silver labels. Challenge: agent-curated captured-passage labels frozen before comparison. Neither is independent expert gold.',
          'recall':'Known-passage recall only; labels are not an exhaustive relevance assessment.',
          'faithfulness':'Not measured by retrieval scores. Citation integrity does not establish semantic support.'},
        'summary':summary,'results':results}
    (ROOT/'reports/retrieval_comparison.json').write_text(json.dumps(report,indent=2))
    with (ROOT/'reports/retrieval_comparison.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=['id','split','method','question','hit_at_5','mrr_at_5','ndcg_at_5','known_passage_recall_at_5','retrieval_ms','retrieved_passage_ids'])
        writer.writeheader()
        for r in results:writer.writerow({k:r[k] for k in ['id','split','method','question','retrieval_ms']}|r['scores']|{'retrieved_passage_ids':' | '.join(r['retrieved_passage_ids'])})
    return report

def answer_samples():
    import assistant_service as svc
    if not status()['ready']:raise svc.SetupError('Connect Pinecone before comparing generated answers.')
    chosen=[c for c in cases() if c['id'] in ('C01','C05')]
    chosen.append({'id':'N01','question':'How many Suspicious Activity Reports did my employer file last month? I have not provided any internal reporting data.','expected_behavior':'clarify or insufficient; no invented internal counts'})
    rows=[]
    for case in chosen:
        for method in ('bm25','hybrid'):
            start=time.monotonic();answer=svc.ask(case['question'],retrieval_method=method)
            record={'id':case['id'],'question':case['question'],'method':method,'expected_behavior':case.get('expected_behavior','Answer supported parts without inventing facts or obligations.'),
                'answer':answer,'elapsed_seconds':round(time.monotonic()-start,2),'review':{'status':'pending','faithfulness':None,'relevance':None,'completeness':None,'notes':''}}
            rows.append(record)
            # Save incrementally so a provider outage never discards prior samples.
            (ROOT/'reports/answer_comparison.json').write_text(json.dumps({'status':'review_pending','kind':'six illustrative generation samples, not an accuracy benchmark','samples':rows},indent=2))
            print('Answer sample',case['id'],method,answer['status'],flush=True)
    return rows

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--answers',action='store_true');args=parser.parse_args()
    if args.answers:answer_samples()
    else:
        result=compare();print(json.dumps({'status':result['status'],'summary':result['summary']},indent=2))
