import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import regulator_documents as docs
import news_service as news
import assistant_service as svc

ITEM={'publisher':'CFTC','url':'https://www.cftc.gov/PressRoom/PressReleases/9277-26','title':'AML monitoring failures'}
URL='https://www.cftc.gov/media/12345/enforder/download'
class RegulatorDocumentTests(unittest.TestCase):
    def test_only_direct_official_documents_are_discovered(self):
        html='<nav><a href="/unrelated.pdf">Privacy</a></nav><article><a href="'+URL+'#page=2">Consent order</a><a href="https://evil.test/report.pdf">Report</a><a href="/media/12345/enforder/download">Order duplicate</a></article>'
        self.assertEqual(docs.discover(html,ITEM),[{'url':URL,'title':'Consent order'}])
    def test_rejects_external_credential_encoded_and_query_urls(self):
        for url in ['http://www.cftc.gov/a.pdf','https://www.cftc.gov.evil.test/a.pdf','https://www.cftc.gov@evil.test/a.pdf','https://www.cftc.gov/a.pdf?target=internal','https://www.cftc.gov/%2e%2e/a.pdf','https://127.0.0.1/a.pdf','https://www.cftc.gov:443/a.pdf','https://www.sec.gov/a.pdf']:
            with self.subTest(url=url),self.assertRaises(svc.SetupError):docs.official_document(url,'CFTC')
    def test_failed_pdf_does_not_block_announcement(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(docs,'read_document',side_effect=svc.SetupError('PDF offline')):
            evidence,status=docs.collect(Path(folder),[{'url':URL,'title':'Order'}],ITEM)
            self.assertEqual(evidence,[]);self.assertEqual(status[0]['state'],'unavailable')
    def test_selected_evidence_keeps_pdf_page_and_limits_document_count(self):
        parsed={'pages':[{'page':3,'text':'The order describes monitoring failures in transaction inputs. '*30}],'total_pages':70,'pages_scanned':50,'truncated':True}
        with tempfile.TemporaryDirectory() as folder,patch.object(docs,'read_document',return_value=parsed) as read:
            evidence,status=docs.collect(Path(folder),[{'url':URL,'title':'Order'}]*3,ITEM)
            self.assertEqual(read.call_count,2);self.assertTrue(status[0]['truncated'])
            self.assertEqual(evidence[0]['pdf_page'],3);self.assertTrue(evidence[0]['chunk_id'].startswith('NEWS:D'))
    def test_pdf_insights_cannot_use_announcement_only(self):
        evidence=[{'chunk_id':'NEWS:P1','text':'The regulator issued an announcement on transaction monitoring.','source_id':'NEWS','heading':'Announcement','authority_type':'news_announcement'}]
        raw={'status':'supported','summary':'Case','claims':[{'text':'The regulator issued an announcement.','evidence':[{'id':'E001'}]}],'checklist':[],'limitations':[],
            'document_insights':[{'text':'The order describes a monitoring finding.','evidence':[{'id':'E001'}]}]}
        with self.assertRaises(ValueError):news.validate_brief(raw,evidence)
        raw['document_insights']=[];raw['suggested_actions']=[{'text':'Unrequested suggestion'}]
        self.assertNotIn('suggested_actions',news.validate_brief(raw,evidence))

if __name__=='__main__':unittest.main()
