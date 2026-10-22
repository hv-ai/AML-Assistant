"""Risk categories and public publisher adapters. No model calls during collection."""
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin
import json
import re

CATEGORIES = {'aml':'AML', 'fraud':'Fraud', 'credit':'Credit'}
FRAUD = re.compile(r'\bfraud\b|\bscams?\b|identity theft|synthetic identit|account takeover|impersonat|phishing|business email compromise|\bponzi\b|credit washing|stolen identit', re.I)
CREDIT = re.compile(r'delinquen|charge.off|nonperforming|non-performing|underwriting|credit (?:risk|quality|loss|access|conditions|standards|performance)|loan (?:loss|performance|demand|standards|delinquenc)|lending (?:standards|practices|regulat|risk)|\bdefaults?\b|household debt|consumer (?:debt|credit)|mortgage (?:lending|debt|delinquenc|market)|commercial real estate|senior loan officer|household.*credit|credit.*household|fair lending|loan officer opinion|credit washing|adverse.action|credit (?:scor|market|report)|lending (?:decision|growth)|loan (?:originat|growth)', re.I)

def categories(item, aml_terms):
    text=item.get('title','')+' '+item.get('description','')
    found=[]
    if item.get('publisher') in ('FinCEN','OFAC','FATF','AUSTRAC','FINTRAC') or aml_terms.search(text):found.append('aml')
    if FRAUD.search(text):found.append('fraud')
    if CREDIT.search(text):found.append('credit')
    return found

def source(name,url,paths,sector,kind='generic',hosts=None,feeds=None,archives=None,source_type='official'):
    from urllib.parse import urlsplit
    return {'publisher':name,'full_name':name,'sector':sector,'url':url,'kind':kind,
            'hosts':hosts or [urlsplit(url).netloc],'paths':paths,'feeds':feeds or [url],
            'archive_urls':archives or [],'source_type':source_type}

