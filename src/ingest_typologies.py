"""Rebuild typology extracts from verified, locally saved official originals.

Run with a Python environment containing pypdf. This script makes no network or
model calls. Original download URLs and checksums live in typology_sources.json.
"""
import hashlib
import json
from pathlib import Path
import re
from pypdf import PdfReader
from news_service import article_text
from aml_research import build_index

ROOT=Path(__file__).resolve().parents[1]

def extract(source):
    original=ROOT/source['original_path']
    data=original.read_bytes()
    if hashlib.sha256(data).hexdigest()!=source['original_sha256']:
        raise ValueError('Original checksum mismatch: '+source['source_id'])
    lines=[]
    if original.suffix=='.pdf':
        reader=PdfReader(original)
        for number,page in enumerate(reader.pages,1):
            # Treasury cover, contents, participants and methodology are not
            # substantive typology evidence. Preserve the entire analysis body.
            if source['source_id']=='S14' and not 5<=number<=76:continue
            text=page.extract_text() or ''
            text=text.replace('\u00ad','').replace('\x00','')
            if len(text.strip())<80:continue
            lines.append({'line':len(lines)+1,'text':f'### {source["title"]} · PDF page {number}','page':number})
            lines.append({'line':len(lines)+1,'text':text.strip(),'page':number})
        method='pypdf_page_text_extract'
        coverage='Substantive PDF pages, preserved page by page. Extracted text includes footnotes; PDF page numbers are one-based physical pages, not printed page labels.'
        if source['source_id']=='S14':coverage+=' Pages 5–76 indexed; cover/contents and final administrative pages omitted.'
    else:
        text=article_text(data.decode('utf-8'))
        for paragraph in text.splitlines():
            if paragraph.strip():lines.append({'line':len(lines)+1,'text':paragraph.strip()})
        method='official_html_article_text_extract'
        coverage='Main article body extracted from saved official HTML; navigation/footer excluded. Extract line numbers are local locators, not official paragraph numbers.'
    if not lines:raise ValueError('No content extracted')
    return {'source_id':source['source_id'],'url':source['url'],'captured_date':'2026-10-17','capture_method':method,'coverage':coverage,'original_sha256':source['original_sha256'],'original_path':source['original_path'],'extract_line_range':[1,len(lines)],'lines':lines}

def main():
    path=ROOT/'config/source_manifest.json'
    manifest=json.loads(path.read_text())
    sources=json.loads((ROOT/'config/typology_sources.json').read_text())
    for source in sources:
        raw=extract(source)
        (ROOT/'data/raw'/f'{source["source_id"]}.json').write_text(json.dumps(raw,indent=2,ensure_ascii=False))
        meta={**source,'topic':','.join(source['topics']),'ingested':True,'eligible_for_retrieval_prototype':True,'review_status':'official_document_and_publication_checked; typology_research_only; legal_currency_review_pending','effective_date':None,'notes':'Risk indicators support investigation, not a finding of criminality. Advisory/risk-assessment material is not a new legal obligation. Preserve publication date, geographic scope, historical context and source-specific qualifications. FATF/Egmont material is international context, not US law.'}
        manifest['sources']=[s for s in manifest['sources'] if s['source_id']!=source['source_id']]+[meta]
        print(source['source_id'],len(raw['lines']),'extract lines',flush=True)
    path.write_text(json.dumps(manifest,indent=2))
    chunks=build_index()
    print('Indexed',len(chunks),'chunks from',len({c['source_id'] for c in chunks}),'sources.')

if __name__=='__main__':main()
