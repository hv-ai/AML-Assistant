from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hosted

class HostedPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=hosted.create_app({'TESTING':True,'SECRET_KEY':'x'*40,'PUBLIC_ORIGIN':'https://pilot.example',
            'BUDGET_PATH':Path(self.temp.name)/'limits.sqlite3','PILOT_VISITOR_DAILY':2})
        self.client=self.app.test_client()
    def tearDown(self):self.temp.cleanup()
    def post(self,path,body,origin='https://pilot.example'):
        return self.client.post(path,json=body,base_url='https://pilot.example',headers={'Origin':origin})
    def test_cross_origin_and_model_overrides_rejected(self):
        self.assertEqual(self.post('/api/ask',{'question':'KYC'},'https://evil.test').status_code,403)
        self.assertEqual(self.post('/api/ask',{'model':'costly-model'}).status_code,400)
    def test_no_account_or_secret_configuration_routes(self):
        for path in ['/api/register','/api/login','/api/models','/api/history']:
            self.assertEqual(self.post(path,{}).status_code,404)
        self.assertEqual(self.client.get('/.env',base_url='https://pilot.example').status_code,404)
    def test_fixed_model_and_per_visitor_ai_limit(self):
        with patch.object(hosted.svc,'ask',return_value={'status':'supported'}) as ask:
            self.assertEqual(self.post('/api/ask',{'question':'KYC'}).status_code,200)
            self.assertEqual(self.post('/api/ask',{'question':'CDD'}).status_code,200)
            self.assertEqual(self.post('/api/ask',{'question':'EDD'}).status_code,429)
            self.assertEqual(ask.call_count,2)
            self.assertNotIn('model',ask.call_args.kwargs)
    def test_keyword_search_does_not_spend_generation_allowance(self):
        with patch.object(hosted.svc,'ask',return_value={'status':'supported'}):
            for _ in range(3):self.assertEqual(self.post('/api/ask',{'question':'KYC','generate':False}).status_code,200)
    def test_public_refresh_cannot_bypass_shared_cache(self):
        with patch.object(hosted.news_service,'news_snapshot',return_value={'items':[]}) as listing:
            self.assertEqual(self.post('/api/news',{'refresh':True}).status_code,200)
            listing.assert_called_once_with()
    def test_host_and_deployment_configuration_fail_closed(self):
        self.assertEqual(self.client.get('/',base_url='https://other.example').status_code,403)
        self.app.config['SECRET_KEY']=''
        self.assertEqual(self.client.get('/',base_url='https://pilot.example').status_code,503)
        self.assertEqual(self.client.get('/healthz').status_code,200)

if __name__=='__main__':unittest.main()