# Only these exact listing URLs and publisher-specific article paths may be fetched.
ADDITIONAL_SOURCES = [
 source('FBI IC3','https://www.ic3.gov/PSA/rss',[r'/PSA/\d{4}/[A-Za-z0-9-]+'], 'Cyber-enabled fraud',kind='rss',archives=['https://www.ic3.gov/PSA/2026','https://www.ic3.gov/PSA']),
 source('FTC','https://www.ftc.gov/news-events/news/press-releases',[r'/news-events/news/press-releases/\d{4}/\d{2}/[A-Za-z0-9-]+'],'Consumer fraud and protection'),
 source('CFPB','https://www.consumerfinance.gov/about-us/newsroom/feed/',[r'/about-us/newsroom/[A-Za-z0-9-]+/'],'Consumer lending and payments',kind='rss',archives=['https://www.consumerfinance.gov/about-us/newsroom/']),
 source('DOJ','https://www.justice.gov/news',[r'/(?:opa|usao-[a-z-]+|criminal[a-z/-]*)/pr/[A-Za-z0-9-]+'],'Enforcement and prosecutions'),
 source('FBI','https://www.fbi.gov/news',[r'/news/(?:press-releases|stories)/[A-Za-z0-9-]+'],'Financial crime investigations'),
 source('US Treasury','https://home.treasury.gov/news/press-releases',[r'/news/press-releases/[A-Za-z0-9-]+'],'Financial policy and illicit finance'),
 source('OFAC','https://ofac.treasury.gov/recent-actions',[r'/recent-actions/[A-Za-z0-9-]+'],'Sanctions and evasion'),
 source('New York Fed','https://www.newyorkfed.org/press',[r'/(?:newsevents/news/research|research|microeconomics)/[A-Za-z0-9/_.-]+'],'Household debt and credit',archives=['https://www.newyorkfed.org/press/2026']),
 source('Fed Lending Survey','https://www.federalreserve.gov/feeds/sloos.html',[r'/data/sloos/sloos-\d{6}\.htm',r'/newsevents/pressreleases/[A-Za-z0-9-]+\.htm'],'Lending standards and demand',kind='generic',feeds=['https://www.federalreserve.gov/data/sloos.htm'],archives=['https://www.federalreserve.gov/data/sloos.htm']),
 source('NY DFS','https://www.dfs.ny.gov/press-room',[r'/(?:reports-and-publications/press-releases|about/press)/[A-Za-z0-9/_.-]+'],'Financial services supervision'),
 source('FINRA','https://www.finra.org/media-center/newsreleases',[r'/(?:media-center/newsreleases|rules-guidance/notices)/[A-Za-z0-9/_.-]+'],'Securities supervision'),
 source('FCA','https://www.fca.org.uk/news',[r'/news/(?:press-releases|news-stories|statements|speeches|warnings)/[A-Za-z0-9-]+'],'UK financial services'),
 source('AUSTRAC','https://www.austrac.gov.au/news-and-media',[r'/news-and-media/(?:media-release|our-recent-work|financial-crime-guides)/[A-Za-z0-9-]+'],'Australian financial intelligence'),
 source('FINTRAC','https://fintrac-canafe.canada.ca/new-neuf/1-eng',[r'/(?:new-neuf|bulletins|intel|nouvelles)/[A-Za-z0-9/_.-]+'],'Canadian financial intelligence'),
 source('FATF','https://www.fatf-gafi.org/en/publications.html',[r'/en/(?:publications|the-fatf/news)/[A-Za-z0-9/_.-]+\.html'],'International financial crime standards'),
 source('BIS','https://www.bis.org/media/news',[r'/(?:press|publ|bcbs)/[A-Za-z0-9/_.-]+(?:\.htm|\.html)'],'International banking risk'),
 source('ECB Banking Supervision','https://www.bankingsupervision.europa.eu/press/html/index.en.html',[r'/press/[A-Za-z0-9/_.~%-]+\.en\.html'],'European bank supervision'),
 source('Bank of England','https://www.bankofengland.co.uk/news',[r'/(?:news|financial-stability-report|prudential-regulation/publication)/\d{4}/[A-Za-z0-9/-]+'],'UK credit and prudential risk'),
 source('TransUnion','https://newsroom.transunion.com/',[r'/[A-Za-z0-9-]+/'],'Consumer credit research',source_type='company_research'),
 source('Experian','https://www.experian.com/insights/',[r'/insights/[A-Za-z0-9-]+/'],'Consumer credit research',source_type='company_research'),
 source('Banking Dive','https://www.bankingdive.com/feeds/news/',[r'/news/[A-Za-z0-9-]+/\d+/'],'Banking industry reporting',kind='rss',source_type='industry_reporting'),
 source('Payments Dive','https://www.paymentsdive.com/feeds/news/',[r'/news/[A-Za-z0-9-]+/\d+/'],'Payments industry reporting',kind='rss',source_type='industry_reporting'),
 source('The Paypers','https://thepaypers.com/',[r'/(?:payments|fraud-and-fincrime|fintech|crypto-web3-and-cbdc|regulations|news)/[A-Za-z0-9/-]+'],'Payments and financial crime reporting',source_type='industry_reporting'),
 source('Finextra','https://www.finextra.com/',[r'/newsarticle/\d+/[A-Za-z0-9-]+'],'Financial services reporting',source_type='industry_reporting'),
 source('AML Intelligence','https://www.amlintelligence.com/',[r'/\d{4}/\d{2}/[A-Za-z0-9-]+/'],'Financial crime reporting',source_type='industry_reporting'),
]

DATE_PATTERN=re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b',re.I)

def publication_date(text):
    match=DATE_PATTERN.search(text or '')
    if not match:return ''
    value=match[0].replace('.','').replace(',','')
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%B %d %Y','%b %d %Y','%d %B %Y'):
        try:return datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    return ''

class Node:
    def __init__(self,tag='',attrs=None,parent=None):self.tag=tag;self.attrs=attrs or {};self.parent=parent;self.children=[];self.data=[]
    def text(self):return ' '.join(self.data+ [c.text() for c in self.children])

class Tree(HTMLParser):
    def __init__(self):super().__init__();self.root=Node();self.current=self.root;self.nodes=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        n=Node(tag,dict(attrs),self.current);self.current.children.append(n);self.nodes.append(n)
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):self.current=n
    def handle_endtag(self,tag):
        n=self.current
        while n.parent:
            if n.tag==tag:self.current=n.parent;return
            n=n.parent
    def handle_data(self,text):self.current.data.append(text.strip())

