"""Read bounded, directly linked official regulator PDFs for a news brief.

No arbitrary client URL is accepted. Links must come from the fetched article,
remain on its issuing agency's approved HTTPS hosts, and pass the same checks
on every redirect. PDF extraction runs in a time-limited subprocess.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib import request, error
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
import news_sources
import assistant_service as svc

MAX_BYTES = 6_000_000
MAX_PAGES = 50

def official_document(url, publisher):
    u=urlsplit(url)
    source=next((s for s in news_sources.SOURCES if s['publisher']==publisher),None)
    if (not source or source.get('source_type','official')!='official' or u.scheme!='https' or u.netloc not in source['hosts'] or
        u.username or u.password or u.port or u.query or re.search(r'%(?!20)',u.path,re.I) or '..' in u.path or '\\' in u.path):
        raise svc.SetupError('Only directly linked PDFs on the issuing regulator’s official HTTPS hosts are supported.')
    if not (u.path.lower().endswith('.pdf') or re.fullmatch(r'/media/[A-Za-z0-9_% .-]+(?:/[A-Za-z0-9_% .-]+)*/download',u.path)):
        raise svc.SetupError('The regulator link is not a supported PDF URL.')
    return urlunsplit((u.scheme,u.netloc,u.path,'',''))

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.current=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a':self.current=[attrs.get('href',''),'']
    def handle_data(self,text):
        if self.current is not None:self.current[1]+=text
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:self.links.append(self.current);self.current=None

def discover(html,item):
    # Prefer the article body so site-wide footer PDFs are not treated as case evidence.
    article=re.search(r'<article\b[^>]*>(.*?)</article>',html,re.S|re.I)
    p=Links();p.feed(article[1] if article else html);found={}
    attachments=Links();attachments.feed(html)
    # Some agencies put case attachments in a sibling panel outside <article>.
    related=[link for link in attachments.links if re.search(r'order|consent|assessment|alert|advisory|report|notice',link[1],re.I)
             and not re.search(r'privacy|accessibility|annual report|performance report',link[1],re.I)]
    for href,title in p.links+related:
        try:url=official_document(urljoin(item['url'],href),item['publisher'])
        except (svc.SetupError,ValueError):continue
        found.setdefault(url,{'url':url,'title':' '.join(title.split())[:180] or 'Regulator document'})
    # Case orders, alerts and reports take precedence over incidental attachments.
    rows=sorted(found.values(),key=lambda d:bool(re.search(r'order|consent|assessment|alert|advisory|report|notice',d['title'],re.I)),reverse=True)
    return rows

def fetch_pdf(url,publisher):
    url=official_document(url,publisher)
    class SafeRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            target=official_document(newurl,publisher)
            return super().redirect_request(req,fp,code,msg,headers,target)
    req=request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; AMLResearchAssistant/0.3; public-source research)'})
    try:
        with request.build_opener(SafeRedirect).open(req,timeout=15) as response:
            if 'application/pdf' not in response.headers.get('Content-Type','').lower():
                raise svc.SetupError('The linked document did not return a PDF.')
            data=response.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise svc.SetupError('The PDF exceeds the 6 MB reading limit.')
        if not data.startswith(b'%PDF-'):raise svc.SetupError('The linked file is not a readable PDF.')
        return data
    except (error.URLError,TimeoutError):raise svc.SetupError('The linked regulator PDF could not be downloaded.') from None

def extract(path):
    try:from pypdf import PdfReader
    except ImportError:raise svc.SetupError('PDF reading is unavailable. Install the project requirements.') from None
    reader=PdfReader(path,strict=False)
    if reader.is_encrypted:raise svc.SetupError('The regulator PDF is encrypted.')
    total=len(reader.pages);pages=[];remaining=160_000
    for number in range(min(total,MAX_PAGES)):
        text=' '.join((reader.pages[number].extract_text() or '').split())[:remaining]
        remaining-=len(text)
        if text:pages.append({'page':number+1,'text':text})
        if remaining<=0:break
    if sum(len(p['text']) for p in pages)<80:raise svc.SetupError('The PDF has no usable text layer; scanned pages need OCR.')
    return {'pages':pages,'total_pages':total,'pages_scanned':number+1,'truncated':number+1<total or remaining<=0}

def read_document(root,document,publisher):
    folder=root/'.runtime/news/documents';folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(document['url'].encode()).hexdigest();saved=folder/(key+'.json')
    if saved.exists():
        cached=json.loads(saved.read_text())
        if cached.get('fetched_at') and (datetime.now(timezone.utc)-datetime.fromisoformat(cached['fetched_at'])).total_seconds()<3600:
            return cached
    data=fetch_pdf(document['url'],publisher)
    target=folder/(key+'.'+uuid.uuid4().hex+'.pdf');target.write_bytes(data)
    try:
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'extract',str(target)],capture_output=True,text=True,timeout=20)
        if run.returncode:raise svc.SetupError('The linked PDF could not be parsed. It may need OCR or a newer PDF reader.')
        parsed=json.loads(run.stdout)
        parsed.update(fetched_at=datetime.now(timezone.utc).isoformat(),content_sha256=hashlib.sha256(data).hexdigest())
    except subprocess.TimeoutExpired:raise svc.SetupError('PDF extraction exceeded the reading time limit.') from None
    finally:target.unlink(missing_ok=True)
    temp=saved.with_name(saved.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(parsed));temp.replace(saved)
    return parsed

def collect(root,documents,item):
    evidence=[];status=[]
    for number,document in enumerate(documents[:2],1):
        try:
            parsed=read_document(root,document,item['publisher']);candidates=[]
            for page in parsed['pages']:
                words=page['text'].split()
                for start in range(0,len(words),320):
                    text=' '.join(words[start:start+360])
                    candidates.append({'chunk_id':f'NEWS:D{number}:P{page["page"]}:C{start//320+1}',
                        'source_id':'NEWS_DOC','authority_type':'linked_regulator_document','text':text,
                        'title':document['title'],'heading':document['title'],'url':document['url'],
                        'pdf_page':page['page'],'locator':f'PDF page {page["page"]}',
                        'captured_date':parsed.get('fetched_at',datetime.now(timezone.utc).isoformat())[:10]})
            # Select passages about findings and mechanisms; do not send an entire long order.
            from aml_research import tokens
            focus=set(tokens(item['title']+' '+item.get('description','')))
            key_terms={'fail','failure','deficiency','monitoring','transaction','suspicious','customer','penalty','violation','finding','risk','control','laundering'}
            def rank(c):
                terms=set(tokens(c['text']));return len(terms&focus)+2*len(terms&key_terms)
            selected=sorted(candidates,key=rank,reverse=True)[:6]
            evidence.extend(selected)
            status.append({**document,'state':'read','total_pages':parsed['total_pages'],'pages_scanned':parsed['pages_scanned'],
                'truncated':parsed['truncated'],'selected_pages':sorted({c['pdf_page'] for c in selected})})
        except (svc.SetupError,ValueError,OSError) as exc:
            status.append({**document,'state':'unavailable','reason':str(exc) if isinstance(exc,svc.SetupError) else 'The PDF could not be read.'})
    return evidence,status

if __name__=='__main__':
    try:print(json.dumps(extract(sys.argv[2])))
    except Exception:sys.exit(1)
