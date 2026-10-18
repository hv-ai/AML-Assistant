"""Check passage coverage for curated questions; not an answer accuracy score."""
import json
from pathlib import Path
from aml_research import ROOT,load_index

def normalize(text):return ' '.join(text.lower().replace('‑','-').replace('–','-').split())

def evaluate():
    index=load_index();cases=json.loads((ROOT/'evaluation/typology_cases.json').read_text());results=[]
    for c in cases:
        hits=index.search(c['question'],5)
        relevant=[h for h in hits if h['source_id'] in c['source_ids']]
        matches=[h for h in relevant if any(normalize(p) in normalize(h['text']) for p in c['key_phrases'])]
        results.append({**c,'pass':bool(matches),'matched_passages':[h['chunk_id'] for h in matches], 'retrieved_passages':[h['chunk_id'] for h in hits]})
    report={'kind':'development passage-coverage checks; not held-out evaluation or semantic answer accuracy','total':len(results),'passed':sum(r['pass'] for r in results),'cases':results}
    (ROOT/'reports/typology_retrieval.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    r=evaluate();print(f"Passage checks: {r['passed']}/{r['total']}")
    for c in r['cases']:
        if not c['pass']:print('MISSING',c['id'],c['question'],c['retrieved_passages'])
