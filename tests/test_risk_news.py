from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import risk_news as risk
import news_sources as sources
import news_service as news
import assistant_service as svc

class RiskNewsTests(unittest.TestCase):
    def source(self,name):return next(s for s in sources.SOURCES if s['publisher']==name)
    def test_credit_release_archive_uses_publisher_dates_and_stable_links(self):
        data=[{'yearValue':'2026','Months':[{'Dates':['20260107','20260206']}]}]
        items=risk.parse_release_dates(json.dumps(data),self.source('Fed Consumer Credit'),sources.make_item)
        self.assertEqual([i['published_date'] for i in items],['2026-01-07','2026-02-06'])
        self.assertTrue(all(i['categories']==['credit'] for i in items))
        self.assertTrue(items[0]['url'].endswith('/20260107/default.htm'))
    def test_category_overlap_and_unrelated_news(self):
        classify=lambda title:risk.categories({'title':title},sources.AML_TERMS)
        self.assertEqual(classify('Money laundering through identity theft scams'),['aml','fraud'])
        self.assertEqual(classify('Household debt and delinquency transition rates'),['credit'])
        self.assertEqual(classify('Synthetic identity fraud and credit washing'),['fraud','credit'])
        self.assertEqual(classify('Bank appoints new chief executive'),[])
        self.assertEqual(classify('Credit union opens an office'),[])
    def test_dated_cards_keep_each_story_date_and_ignore_navigation(self):
        html='<nav><a href="/news/fake/123/">Fake fraud headline</a></nav><article><time datetime="2026-09-15">September 15, 2026</time><a href="/news/fraud-alert/123/">Account takeover fraud alert</a></article><article><time datetime="2026-08-20">August 20, 2026</time><a href="/news/credit-trends/124/">Consumer credit delinquencies rise</a></article>'
        items=risk.parse_html(html,self.source('Banking Dive'),sources.make_item)
        self.assertEqual([(x['published_date'],x['categories']) for x in items],[('2026-09-15',['fraud']),('2026-08-20',['credit'])])
    def test_no_shared_listing_date_is_assigned_to_undated_link(self):
        html='<div><article>September 1, 2026<a href="/news/dated/123/">A dated fraud announcement</a></article><a href="/news/unknown/124/">An undated fraud announcement</a><article>October 1, 2026<a href="/news/another/125/">Another fraud announcement</a></article></div>'
        items=risk.parse_html(html,self.source('Banking Dive'),sources.make_item)
        self.assertNotIn('https://www.bankingdive.com/news/unknown/124/',[i['url'] for i in items])
    def test_new_sources_do_not_allow_arbitrary_urls(self):
        for url in ['https://www.ic3.gov.evil.test/PSA/2026/PSA261015','https://www.ic3.gov/PSA/2026/PSA261015?redirect=http://localhost','https://www.bankingdive.com/news/foo/123/#x','http://www.newyorkfed.org/press']:
            with self.assertRaises(svc.SetupError):sources.agency_for_url(url)
    def test_category_changes_generation_prompt_and_cache(self):
        source=self.source('TransUnion')
        item=sources.make_item(source,'Synthetic identity fraud and credit washing','https://newsroom.transunion.com/test-credit-risk/','2026-09-15')
        text='The report describes synthetic identity fraud and credit washing that affect lending decisions and risk assessment.'
        html='<article><p>'+text+'</p></article>'
        response={'status':'supported','summary':'Credit and fraud research','claims':[{'text':'The report discusses lending risks.','evidence':[{'id':'E001'}]}],'checklist':[],'limitations':[],'implications':[]}
        provider={'choices':[{'message':{'content':json.dumps(response)}}],'usage':{}}
        with tempfile.TemporaryDirectory() as folder,patch.object(news,'ROOT',Path(folder)),patch.object(svc,'ROOT',Path(folder)),patch.object(news,'fetch_html',return_value=html),patch.object(svc,'settings',return_value={'NEBIUS_MODEL':'test'}),patch.object(svc,'provider',return_value=provider) as call:
            news.write_json(Path(folder)/'data/news_archive.json',{'items':[item]})
            fraud=news.brief(item['id'],category='fraud');credit=news.brief(item['id'],category='credit');again=news.brief(item['id'],category='credit')
            self.assertEqual(call.call_count,2);self.assertTrue(again['cached'])
            self.assertEqual((fraud['category'],credit['category']),('fraud','credit'))
            self.assertIn('Selected category: Credit',call.call_args.args[1]['messages'][0]['content'])
            with self.assertRaises(svc.SetupError):news.brief(item['id'],category='aml')
    def test_fed_credit_release_uses_main_content_container(self):
        html='<header>Not evidence</header><div id="content"><p>The Federal Reserve reported consumer credit changes, including revolving credit and nonrevolving credit.</p></div><footer>Footer is excluded</footer>'
        text=news.article_text(html,'Fed Consumer Credit')
        self.assertIn('revolving credit',text);self.assertNotIn('Footer',text);self.assertNotIn('Not evidence',text)
    def test_generic_article_excludes_navigation(self):
        html='<header>Header text</header><main><nav>Unrelated links</nav><article><p>A credit report describes lending standards and changes in delinquency rates across consumer loan portfolios.</p></article></main><footer>Footer text</footer>'
        result=news.article_text(html,'New York Fed')
        self.assertIn('delinquency',result);self.assertNotIn('Unrelated',result);self.assertNotIn('Footer',result)

if __name__=='__main__':unittest.main()
