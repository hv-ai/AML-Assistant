import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aml_research import ROOT,load_index
import hybrid_retrieval as hybrid
import assistant_service as svc

class ResearchModeTests(unittest.TestCase):
    def test_advanced_topics_have_relevant_assessment_passages(self):
        for question,phrase in [('Hawala laundering patterns','hawala'),('Real estate laundering','real estate'),('Bulk cash smuggling','cash'),('Gambling casino laundering','casino')]:
            with self.subTest(question=question):
                rows=load_index().search(question,5)
                self.assertTrue(rows)
                self.assertTrue(any(phrase in r['text'].lower() for r in rows))
                self.assertTrue(set(hybrid.eligible_sources(question)) >= {r['source_id'] for r in rows})
    def test_red_flag_mode_requests_evidence_checks_without_customer_risk_scoring(self):
        evidence=[{'chunk_id':'A','heading':'Observed patterns','authority_type':'advisory','text':'Unusual incoming payments can warrant contextual review.'}]
        raw={'status':'supported','summary':'Patterns to investigate','claims':[{'title':'Incoming activity','text':'Unusual incoming payments can warrant contextual review.','evidence':['E001']}],'checklist':[{'item':'Review the context of incoming payments.','basis':'reviewer_suggestion','evidence':['E001']}],'limitations':['An indicator alone is not proof.']}
        result={'choices':[{'message':{'content':json.dumps(raw)}}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(svc,'ROOT',Path(folder)),patch.object(hybrid,'retrieve',return_value=(evidence,{'method':'BM25','degraded':False})),patch.object(svc,'settings',return_value={'NEBIUS_API_KEY':'fake-test-key','NEBIUS_MODEL':'test'}),patch.object(svc,'reserve_call'),patch.object(svc,'record_usage'),patch.object(svc,'provider',return_value=result) as provider:
            answer=svc.ask('Review possible money mule patterns',mode='red_flags')
            self.assertEqual(answer['research_mode'],'red_flags')
            self.assertEqual(len(answer['checklist']),1)
            prompt=provider.call_args.args[1]['messages'][0]['content']
            self.assertIn('specific follow-up evidence requests',prompt)
            self.assertIn('Do not invent thresholds, risk scores',prompt)
    def test_general_hawala_query_excludes_case_specific_identity_context(self):
        rows=[{'id':'E001','chunk_id':'A','text':'A customer presenting a Chinese passport receives funds.'},{'id':'E002','chunk_id':'A','text':'Unexpected incoming payments merit contextual review.'}]
        self.assertEqual([r['id'] for r in svc.bounded_catalog(rows,'Hawala red flags')],['E002'])
        evidence=[{'chunk_id':'A','heading':'Context','authority_type':'advisory','text':'A customer presenting a Chinese passport receives funds.'}]
        raw={'status':'supported','summary':'Context','claims':[{'text':'A customer with a Chinese passport warrants review.','evidence':['E001']}],'checklist':[],'limitations':[]}
        answer=svc.validate_answer(raw,evidence,question='General hawala indicators')
        self.assertEqual(answer['status'],'insufficient');self.assertFalse(answer['claims'])
        evidence[0].update(issuer='US Treasury',text='Unregistered money transmission can warrant contextual review.')
        raw['claims']=[{'text':'The FFIEC guidance describes unregistered money transmission.','evidence':['E001']}]
        self.assertFalse(svc.validate_answer(raw,evidence,question='General hawala indicators')['claims'])
    def test_mode_is_not_a_new_corpus_or_detection_claim(self):
        topics=json.loads((ROOT/'config/additional_research_topics.json').read_text())
        self.assertEqual(len(topics),6)
        available={r['source_id'] for r in load_index().chunks}
        for topic in topics:
            self.assertTrue(set(topic['source_ids'])<=available)
            self.assertIn('assessment',topic['coverage_basis'].lower())

if __name__=='__main__':unittest.main()
