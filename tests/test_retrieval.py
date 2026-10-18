import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aml_research import BM25, make_chunks, load_index


class RetrievalTests(unittest.TestCase):
    def test_no_overlap_does_not_fabricate_a_match(self):
        self.assertEqual(load_index().search('photosynthesis chlorophyll'), [])

    def test_stopword_only_query_returns_no_evidence(self):
        self.assertEqual(load_index().search('what is the'), [])

    def test_source_filter_is_enforced(self):
        hits = load_index().search('risk assessment', source_id='S05')
        self.assertTrue(hits)
        self.assertTrue(all(h['source_id'] == 'S05' for h in hits))

    def test_known_phrase_finds_required_source(self):
        hits = load_index().search('BSA officer authority independence resources')
        self.assertIn('S11', {h['source_id'] for h in hits})

    def test_k_is_bounded(self):
        with self.assertRaises(ValueError):
            load_index().search('risk', k=1000)

    def test_locators_and_text_match_captured_source(self):
        import json, re
        from aml_research import ROOT
        index = load_index()
        for c in index.chunks:
            source = json.loads((ROOT / 'data/raw' / (c['source_id'] + '.json')).read_text())
            start, end = map(int, re.search(r':L(\d+)-L(\d+)$', c['chunk_id']).groups())
            expected = '\n'.join(l['text'].strip() for l in source['lines']
                                 if start <= l['line'] <= end and l['text'].strip())
            self.assertEqual(c['text'], expected)


if __name__ == '__main__':
    unittest.main()

class ComparisonCoverageTests(unittest.TestCase):
    def test_comparison_retrieves_all_requested_concepts(self):
        results=load_index().search('What is the difference between KYC, CDD and EDD?',5)
        texts=' '.join(x['text'].lower() for x in results)
        self.assertIn('verification',texts)
        self.assertIn('customer due diligence',texts)
        self.assertIn('enhanced due diligence (edd)',texts)
        self.assertNotIn('S13',{x['source_id'] for x in results})
        self.assertIn('S24',{x['source_id'] for x in results})
    def test_spelled_out_comparison_keeps_enhanced_due_diligence(self):
        results=load_index().search('Compare customer due diligence and enhanced due diligence',5)
        self.assertTrue(any('enhanced due diligence (EDD)' in x['text'] for x in results))

class CustomerControlRegressionTests(unittest.TestCase):
    def test_practical_kyc_question_uses_customer_guidance(self):
        results=load_index().search('How does KYC helps with CDD and EDD. Top ways to do KYC',8)
        ids={c['source_id'] for c in results}
        self.assertTrue({'S10','S12','S24'} <= ids)
        self.assertNotIn('S14',ids)
        texts=' '.join(c['text'].lower() for c in results)
        for phrase in ['non-documentary','enhanced due diligence','nature and purpose']:
            self.assertIn(phrase,texts)
    def test_control_comparison_small_budget_still_contains_edd(self):
        results=load_index().search('Explain KYC CDD EDD',5)
        self.assertTrue(any('enhanced due diligence' in c['text'].lower() for c in results))
