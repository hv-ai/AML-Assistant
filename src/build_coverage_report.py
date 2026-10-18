"""Build the current source/verification report without model calls."""
from pathlib import Path
import collections
import html
import json
ROOT=Path(__file__).resolve().parents[1]

def main():
    esc=html.escape
    topics=json.loads((ROOT/'config/typology_topics.json').read_text())
    manifest=json.loads((ROOT/'config/source_manifest.json').read_text())
    metadata={s['source_id']:s for s in manifest['sources']}
    chunks=json.loads((ROOT/'data/processed/chunks.json').read_text())
    retrieval=json.loads((ROOT/'reports/typology_retrieval.json').read_text())
    live=json.loads((ROOT/'reports/typology_live_checks.json').read_text())
    checks={r['topic']:r for r in live['checks']}
    records=[]
    for t in topics:
        cases=[c for c in retrieval['cases'] if c['topic']==t['id']]
        sample=checks.get(t['id'],{})
        result_path=ROOT/sample.get('result_path','missing')
        answer=json.loads(result_path.read_text()) if result_path.is_file() else {}
        records.append({**t,'source_status':'dedicated official source material indexed; historical tests predate latest corpus revision','retrieval_checks':len(cases),'retrieval_passed':sum(c['pass'] for c in cases),'live_citation_check':sample.get('status','not run'),'retained_sample_claims':len(answer.get('claims',[])),'answer_accuracy':'not scored; expert review pending','source_details':[{k:metadata[sid].get(k) for k in ('source_id','title','issuer','published_date','authority_type','url')} for sid in t['source_ids']]})
    report={'audit_date':'2026-10-18','scope':'Seven selected AML research topics (methods, channels and underlying crimes); not every possible AML risk, scenario, jurisdiction or legal obligation.','indexed_documents':len({c['source_id'] for c in chunks}),'indexed_passages':len(chunks),'requested_topics_with_dedicated_sources':len(records),'development_retrieval_passed':retrieval['passed'],'development_retrieval_total':retrieval['total'],'live_citation_checks_supported':sum(r['live_citation_check']=='supported' for r in records),'live_citation_checks_total':len(records),'answer_accuracy':'Not a held-out benchmark; citations resolve and quotes match, but semantic support and applicability still require expert review.','topics':records,'broader_risks':'The Treasury assessment adds material on other areas, but the earlier 20-topic audit has not been re-validated beyond these seven areas.','generation_guards':'Unknown references rejected. Valid numeric selection formatting normalized. Some unsupported frequency, stronger-modality and legal-currency assertions omitted; this is not complete entailment checking.'}
    for suffix in ('json','html'):
        p=ROOT/f'reports/aml_typology_coverage.{suffix}'
        old=ROOT/f'reports/aml_typology_coverage_initial.{suffix}'
        if p.exists() and not old.exists():old.write_bytes(p.read_bytes())
    (ROOT/'reports/aml_typology_coverage.json').write_text(json.dumps(report,indent=2))
    rows=''
    for t in records:
        refs=''.join(f'<li><a href="{esc(s["url"])}">{esc(s["issuer"])} · {esc(s["title"])}</a><small>Published {esc(s["published_date"] or "date not specified")} · {esc(s["authority_type"].replace("_"," "))}</small></li>' for s in t['source_details'])
        rows+=f'<tr><td><strong>{esc(t["label"])}</strong><p>Dedicated source material indexed</p></td><td><ul>{refs}</ul></td><td>{t["retrieval_passed"]}/{t["retrieval_checks"]} passage checks<br><small>Live cited response: {esc(t["live_citation_check"])}; {t["retained_sample_claims"]} claims retained after checks.</small></td></tr>'
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AML typology source coverage</title><link rel="stylesheet" href="../web/coverage.css"></head><body><main><p class="eyebrow">AML REVIEW DESK · SOURCE COVERAGE · 18 OCT 2026</p><h1>Selected AML topics, with explicit coverage gaps.</h1><p class="intro">The library now includes {report['indexed_documents']} official documents and {report['indexed_passages']} passages. The seven shortcuts are selected research topics, not a complete or uniform taxonomy.</p><div class="metrics"><div><strong>7 / 7</strong><span>Areas with dedicated sources</span></div><div><strong>{retrieval['passed']} / {retrieval['total']}</strong><span>Development passage checks</span></div><div><strong>{report['live_citation_checks_supported']} / 7</strong><span>Live cited-response checks</span></div></div><p class="note">The displayed topic checks were run on the October 17 corpus; they have not been rerun as a held-out benchmark on this revision. These are prototype coverage and pipeline checks, not an answer-accuracy score. Source dates, geographic scope, applicability and the meaning of each citation still require review. The initial gap audit is retained separately.</p><table><thead><tr><th>Area</th><th>Primary source material</th><th>Checks</th></tr></thead><tbody>{rows}</tbody></table><h2>What you can investigate</h2><p>Typology explanations, source-supported warning indicators, legitimate explanations and qualifications, and evidence an analyst may request. Use the seven topic buttons in the app, then inspect supporting passages or ask a more specific follow-up question.</p><h2>How evidence is handled</h2><p>Original public files and their checksums are saved locally. PDF citations identify physical PDF pages; extract line numbers are local locators. The model selects evidence IDs and the app inserts the original text. Unknown IDs are rejected, and some observable overclaims are omitted. These checks do not establish that every paraphrase is fully supported.</p><h2>Customer controls: updated source</h2><p>FinCEN consolidated CDD FAQs, updated May 6, 2026, are now indexed with physical PDF page locators. Individual answers retain their issue/update dates. FAQs clarify requirements but are not the binding CFR text or the relief order itself. The 2014 KYC testimony is historical background, excluded from ordinary control-question routing.</p><h2>Coverage gaps beyond the shortcuts</h2><p>Further targeted source and answer validation is needed for professional laundering networks, underground banking/hawala, bulk cash smuggling, real estate, gambling, and laundering proceeds of fraud/cybercrime, drugs and environmental crime. A mention in a broad national assessment does not establish dedicated coverage. Terrorist financing and sanctions evasion are related but distinct risk domains.</p><h2>Scope and remaining work</h2><p>US banking is the main research scope; FATF/Egmont material is international context. Advisories and risk assessments are distinguished from regulations. Historical publications are dated and are not treated as verified current-law determinations. News briefs remain separate from the question-answer library.</p><p>The 2026 Treasury assessment includes other threats and channels, but coverage outside these seven areas still needs targeted passage and answer review. A red flag is an investigative signal, not proof of wrongdoing. This app does not make customer, SAR-filing or compliance determinations.</p><p class="footer">Source-backed research prototype · Expert answer review and a held-out evaluation remain outstanding.</p></main></body></html>'''
    (ROOT/'reports/aml_typology_coverage.html').write_text(page)
    print('Coverage report:',len(records),'areas;',report['live_citation_checks_supported'],'live cited responses')

if __name__=='__main__':main()
