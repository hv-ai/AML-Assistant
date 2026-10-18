import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import news_service as news
import news_sources
import assistant_service as svc

LISTING='''<div class="fincen-news-article__content"><div><time datetime="2026-10-15T12:00:00Z">date</time></div><div class="fincen-news-article__title"><a href="/news/news-releases/test-alert">Public AML alert</a></div><div class="fincen-news-article__body"><p>Selected announcement text.</p></div></div>'''
TEXT='FinCEN issued an alert asking financial institutions to review potentially suspicious activity.'
ARTICLE='<nav>Navigation only</nav><article><div class="field field--name-body"><p>'+TEXT+'</p></div></article><footer><div class="field--name-body">Do not capture footer content</div></footer>'
EVIDENCE=[{'chunk_id':'NEWS:P1','source_id':'NEWS','authority_type':'news_announcement','heading':'Test','text':TEXT}]
def response():return {'status':'supported','summary':'Public alert','claims':[{'text':'The announcement describes an alert.','evidence':[{'id':'E001'}]}],'checklist':[],'limitations':['Announcement text only.'],'implications':[],'management_questions':[],'suggested_actions':[]}

class NewsTests(unittest.TestCase):
    def test_listing_contains_dates_titles_and_fixed_source(self):
        items=news.parse_listing(LISTING)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['published_date'],'2026-10-15')
        self.assertEqual(items[0]['url'],'https://www.fincen.gov/news/news-releases/test-alert')
    def test_external_or_credential_urls_rejected(self):
        for u in ['http://www.fincen.gov/news/press-releases','https://evil.test/news/press-releases','https://www.fincen.gov@evil.test/news/press-releases','https://www.fincen.gov/news/press-releases?x=1']:
            with self.assertRaises(svc.SetupError):news.safe_url(u)
    def test_article_does_not_capture_footer_or_navigation(self):
        self.assertEqual(news.article_text(ARTICLE),TEXT)
        with self.assertRaises(svc.SetupError):news.article_text('<div class="field--name-body">'+TEXT+'</div>')
    def test_failed_refresh_is_labeled_stale(self):
        with tempfile.TemporaryDirectory() as d,patch.object(news_sources,'SOURCES',news_sources.SOURCES[:1]),patch.object(news,'ROOT',Path(d)),patch.object(news,'fetch_html',return_value=LISTING) as fetch:
            news.news_list();news.news_list();self.assertEqual(fetch.call_count,1)
            fetch.side_effect=svc.SetupError('Offline')
            result=news.news_list(force=True)
            self.assertTrue(result['stale']);self.assertEqual(result['sources'][0]['error'],'Offline')
    def test_analysis_must_have_real_evidence(self):
        raw=response();raw['implications']=[{'text':'A suggested discussion point','evidence':[{'id':'E999'}]}]
        with self.assertRaises(ValueError):news.validate_brief(raw,EVIDENCE)
    def test_policy_only_fact_is_rejected(self):
        evidence=[{**EVIDENCE[0],'chunk_id':'S05:L1','source_id':'S05'}]
        with self.assertRaises(ValueError):news.validate_brief(response(),evidence)
    def test_brief_reuses_cache_and_never_fetches_client_url(self):
        with tempfile.TemporaryDirectory() as d,patch.object(news_sources,'SOURCES',news_sources.SOURCES[:1]),patch.object(news,'ROOT',Path(d)),patch.object(svc,'ROOT',Path(d)),patch.object(news,'fetch_html',side_effect=lambda u:LISTING if u==news.INDEX_URL else ARTICLE),patch.object(svc,'settings',return_value={'NEBIUS_MODEL':'test'}),patch.object(svc,'load_index') as index,patch.object(svc,'provider',return_value={'choices':[{'message':{'content':json.dumps(response())}}],'usage':{}}) as provider:
            index.return_value.search.return_value=[]
            item=news.news_list()['items'][0]
            a=news.brief(item['id']);b=news.brief(item['id'])
            self.assertFalse(a['cached']);self.assertTrue(b['cached']);self.assertEqual(provider.call_count,1)
            self.assertEqual(a['claims'][0]['evidence'][0]['quote'],TEXT)
    def test_analysis_keeps_safe_sentences_when_an_obligation_is_omitted(self):
        raw=response();raw['implications']=[{'text':'This may warrant reviewing relevant customer activity. Every bank must deploy a new monitoring system.','evidence':[{'id':'E001'}]}]
        checked=news.validate_brief(raw,EVIDENCE)
        self.assertEqual(checked['implications'][0]['text'],'This may warrant reviewing relevant customer activity.')
        self.assertNotIn('must',checked['implications'][0]['text'])
    def test_executive_summary_resolves_real_announcement_quotes(self):
        raw=response();raw['executive_summary']={'text':'FinCEN issued an alert.','evidence':[{'id':'E001'}]}
        checked=news.validate_brief(raw,EVIDENCE)
        self.assertEqual(checked['executive_summary']['evidence'][0]['quote'],TEXT)
        self.assertEqual(raw['executive_summary']['evidence'][0]['id'],'E001')
    def test_executive_summary_rejects_invented_citations(self):
        raw=response();raw['executive_summary']={'text':'An announcement.','evidence':[{'id':'E999'}]}
        with self.assertRaises(ValueError):news.validate_brief(raw,EVIDENCE)
    def test_unsupported_brief_cannot_contain_factual_summary(self):
        raw=response();raw.update(status='insufficient',claims=[],executive_summary={'text':'An announcement.','evidence':[{'id':'E001'}]})
        with self.assertRaises(ValueError):news.validate_brief(raw,EVIDENCE)
    def test_validator_does_not_mutate_model_selections(self):
        raw=response();news.validate_brief(raw,EVIDENCE)
        self.assertEqual(raw['claims'][0]['evidence'][0]['id'],'E001')

if __name__=='__main__':unittest.main()
