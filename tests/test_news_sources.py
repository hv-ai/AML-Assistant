from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import news_sources as sources
import news_service as news
import assistant_service as svc

class AgencyNewsTests(unittest.TestCase):
    def agency(self,name):return next(x for x in sources.SOURCES if x['publisher']==name)
    def test_official_agency_article_urls_and_host_spoofs(self):
        self.assertEqual(sources.agency_for_url('https://www.cftc.gov/PressRoom/PressReleases/9000-26')['publisher'],'CFTC')
        for url in ['https://www.cftc.gov.evil.test/PressRoom/PressReleases/9000-26',
                    'https://www.sec.gov@evil.test/newsroom/press-releases/2026-1',
                    'https://ncua.gov/newsroom/press-release/2026/test?url=http://localhost',
                    'https://www.federalreserve.gov/newsevents/pressreleases/%2e%2e/test.htm']:
            with self.assertRaises(svc.SetupError):sources.agency_for_url(url)
    def test_rss_preserves_publisher_date_and_sector(self):
        xml='<rss><channel><item><title>CFTC addresses AML monitoring failures</title><link>https://www.cftc.gov/PressRoom/PressReleases/9000-26</link><pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate><description>Bank Secrecy Act action.</description></item></channel></rss>'
        item=sources.parse_rss(xml,self.agency('CFTC'))[0]
        self.assertEqual(item['publisher'],'CFTC');self.assertEqual(item['published_date'],'2026-10-01')
        self.assertEqual(item['sector'],'Futures / derivatives sector')
    def test_xml_entity_declarations_are_rejected(self):
        with self.assertRaises(svc.SetupError):sources.parse_rss('<!DOCTYPE rss [<!ENTITY x "test">]><rss/>',self.agency('SEC'))
    def test_dated_ncua_index_excludes_navigation(self):
        html='<nav><a href="/newsroom/press-release/2026/nav">AML navigation</a></nav><table><tr><td><a href="/newsroom/press-release/2026/test-aml">Customer Due Diligence update</a></td><td>09/02/2026</td></tr></table>'
        items=sources.parse_index(html,self.agency('NCUA'))
        self.assertEqual(len(items),1);self.assertEqual(items[0]['published_date'],'2026-09-02')
        self.assertIn('Customer Due Diligence',items[0]['title'])
    def test_aml_filter_excludes_generic_monetary_policy(self):
        self.assertIsNone(sources.AML_TERMS.search('Federal Reserve announces interest rate decision'))
        for text in ['suspicious activity reporting','Bank Secrecy Act','beneficial ownership','AML monitoring','illicit finance']:
            self.assertIsNotNone(sources.AML_TERMS.search(text))
    def test_one_agency_failure_does_not_hide_other_news(self):
        xml='<rss><channel><item><title>CFTC AML monitoring action</title><link>https://www.cftc.gov/PressRoom/PressReleases/9000-26</link><pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        def fetch(url):
            if 'sec.gov' in url:raise svc.SetupError('Unavailable')
            return xml
        with tempfile.TemporaryDirectory() as folder,patch.object(sources,'SOURCES',[self.agency('SEC'),self.agency('CFTC')]):
            result=sources.collect_news(Path(folder),fetch,lambda _:[])
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['sources'][0]['state'],'unavailable')
        self.assertEqual(result['sources'][1]['state'],'fresh')
    def test_fed_article_excludes_header_and_footer(self):
        html='<nav>Navigation not evidence</nav><div id="article"><p>The Board announced an action addressing suspicious activity reporting deficiencies and required remediation.</p></div><footer>Footer not evidence</footer>'
        text=news.article_text(html,'Federal Reserve')
        self.assertIn('suspicious activity',text);self.assertNotIn('Navigation',text);self.assertNotIn('Footer',text)
    def test_drupal_agency_body_excludes_generic_header_blocks(self):
        html='<div class="field--name-body">About the agency. This navigation block is not the announcement.</div><article><div class="field--name-body"><p>The agency issued customer identification guidance describing risk-based verification methods and relevant considerations.</p></div></article><footer>Footer content</footer>'
        for publisher in ('FDIC','CFTC','SEC'):
            text=news.article_text(html,publisher)
            self.assertIn('customer identification',text);self.assertNotIn('navigation',text);self.assertNotIn('Footer',text)
    def test_occ_article_selects_release_body(self):
        html='<main><nav>Sidebar not evidence</nav><section class="occgov-issuance-content"><p>The OCC announced a Bank Secrecy Act enforcement action and described deficiencies in monitoring controls.</p></section></main>'
        text=news.article_text(html,'OCC')
        self.assertIn('Bank Secrecy Act',text);self.assertNotIn('Sidebar',text)

if __name__=='__main__':unittest.main()