def parse_html(text,source,make_item):
    """Read dated publisher cards, not arbitrary navigation or invented dates."""
    tree=Tree();tree.feed(text);items={}
    for anchor in tree.nodes:
        if anchor.tag!='a' or len(anchor.text().strip())<15:continue
        href=anchor.attrs.get('href','');url=urljoin(source['url'],href)
        node=anchor;stamp='';description=''
        for _ in range(5):
            if not node:break
            if node.tag in ('nav','footer','header','body','html'):break
            body=node.text()
            times=[n.attrs.get('datetime','') for n in node.children if n.tag=='time']
            if len(set(DATE_PATTERN.findall(body)))>1:break
            stamp=publication_date(' '.join(times)+' '+body)
            if stamp:description=body;break
            node=node.parent
        if not stamp:
            # IC3's publisher-assigned identifier includes the exact issue date.
            m=re.search(r'/PSA/(20\d{2})/PSA(\d{2})(\d{2})(\d{2})(?:-|$)',url)
            if m and m[1][2:]==m[2]:stamp=f'{m[1]}-{m[3]}-{m[4]}'
        if not stamp:continue
        item=make_item(source,anchor.text(),url,stamp,description)
        if item:items[item['id']]=item
    # JSON-LD is often the only structured date on commercial publisher listings.
    def walk(value):
        if isinstance(value,dict):
            title=value.get('headline') or value.get('name');url=value.get('url');stamp=value.get('datePublished')
            if title and isinstance(url,str) and stamp:
                item=make_item(source,title,url,str(stamp)[:10],value.get('description',''))
                if item:items[item['id']]=item
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    for n in tree.nodes:
        if n.tag=='script' and n.attrs.get('type')=='application/ld+json':
            try:walk(json.loads(' '.join(n.data)))
            except (ValueError,TypeError):pass
    if not items:
        import assistant_service as svc
        raise svc.SetupError('No supported dated story cards were found on this publisher page.')
    return list(items.values())[:500]

for name,url in {
    'FCA':'https://www.fca.org.uk/news/rss.xml',
    'FINTRAC':'https://fintrac-canafe.canada.ca/rss/rss-eng.xml',
    'AML Intelligence':'https://www.amlintelligence.com/feed/',
    'TransUnion':'https://newsroom.transunion.com/feed/transunion/media_en-us/',
}.items():
    entry=next(s for s in ADDITIONAL_SOURCES if s['publisher']==name)
    entry['archive_urls']=list(dict.fromkeys(entry['archive_urls']+[entry['url']]))
    entry['feeds']=[url,entry['url']];entry['kind']='auto'

ADDITIONAL_SOURCES.extend([
 source('Fed Consumer Credit','https://www.federalreserve.gov/Releases/G19/releaseDates.json',[r'/[Rr]eleases/[Gg]19/\d{8}(?:/default\.htm|/)?'],'Consumer credit statistical releases',kind='release_dates'),
 source('Liberty Street Economics','https://libertystreeteconomics.newyorkfed.org/feed/',[r'/\d{4}/\d{2}/[A-Za-z0-9-]+/'],'New York Fed credit research',kind='rss',archives=['https://libertystreeteconomics.newyorkfed.org/household-finance/','https://libertystreeteconomics.newyorkfed.org/household-finance/page/2/']),
 source('MAS','https://www.mas.gov.sg/news',[r'/news/(?:media-releases|speeches|parliamentary-replies)/\d{4}/[A-Za-z0-9-]+'],'Singapore financial supervision'),
 source('Europol','https://www.europol.europa.eu/media-press/newsroom',[r'/media-press/newsroom/news/[A-Za-z0-9-]+'],'International financial crime operations'),
 source('ACFE','https://www.acfe.com/fraud-magazine/all-issues',[r'/fraud-magazine/(?:all-issues|[A-Za-z0-9-]+)/[A-Za-z0-9/-]+'],'Fraud investigation and research',source_type='industry_reporting'),
])

def parse_release_dates(text,source,make_item):
    """Federal Reserve G.19's public releaseDates.json gives exact issue dates."""
    rows=[]
    for year in json.loads(text):
        if year.get('yearValue')!='2026':continue
        for month in year.get('Months',[]):
            for stamp in month.get('Dates',[]):
                if not re.fullmatch(r'2026\d{4}',stamp):continue
                date_text=datetime.strptime(stamp,'%Y%m%d').date().isoformat()
                url='https://www.federalreserve.gov/releases/g19/'+stamp+'/default.htm'
                item=make_item(source,'Consumer Credit — G.19 release · '+date_text,url,date_text,'Federal Reserve statistical release on outstanding consumer credit, including revolving and nonrevolving credit. Open the brief for the reported figures and context.')
                if item:rows.append(item)
    return rows
