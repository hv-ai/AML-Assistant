import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import assistant_service as svc

EVIDENCE=[{'chunk_id':'S05:L1-L2','source_id':'S05','authority_type':'examination_guidance','heading':'Risk assessment','text':'Banks consider products, services, customers and geographic locations.','captured_date':'2026-10-16','currency_status':'pending'}]
def answer():
    return {'status':'supported','summary':'Risk assessment factors','claims':[{'text':'The captured guidance describes several risk factors.','evidence':[{'id':'S05:L1-L2','quote':'products, services, customers and geographic locations.'}]}],'checklist':[],'limitations':['Currency review pending.']}

class ServiceTests(unittest.TestCase):
    def test_selected_evidence_inserts_original_quote(self):
        a=answer();a['claims'][0]['evidence']=[{'id':'E001'}]
        checked=svc.validate_answer(a,EVIDENCE)
        ref=checked['claims'][0]['evidence'][0]
        self.assertEqual(ref['id'],EVIDENCE[0]['chunk_id'])
        self.assertEqual(ref['quote'],EVIDENCE[0]['text'])
    def test_unpadded_real_selection_is_normalized(self):
        a=answer();a['claims'][0]['evidence']=[{'id':'E1'}]
        self.assertEqual(svc.validate_answer(a,EVIDENCE)['claims'][0]['evidence'][0]['quote'],EVIDENCE[0]['text'])

    def test_uncited_frequency_claim_is_omitted(self):
        a=answer();a['claims'][0]['text']='Victim payments are typically one-time transactions.'
        checked=svc.validate_answer(a,EVIDENCE)
        self.assertEqual(checked['status'],'insufficient');self.assertEqual(checked['claims'],[])
    def test_historical_date_does_not_prove_ruling_is_not_current_law(self):
        a=answer();a['claims'][0]['text']='This old ruling does not constitute current law.'
        self.assertEqual(svc.validate_answer(a,EVIDENCE)['status'],'insufficient')

    def test_advice_cannot_be_upgraded_to_must(self):
        a=answer();a['claims'][0]['text']='Banks must consider all of these factors.'
        self.assertEqual(svc.validate_answer(a,EVIDENCE)['status'],'insufficient')
    def test_supported_claim_survives_omission_of_an_overclaim(self):
        a=answer();a['claims'].append({'text':'This old guidance is no longer law.','evidence':a['claims'][0]['evidence']})
        checked=svc.validate_answer(a,EVIDENCE)
        self.assertEqual(checked['status'],'supported');self.assertEqual(len(checked['claims']),1)

    def test_invented_evidence_selection_is_rejected(self):
        a=answer();a['claims'][0]['evidence']=[{'id':'E999'}]
        with self.assertRaises(ValueError):svc.validate_answer(a,EVIDENCE)
    def test_valid_evidence_is_accepted(self):
        self.assertEqual(svc.validate_answer(answer(),EVIDENCE)['status'],'supported')
    def test_unknown_citation_rejected(self):
        a=answer();a['claims'][0]['evidence'][0]['id']='S99'
        with self.assertRaises(ValueError):svc.validate_answer(a,EVIDENCE)
    def test_invented_quote_rejected(self):
        a=answer();a['claims'][0]['evidence'][0]['quote']='Every bank must update its assessment every month.'
        with self.assertRaises(ValueError):svc.validate_answer(a,EVIDENCE)
    def test_uncited_claim_rejected(self):
        a=answer();a['claims'][0]['evidence']=[]
        with self.assertRaises(ValueError):svc.validate_answer(a,EVIDENCE)
    def test_abstention_cannot_smuggle_claims(self):
        a=answer();a['status']='insufficient'
        with self.assertRaises(ValueError):svc.validate_answer(a,EVIDENCE)
    def test_search_does_not_call_provider(self):
        with patch.object(svc,'provider',side_effect=AssertionError('Network forbidden')):
            result=svc.ask('What should a risk assessment cover?',generate=False)
        self.assertEqual(result['status'],'evidence_only')
    def test_call_cap_persists_and_stops(self):
        with tempfile.TemporaryDirectory()as d,patch.object(svc,'ROOT',Path(d)),patch.object(svc,'CALL_LIMIT',1):
            svc.reserve_call()
            with self.assertRaises(svc.SetupError):svc.reserve_call()
            self.assertEqual(svc.usage_state()['attempts'],1)
    def test_completed_answer_cached_and_revalidated(self):
        response={'choices':[{'message':{'content':json.dumps(answer())}}],'usage':{'prompt_tokens':120,'completion_tokens':80}}
        class Index:
            def search(self,*args):return EVIDENCE
        with tempfile.TemporaryDirectory()as d,patch.object(svc,'ROOT',Path(d)),patch.object(svc,'settings',return_value={'NEBIUS_API_KEY':'test','NEBIUS_MODEL':'test-model'}),patch.object(svc,'load_index',return_value=Index()),patch.object(svc,'provider',return_value=response)as provider:
            a=svc.ask('What factors are considered?');b=svc.ask('What factors are considered?')
            self.assertFalse(a['cached']);self.assertTrue(b['cached']);self.assertEqual(provider.call_count,1)
            self.assertEqual(svc.usage_state()['input_tokens'],120)
    def test_reject_credential_redirect_host(self):
        with patch.dict('os.environ',{'NEBIUS_BASE_URL':'https://example.com/v1'}):
            with self.assertRaises(svc.SetupError):svc.settings()

if __name__=='__main__':unittest.main()
