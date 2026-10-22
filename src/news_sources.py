"""Bounded, cached discovery of AML-relevant news from official US agencies."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
import hashlib
import json
import uuid
import re
import xml.etree.ElementTree as ET
import assistant_service as svc
import risk_news

SOURCES = [
 {'publisher':'FinCEN','full_name':'Financial Crimes Enforcement Network','sector':'Cross-sector BSA / AML','url':'https://www.fincen.gov/news/press-releases','kind':'fincen','hosts':['www.fincen.gov'],'paths':[r'/news/news-releases/[a-zA-Z0-9-]+']},
 {'publisher':'OCC','full_name':'Office of the Comptroller of the Currency','sector':'National banks / federal savings associations','url':'https://www.occ.gov/rss/occ_news.xml','kind':'rss','hosts':['www.occ.gov','occ.gov'],'paths':[r'/news-issuances/news-releases/\d{4}/[a-zA-Z0-9-]+\.html',r'/news-issuances/bulletins/\d{4}/[a-zA-Z0-9-]+\.html']},
 {'publisher':'Federal Reserve','full_name':'Board of Governors of the Federal Reserve System','sector':'Federal Reserve-supervised institutions','url':'https://www.federalreserve.gov/feeds/press_all.xml','kind':'rss','hosts':['www.federalreserve.gov'],'paths':[r'/newsevents/pressreleases/[a-zA-Z0-9-]+\.htm']},
 {'publisher':'FDIC','full_name':'Federal Deposit Insurance Corporation','sector':'FDIC-supervised institutions','url':'https://www.fdic.gov/news/press-releases','kind':'html','hosts':['www.fdic.gov','fdic.gov'],'paths':[r'/news/press-releases/\d{4}/[a-zA-Z0-9-]+',r'/news/press-releases/\d{4}/[a-zA-Z0-9-]+\.html',r'/news/financial-institution-letters/\d{4}/[a-zA-Z0-9-]+']},
 {'publisher':'NCUA','full_name':'National Credit Union Administration','sector':'Credit unions','url':'https://ncua.gov/news/press-releases','kind':'html','hosts':['ncua.gov','www.ncua.gov'],'paths':[r'/newsroom/press-release/\d{4}/[a-zA-Z0-9-]+',r'/news/press-releases/\d{4}/[a-zA-Z0-9-]+']},
 {'publisher':'SEC','full_name':'Securities and Exchange Commission','sector':'Securities sector','url':'https://www.sec.gov/news/pressreleases.rss','kind':'rss','hosts':['www.sec.gov'],'paths':[r'/newsroom/press-releases/[a-zA-Z0-9-]+',r'/news/press-release/[a-zA-Z0-9-]+']},
 {'publisher':'CFTC','full_name':'Commodity Futures Trading Commission','sector':'Futures / derivatives sector','url':'https://www.cftc.gov/RSS/RSSGP/rssgp.xml','kind':'rss','hosts':['www.cftc.gov','cftc.gov'],'paths':[r'/PressRoom/PressReleases/[a-zA-Z0-9-]+']},
]
for source in SOURCES:
    extras={'OCC':['https://www.occ.gov/rss/occ_bulletins.xml'],
            'FDIC':['https://www.fdic.gov/news/financial-institution-letters'],
            'CFTC':['https://www.cftc.gov/RSS/RSSENF/rssenf.xml']}
    source['feeds']=[source['url']]+extras.get(source['publisher'],[])
SOURCES.extend(risk_news.ADDITIONAL_SOURCES)
for source in SOURCES:
    source.setdefault('source_type','official')
    source.setdefault('archive_urls',[])

AML_TERMS=re.compile(r'\b(?:AML|BSA|CFT|CIP|CDD|EDD|SARs?|CTRs?|FinCEN|OFAC)\b|anti[ -]?money[ -]?launder|money[ -]?launder|bank secrecy|illicit financ|terroris[tm].{0,15}financ|financ.{0,15}terroris|beneficial owner|customer (?:due diligence|identification)|suspicious activit|transaction monitoring|correspondent (?:bank|account)|sanctions|financial crim',re.I)

def agency_for_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.username or u.password or u.port or u.query or u.fragment or '%' in u.path or '..' in u.path:
        raise svc.SetupError('Only approved HTTPS agency news URLs can be fetched.')
    for source in SOURCES:
        if u.netloc in source['hosts'] and (url in source['feeds'] or url in source.get('archive_urls',[]) or any(re.fullmatch(p,u.path) for p in source['paths'])):
            return source
    raise svc.SetupError('This URL is outside the approved official agency news sources.')

def clean(text):
    from html import unescape
    text=re.sub(r'<[^>]+>',' ',text or '')
    return ' '.join(unescape(text).split())

def make_item(source,title,url,date,description=''):
    url=urljoin(source['url'],url).replace('http://','https://',1)
    try:
        owner=agency_for_url(url)
        if owner['publisher']!=source['publisher'] or url==source['url']:return None
        try:stamp=datetime.fromisoformat(date.replace('Z','+00:00'))
        except ValueError:
            try:stamp=parsedate_to_datetime(date)
            except (ValueError,TypeError):stamp=datetime.strptime(date,'%m/%d/%Y')
        if stamp.date()>datetime.now(timezone.utc).date():return None
    except (svc.SetupError,ValueError,TypeError):return None
    item = {'id':hashlib.sha256(url.encode()).hexdigest()[:16],'title':clean(title),'url':url,
            'published_date':stamp.date().isoformat(),'publisher':source['publisher'],
            'sector':source['sector'],'source_type':source.get('source_type','official'),
            'description':clean(description)[:(280 if source.get('source_type')=='industry_reporting' else 700)]}
    item['categories']=risk_news.categories(item,AML_TERMS)
    return item

def parse_rss(text,source):
    if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):raise svc.SetupError('Unsupported XML declaration in agency feed.')
    try:root=ET.fromstring(text.lstrip('\ufeff'))
    except ET.ParseError:raise svc.SetupError('The agency feed was not readable XML.') from None
    items=[]
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item','entry'):continue
        values={c.tag.split('}')[-1]:c for c in node}
        def val(name):
            child=values.get(name)
            return ''.join(child.itertext()).strip() if child is not None else ''
        link=val('link')
        if not link and values.get('link') is not None:link=values['link'].get('href','')
        item=make_item(source,val('title'),link,val('pubDate') or val('date') or val('updated') or val('published'),val('description') or val('summary'))
        if item:items.append(item)
    if not items:raise svc.SetupError('No dated agency announcements could be read from the feed.')
    return items[:500]

class IndexParser(HTMLParser):
    """Capture dated rows only, excluding navigation and unrelated links."""
    def __init__(self):super().__init__();self.depth=0;self.row=None;self.rows=[];self.anchor=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.row is None and (tag=='tr' or tag=='div' and 'views-row' in attrs.get('class','').split()):
            self.row={'links':[],'text':[],'date':''};self.depth=1
        elif self.row is not None and tag not in ('br','img','hr','meta','input','link'):self.depth+=1
        if self.row is not None:
            if tag=='a':self.anchor=[attrs.get('href',''),'']
            if tag=='time':self.row['date']=attrs.get('datetime','')
    def handle_data(self,text):
        if self.row is not None:self.row['text'].append(text)
        if self.anchor is not None:self.anchor[1]+=text
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor is not None:
            if self.row is not None:self.row['links'].append(self.anchor)
            self.anchor=None
        if self.row is not None and tag not in ('br','img','hr','meta','input','link'):
            self.depth-=1
            if self.depth==0:self.rows.append(self.row);self.row=None

def parse_index(text,source):
    parser=IndexParser();parser.feed(text);items=[]
    for row in parser.rows:
        body=' '.join(row['text']);date=row['date']
        if not date:
            m=re.search(r'\b\d{2}/\d{2}/\d{4}\b',body)
            if not m:continue
            date=m[0]
        for url,title in row['links']:
            item=make_item(source,title,url,date,body)
            if item:items.append(item);break
    if not items:raise svc.SetupError('No dated announcement rows could be read from the agency index.')
    return items[:500]

def parse_channel(text,source,parse_fincen):
    kind=source['kind']
    if kind=='release_dates':return risk_news.parse_release_dates(text,source,make_item)
    if kind=='fincen':return parse_fincen(text)
    if kind=='rss':return parse_rss(text,source)
    if kind=='auto':
        xml=re.match(r'\s*(?:<\?xml[^>]*>\s*)?<(?:rss|feed|rdf:RDF)\b',text)
        return parse_rss(text,source) if xml else risk_news.parse_html(text,source,make_item)
    if kind=='generic':return risk_news.parse_html(text,source,make_item)
    return parse_index(text,source)

def collect_news(root,fetch,parse_fincen,force=False):
    now=datetime.now(timezone.utc)
    def collect(source):
        path=root/'.runtime/news/feeds'/(source['publisher'].replace(' ','-').lower()+'.json')
        saved=json.loads(path.read_text()) if path.exists() else None
        info={k:source[k] for k in ('publisher','full_name','sector','url','source_type')}
        if saved and saved.get('schema_version')==3 and saved.get('channels_total')==len(source['feeds']) and not force and (now-datetime.fromisoformat(saved['fetched_at'])).total_seconds()<3600:
            return {**info,'state':'cached','fetched_at':saved['fetched_at'],'scanned':saved['scanned'],'items':saved['items'],'channels_checked':saved.get('channels_checked',1),'channels_total':saved.get('channels_total',1),'feed_errors':saved.get('feed_errors',[])}
        try:
            rows=[];failures=[]
            for feed in source['feeds']:
                try:
                    text=fetch(feed)
                    rows.extend(parse_channel(text,source,parse_fincen))
                except (svc.SetupError,ValueError) as exc:failures.append(str(exc))
            rows=list({r['id']:r for r in rows}.values())
            if not rows:raise svc.SetupError(failures[0] if failures else 'No announcements could be read.')
            for row in rows:
                row['sector']=source['sector'];row['source_type']=source.get('source_type','official')
                row['categories']=risk_news.categories(row,AML_TERMS)
            relevant=[x for x in rows if x['categories'] and '2026-01-01'<=x['published_date']<=now.date().isoformat()]
            data={'schema_version':3,'items':relevant,'scanned':len(rows),'fetched_at':now.isoformat(),'channels_checked':len(source['feeds'])-len(failures),'channels_total':len(source['feeds']),'feed_errors':failures}
            path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(data));tmp.replace(path)
            return {**info,**data,'state':'fresh'}
        except (svc.SetupError,ValueError,OSError) as exc:
            if saved:return {**info,**saved,'state':'stale','error':str(exc)}
            return {**info,'items':[],'state':'unavailable','scanned':0,'fetched_at':None,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=7) as executor:results=list(executor.map(collect,SOURCES))
    unique={x['id']:x for result in results for x in result['items']}
    items=sorted(unique.values(),key=lambda x:(x['published_date'],x['publisher']),reverse=True)[:2000]
    if not items and all(x['state']=='unavailable' for x in results):raise svc.SetupError('Official agency news sources could not be reached. Please try again later.')
    return {'items':items,'sources':[{k:v for k,v in r.items() if k!='items'}|{'matches':len(r['items'])} for r in results],
            'fetched_at':now.isoformat(),'cached':all(r['state']=='cached' for r in results),
            'stale':any(r['state']=='stale' for r in results),
            'coverage':'Selected public publisher feeds and dated indexes, classified into AML, Fraud and Credit from titles and descriptions. Archive availability varies by publisher.'}
