"""Collect public feeds and bounded configured archives; never call an LLM.

Run before packaging/deployment to preserve captured history across restarts.
"""
from pathlib import Path
import argparse
import sys
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import news_service as news
import news_sources as sources
import risk_news

def collect(backfill=False):
    previous=news._archive();fresh=news.news_list(force=True)
    rows={x['id']:x for x in previous['items']+fresh['items']}
    checks=[]
    def scan(task):
        source,url=task
        try:
            text=news.fetch_html(url)
            items=risk_news.parse_html(text,source,sources.make_item)
            return {'publisher':source['publisher'],'url':url,'state':'read','items':items}
        except Exception as exc:return {'publisher':source['publisher'],'url':url,'state':'unavailable','error':str(exc),'items':[]}
    if backfill:
        tasks=[(s,url) for s in sources.SOURCES for url in s.get('archive_urls',[])]
        for result in ThreadPoolExecutor(max_workers=6).map(scan,tasks):
            for item in result.pop('items'):
                if item['categories']:rows[item['id']]=item
            checks.append(result)
    items=sorted([x for x in rows.values() if '2026-01-01'<=x['published_date']<=datetime.now(timezone.utc).date().isoformat()],key=lambda x:(x['published_date'],x['id']),reverse=True)
    result={**fresh,'items':items,'archive_checks':checks,'archive_notice':'Captured 2026 publisher entries. Month filters show stored publication dates; coverage varies by source.'}
    news.write_json(news.ROOT/'data/news_archive.json',result)
    news.write_json(news.ROOT/'.runtime/news/archive.json',result)
    counts={c:sum(c in i.get('categories',[]) for i in items) for c in risk_news.CATEGORIES}
    return {'items':len(items),'categories':counts,'sources':[{k:s.get(k) for k in ('publisher','state','matches','error')} for s in fresh['sources']],'archive_checks':checks}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backfill',action='store_true');args=parser.parse_args()
    print(json.dumps(collect(args.backfill),indent=2))
