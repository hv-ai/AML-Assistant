import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import hybrid_retrieval as hybrid
import assistant_service as svc
from evaluate_hybrid import score

class HybridTests(unittest.TestCase):
    def test_fusion_rewards_cross_channel_support_and_deduplicates(self):
        a={'chunk_id':'A'};b={'chunk_id':'B'};c={'chunk_id':'C'}
        result=hybrid.fuse([a,b,b],[c,b],3)
        self.assertEqual(result[0]['chunk_id'],'B')
        self.assertEqual(set(result[0]['retrieval_channels']),{'keyword','semantic'})
        self.assertEqual(len({r['chunk_id'] for r in result}),len(result))
    def test_embedding_windows_keep_parent_identity_and_overlap(self):
        chunk={'chunk_id':'S01:L1','source_id':'S01','title':'Title','heading':'Heading','text':' '.join(str(i) for i in range(12))}
        rows=hybrid.windows([chunk],size=8,overlap=2)
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['parent_id'],'S01:L1')
        self.assertIn('6 7',rows[0]['text']);self.assertIn('6 7',rows[1]['text'])
        self.assertEqual(rows,hybrid.windows([chunk],size=8,overlap=2))
    def test_embedding_cache_preserves_order_without_rebilling(self):
        response={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}],'usage':{'prompt_tokens':4}}
        with tempfile.TemporaryDirectory() as d,patch.object(hybrid,'ROOT',Path(d)),patch.object(hybrid,'DIMENSION',2),patch.object(hybrid,'config',return_value={'embedding_model':'test'}),patch.object(svc,'provider',return_value=response) as provider:
            first=hybrid.embed(['a','b']);second=hybrid.embed(['b','a'])
            self.assertEqual(first,[[1,0],[0,1]]);self.assertEqual(second,[[0,1],[1,0]])
            self.assertEqual(provider.call_count,1)
    def test_bad_embedding_dimension_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch.object(hybrid,'ROOT',Path(d)),patch.object(hybrid,'config',return_value={'embedding_model':'test'}),patch.object(svc,'provider',return_value={'data':[{'index':0,'embedding':[1,0]}]}):
            with self.assertRaises(svc.SetupError):hybrid.embed(['a'])
    def test_untrusted_pinecone_host_cannot_receive_key(self):
        with patch.object(hybrid,'config',return_value={'PINECONE_API_KEY':'test'}):
            for host in ['evil.test','x.pinecone.io.evil.test','api.pinecone.io@evil.test','localhost']:
                with self.assertRaises(svc.SetupError):hybrid.pinecone('/query',{},host)
    def test_failure_returns_explicit_degraded_keyword_path(self):
        class Index:
            def search(self,*args):return [{'chunk_id':'A'}]
        with patch.object(hybrid,'status',return_value={'ready':True}),patch.object(hybrid,'dense_search',side_effect=svc.SetupError('Offline')):
            rows,info=hybrid.retrieve('customer',index=Index())
            self.assertEqual(rows[0]['chunk_id'],'A');self.assertTrue(info['degraded']);self.assertIn('Offline',info['notice'])
            with self.assertRaises(svc.SetupError):hybrid.retrieve('customer',index=Index(),method='hybrid')
    def test_dense_results_only_resolve_current_local_passages(self):
        class Index:chunks=[{'chunk_id':'A','text':'Original stored text'}]
        with tempfile.TemporaryDirectory() as d,patch.object(hybrid,'ROOT',Path(d)),patch.object(hybrid,'status',return_value={'ready':True}),patch.object(hybrid,'load_index',return_value=Index()),patch.object(hybrid,'embed',return_value=[[1,0]]),patch.object(hybrid,'eligible_sources',return_value=None),patch.object(hybrid,'pinecone',return_value={'matches':[{'metadata':{'parent_id':'UNKNOWN'},'score':1},{'metadata':{'parent_id':'A'},'score':.9},{'metadata':{'parent_id':'A'},'score':.8}]}):
            folder=Path(d)/'.runtime';folder.mkdir();(folder/'hybrid_state.json').write_text(json.dumps({'namespace':'test','host':'host'}))
            rows=hybrid.dense_search('question');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['text'],'Original stored text')
    def test_evaluation_penalizes_late_hits_and_missing_labels(self):
        result=score([{'chunk_id':'X'},{'chunk_id':'A'}],['A','B'])
        self.assertEqual(result['hit_at_5'],1);self.assertEqual(result['mrr_at_5'],.5)
        self.assertEqual(result['known_passage_recall_at_5'],.5);self.assertLess(result['ndcg_at_5'],1)
    def test_control_scope_prevents_incidental_kyc_threat_mentions(self):
        self.assertEqual(set(hybrid.eligible_sources('How do KYC CDD and EDD connect?')),{'S06','S10','S12','S24'})

if __name__=='__main__':unittest.main()
