"""Rebuild customer-control captures from checksum-verified official originals. No network calls."""
import json
from aml_research import ROOT,build_index
from ingest_typologies import extract

def main():
    path=ROOT/'config/source_manifest.json'
    manifest=json.loads(path.read_text())
    for source in json.loads((ROOT/'config/customer_control_sources.json').read_text()):
        raw=extract(source)
        raw['captured_date']='2026-10-18'
        raw['coverage']+=' Consolidated FAQ includes older answers and individual May 2026 updates; document update does not mean every answer was newly issued. FAQs are guidance, not the binding CFR text or the relief order itself.'
        (ROOT/'data/raw'/f"{source['source_id']}.json").write_text(json.dumps(raw,indent=2,ensure_ascii=False))
        meta={**source,'topic':'customer_controls','ingested':True,'eligible_for_retrieval_prototype':True,'review_status':'official_original_checksum_checked; FAQ_authority_not_binding_rule; applicability_review_required','effective_date':None,'notes':raw['coverage']}
        manifest['sources']=[s for s in manifest['sources'] if s['source_id']!=source['source_id']]+[meta]
    path.write_text(json.dumps(manifest,indent=2))
    chunks=build_index()
    print('Indexed',len(chunks),'passages from',len({c['source_id'] for c in chunks}),'documents')

if __name__=='__main__':main()
