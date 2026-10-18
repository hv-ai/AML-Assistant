import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aml_research import ROOT,load_index,tokens
from evaluate_typologies import normalize

class TypologyLibraryTests(unittest.TestCase):
    def test_all_requested_typologies_have_dedicated_sources(self):
        topics=json.loads((ROOT/'config/typology_topics.json').read_text())
        expected={'structuring','money_mules','trade_based','shell_companies','digital_assets','corruption','human_trafficking'}
        self.assertEqual({t['id'] for t in topics},expected)
        index=load_index();available={c['source_id'] for c in index.chunks}
        for t in topics:
            self.assertTrue(set(t['source_ids'])<=available,t['id'])
            self.assertTrue(set(t['source_ids'])-{'S14'},'Broad assessment alone is insufficient: '+t['id'])
    def test_saved_originals_match_recorded_checksums(self):
        for source in json.loads((ROOT/'config/typology_sources.json').read_text()):
            data=(ROOT/source['original_path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),source['original_sha256'],source['source_id'])
    def test_pdf_citations_point_to_actual_extracted_pages(self):
        for c in load_index().chunks:
            if not c.get('pdf_page'):continue
            self.assertIn('PDF page '+str(c['pdf_page']),c['locator'])
            raw=json.loads((ROOT/'data/raw'/f'{c["source_id"]}.json').read_text())
            self.assertTrue(any(l.get('page')==c['pdf_page'] and l['text'].strip()==c['text'] for l in raw['lines']))
    def test_all_development_questions_retrieve_concept_evidence(self):
        index=load_index()
        for case in json.loads((ROOT/'evaluation/typology_cases.json').read_text()):
            with self.subTest(case=case['id']):
                matches=[c for c in index.search(case['question'],5) if c['source_id'] in case['source_ids'] and any(normalize(p) in normalize(c['text']) for p in case['key_phrases'])]
                self.assertTrue(matches)
    def test_singular_plural_and_topic_scope_do_not_lose_mule_evidence(self):
        for q in ['money mule account indicators','money mules account indicators']:
            hits=load_index().search(q)
            self.assertIn('S16',{c['source_id'] for c in hits})
            self.assertTrue(all(c['source_id'] in ('S14','S16') for c in hits))
        self.assertEqual(tokens('analysis status mule mules companies'),['analysis','status','mule','mule','company'])

if __name__=='__main__':unittest.main()
