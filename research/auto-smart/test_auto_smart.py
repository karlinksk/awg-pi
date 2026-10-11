import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader('awg_mihomo_smart_test', str(ROOT / 'awg-mihomo-smart'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def node(name, kind, ms, server, *, ok=True, europe=False, index=1):
    return {'name':name,'type':kind,'delay_ms':ms,'server':server,'port':443,
            'healthy':ok,'europe':europe,'index':index}


class AutoSmartUnit(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            node('ss-low-lat','ss',19,'a',index=1),
            node('ss-second','ss',21,'b',index=2),
            node('ss-third','ss',25,'c',index=3),
            node('vless-low','vless',37,'d',index=4),
            node('hy2','hysteria2',66,'e',index=5),
            node('hy2-copy','hysteria2',69,'e',index=6),
            node('slow-current','trojan',450,'f',index=7),
            node('dead-fast','ss',1,'g',ok=False,index=8),
        ]

    def test_diverse_protocols_and_current_stickiness(self):
        selection=mod.diverse_shortlist(mod.eligible({'nodes':self.nodes}),5,'slow-current')
        names=[x['name'] for x in selection]
        self.assertEqual(names[0],'slow-current')
        self.assertIn('hy2', names)
        self.assertIn('vless-low',names)
        self.assertIn('ss-low-lat', names)
        self.assertNotIn('hy2-copy',names)
        self.assertNotIn('dead-fast',names)
        self.assertEqual(len(names),len(set(names)))

    def test_region_filter_is_fail_closed(self):
        a=mod.eligible({'nodes':self.nodes},region='europe')
        self.assertEqual(a,[])
        self.nodes[-2]['europe']=True
        self.assertEqual([n['name'] for n in mod.eligible({'nodes':self.nodes},region='europe')], ['slow-current'])

    def test_protocol_filter_and_cooldown(self):
        a=mod.eligible({'nodes':self.nodes},protocol='hysteria2',cooldown={'hy2':1})
        self.assertEqual([n['name'] for n in a],['hy2-copy'])

    def test_duplicate_names_ignored(self):
        ns=self.nodes + [node('hy2','vmess',4,'foo',index=20)]
        selected=mod.diverse_shortlist(mod.eligible({'nodes':ns}),12)
        self.assertNotIn('hy2',[n['name'] for n in selected])

    def test_speed_dominates_latency_without_making_slow_links_best(self):
        slow={'name':'low','delay_ms':15,'down_mbps':1.5,'up_mbps':10,'reliability':1.0}
        fast={'name':'fast','delay_ms':100,'down_mbps':130,'up_mbps':75,'reliability':1.0}
        self.assertGreater(mod.score(fast),mod.score(slow))
        self.assertEqual(mod.score({'delay_ms':5,'down_mbps':400,'up_mbps':99,'reliability':0}),0)

    def test_report_does_not_recommend_switch_on_one_measurement(self):
        entries=[{'name':'current','delay_ms':15,'down_mbps':12,'up_mbps':10,'ok':True,
                  'score':40},
                 {'name':'candidate','delay_ms':100,'down_mbps':120,'up_mbps':50,'ok':True,
                  'score':92}]
        self.assertEqual(mod.recommend(entries,'current',{'candidate':[1]})['advice'],
                         'OBSERVE_ONLY_INSUFFICIENT_HISTORY')
        self.assertEqual(mod.recommend(entries,'current',{'candidate':[1,1]})['advice'],
                         'REVIEW_CANDIDATE_MANUALLY')
        self.assertEqual(mod.recommend(entries,'current',{'candidate':[1,1]})['name'],'candidate')

    def test_unavailable_candidates_never_recommended(self):
        a=[{'name':'n','ok':False,'score':0,'delay_ms':15}]
        self.assertEqual(mod.recommend(a,'old',{})['advice'],'NO_HEALTHY_CANDIDATE')

    def test_history_bounded_and_failure_degrades_reliability(self):
        hist={}
        for b in [True,True,True,True,True,False]: mod.bounded_history(hist,'n',b)
        self.assertEqual(hist['n'],[1,1,1,1,0])
        self.assertEqual(round(sum(hist['n'])/len(hist['n']),2),0.8)

    def test_fixture_mode_is_pure(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=pathlib.Path(temp)/'pool.json'
            fixture.write_text(json.dumps({'nodes':self.nodes}))
            args=type('Args',(),{'fixture':str(fixture),'region':'all','protocol':'all','current':'hy2','count':4})()
            pool,current,selected=mod.plan(args)
            self.assertEqual(current,'hy2')
            self.assertEqual(selected[0]['name'],'hy2')
            self.assertEqual(len(selected),4)


    def test_shadow_scan_namespace_does_not_require_fixture_attribute(self):
        # Unit-level guard: the real scan CLI does not define --fixture.
        # Fail before any network launch, and assert the scan reaches plan().
        import argparse
        from unittest.mock import patch
        args = argparse.Namespace(count=1, download_bytes=100000,
                                  upload_bytes=0, per_request_timeout=5)
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch:
            with patch.object(mod.os, 'geteuid', return_value=0), \
                 patch.object(mod, 'STATE_DIR', pathlib.Path(scratch)), \
                 patch.object(mod, 'plan', side_effect=RuntimeError('plan_called')):
                with self.assertRaisesRegex(RuntimeError, 'plan_called'):
                    mod.shadow_scan(args)


    def test_scan_plan_namespace_without_fixture_uses_runtime_pool(self):
        import argparse
        import types
        from unittest.mock import patch
        args = argparse.Namespace(count=3, download_bytes=100000,
                                  upload_bytes=0, per_request_timeout=5)
        pool = {'nodes': self.nodes, 'provider_sha256': 'fixture'}
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch:
            pool_file=pathlib.Path(scratch)/'pool.json'
            pool_file.write_text(json.dumps(pool))
            pool_helper=types.SimpleNamespace(
                read_policy_values=lambda: ('all','all'),
                load_cooldown=lambda: {})
            with patch.object(mod,'POOL_JSON',pool_file), \
                 patch.object(mod,'load_pool_code',return_value=pool_helper), \
                 patch.object(mod,'fresh_pool',return_value=True), \
                 patch.object(mod,'current_name',return_value='hy2'):
                data,current,nodes=mod.plan(args)
            self.assertEqual(data['provider_sha256'],'fixture')
            self.assertEqual(current,'hy2')
            self.assertEqual(nodes[0]['name'],'hy2')


if __name__=='__main__':unittest.main()
