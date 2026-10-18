"""Development-only source retrieval smoke check, not an answer-quality benchmark."""
import csv
import json
from aml_research import ROOT, load_index


def main():
    index = load_index()
    cases = list(csv.DictReader((ROOT / 'evaluation/retrieval_cases.csv').open()))
    results = []
    for case in cases:
        if case['split'] != 'development':
            continue
        hits = index.search(case['question'], 5)
        expected = set(case['expected_source_ids'].split(';'))
        found = {h['source_id'] for h in hits}
        results.append({
            'id': case['id'], 'question': case['question'],
            'expected_sources': sorted(expected), 'retrieved_sources': sorted(found),
            'all_expected_sources_found': expected <= found,
            'chunk_ids': [h['chunk_id'] for h in hits],
        })
    report = {
        'configuration': 'BM25 lexical only',
        'measure': 'all expected sources present in top 5, development cases only',
        'limitation': 'Provisional author-assigned source labels, not reviewed passage gold labels. No answer generation tested. No held-out cases run.',
        'cases': len(results),
        'source_hits': sum(r['all_expected_sources_found'] for r in results),
        'results': results,
    }
    (ROOT / 'reports/retrieval_development.json').write_text(json.dumps(report, indent=2))
    print(f"Development source smoke check: {report['source_hits']}/{report['cases']}. Not an answer-quality result.")


if __name__ == '__main__':
    main()
