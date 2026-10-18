import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aml_research import ROOT,load_index
import hybrid_retrieval as hybrid
import assistant_service as svc

class CurrentSourceTests(unittest.TestCase):
    def test_current_cdd_faq_original_is_verifiable_and_not_regulation(self):
        source=json.loads((ROOT/'config/customer_control_sources.json').read_text())[0]
        self.assertEqual(hashlib.sha256((ROOT/source['original_path']).read_bytes()).hexdigest(),source['original_sha256'])
        self.assertEqual(source['published_date'],'2026-05-06')
        self.assertEqual(source['authority_type'],'regulatory_guidance')
    def test_ordinary_controls_prioritize_updated_faq_not_historical_testimony(self):
        rows=load_index().search('What must a bank CDD program include?',8)
        self.assertEqual(rows[0]['source_id'],'S24')
        self.assertNotIn('S13',{r['source_id'] for r in rows})
        self.assertTrue(any('Exceptive' in r['text'] for r in rows if r['source_id']=='S24'))
    def test_prepared_answer_cites_faq_and_guidance_without_claiming_binding_rule(self):
        answer=svc.ask('What must a bank CDD program include?',retrieval_method='bm25')
        ids={r['id'].split(':')[0] for c in answer['claims'] for r in c['evidence']}
        self.assertTrue({'S12','S24'}<=ids)
        self.assertIn('Binding rule text',answer['authority_notice'])
    def test_new_deployment_pointer_overrides_stale_runtime_namespace(self):
        current=hybrid.corpus_hash(load_index().chunks)
        with tempfile.TemporaryDirectory() as folder,patch.object(hybrid,'ROOT',Path(folder)):
            for name,state in [('.runtime/hybrid_state.json',{'corpus_hash':'old','namespace':'old'}),('config/deployment_retrieval.json',{'corpus_hash':current,'namespace':'new'})]:
                p=Path(folder)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(state))
            self.assertEqual(hybrid.index_state()['namespace'],'new')

if __name__=='__main__':unittest.main()
