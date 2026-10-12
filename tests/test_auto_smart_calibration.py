import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader('awg_smart_calibrated', str(ROOT.parent/'src'/'awg-mihomo-smart'))
spec = importlib.util.spec_from_loader(loader.name, loader)
smart = importlib.util.module_from_spec(spec)
loader.exec_module(smart)

def row(name, protocol, delay, warmup, *, good=True):
    return dict(name=name, type=protocol, delay_ms=delay, warmup_mbps=warmup,
                warmup_ok=good, service_ok=True, down_mbps=0.0, up_mbps=0.0, score=0.0,
                ok=False, confirmed=False, sustained_verified=False,
                reliability=0)

class DummyPopen:
    def __init__(self, *a, **kw):
        self.stopped = False
    def poll(self):
        return 0 if self.stopped else None
    def terminate(self):
        self.stopped=True
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.stopped=True

class CalibrationTests(unittest.TestCase):
    def test_finalists_keep_active_and_diverse_protocols(self):
        data=[
            row('ss-fast','ss',20,30),
            row('ss-next','ss',22,25),
            row('hy-current','hysteria2',80,8),
            row('trojan','trojan',90,15),
            row('vless','vless',120,10),
            row('vmess','vmess',200,5),
        ]
        chosen=smart.calibration_finalists(data,'hy-current',5)
        names=[r['name'] for r in chosen]
        self.assertEqual(names[0],'hy-current')
        self.assertEqual(len(names),5)
        self.assertEqual(len({r['type'] for r in chosen}),5)
        self.assertNotIn('ss-next',names)

    def test_finalists_ignore_failed_screen(self):
        data=[row('dead','vless',1,100,good=False),
              row('good','ss',20,3)]
        self.assertEqual([r['name'] for r in smart.calibration_finalists(data,'dead',3)],['good'])

    def test_service_rejected_nodes_never_reach_speed_benchmark(self):
        nodes=[row('fast-but-blocked','ss',5,100), row('usable','vless',30,12)]
        nodes[0]['service_ok']=False
        finalists=smart.calibration_finalists(nodes,'',3)
        self.assertEqual([n['name'] for n in finalists],['usable'])
        nodes[0].update(ok=True,confirmed=True,sustained_verified=True,score=100)
        nodes[1].update(ok=True,confirmed=True,sustained_verified=True,score=30)
        self.assertEqual(smart.recommend(nodes,'',{})['name'],'usable')
        self.assertEqual([n['name'] for n in smart.calibration_confirmed(nodes,'',2)], ['usable'])

    def test_confirm_picks_current_and_fastest_competitor(self):
        entries=[row('current','hysteria2',100,3),
                 row('rival','ss',50,8),
                 row('third','trojan',60,5)]
        for r,score in zip(entries,[10,90,80]):
            r['sustained_verified']=True
            r['score']=score
            r['down_mbps']=score
        self.assertEqual([r['name'] for r in smart.calibration_confirmed(entries,'current',2)],
                         ['current','rival'])

    def test_unconfirmed_cannot_be_recommended(self):
        confirmed={'name':'current','ok':True,'score':10,
                   'delay_ms':100,'down_mbps':20,'confirmed':True,'service_ok':True}
        unverified={'name':'competitor','ok':True,'score':95,
                   'delay_ms':10,'down_mbps':150,'confirmed':False,'service_ok':True}
        result=smart.recommend([confirmed,unverified],'current',{})
        self.assertEqual(result['name'],'current')
        self.assertEqual(result['advice'],'CURRENT_BEST')

    def test_prior_confirmation_failure_requires_two_new_successes(self):
        current={'name':'SS','ok':True,'confirmed':True,'service_ok':True,'score':30,
                 'delay_ms':50,'down_mbps':20}
        rival={'name':'HY','ok':True,'confirmed':True,'service_ok':True,'score':90,
               'delay_ms':100,'down_mbps':130}
        a=smart.recommend([current,rival],'SS',{'HY':[0,1]})
        self.assertEqual(a['advice'],'OBSERVE_ONLY_INSUFFICIENT_HISTORY')
        b=smart.recommend([current,rival],'SS',{'HY':[0,1,1]})
        self.assertEqual(b['advice'],'REVIEW_CANDIDATE_MANUALLY')

    def test_cli_defaults_and_bounded_arguments(self):
        call={}
        with patch.object(smart,'shadow_scan',side_effect=lambda a:call.update(vars(a))):
            with patch.object(smart.sys,'argv',['awg-mihomo-smart','scan']):
                smart.main()
        self.assertEqual(call['count'],10)
        self.assertEqual(call['download_bytes'],1500000)
        self.assertEqual(call['sustained_bytes'],8000000)
        self.assertEqual(call['confirm_bytes'],20000000)
        self.assertEqual(call['finalists'],3)
        self.assertEqual(call['sustained_upload_bytes'],2000000)
        self.assertNotIn('fixture',call)

    def test_simulated_end_to_end_requires_two_confirmations(self):
        input_nodes=[
            dict(name='SS', type='ss', server='s1', port=443, delay_ms=20,
                 healthy=True,index=1),
            dict(name='HY', type='hysteria2', server='s2', port=443, delay_ms=150,
                 healthy=True,index=2),
            dict(name='TR', type='trojan', server='s3', port=443, delay_ms=80,
                 healthy=True,index=3),
        ]
        state={'node':None}
        def select(_port,probe_name):
            i=int(probe_name.rsplit('-',1)[-1])
            state['node']=['SS','HY','TR'][i-1]
        def probe(_port,_url,*,nbytes,upload=False,max_seconds=11):
            n=state['node']
            if upload:
                return True,{'SS':15.0,'HY':80.0,'TR':10.0}[n],''
            if nbytes==1500000:
                return True,{'SS':13.0,'HY':7.0,'TR':11.0}[n],''
            if nbytes==8000000:
                return True,{'SS':32.0,'HY':115.0,'TR':22.0}[n],''
            if nbytes==20000000:
                return True,{'SS':30.0,'HY':130.0,'TR':18.0}[n],''
            raise AssertionError('unexpected sample size '+str(nbytes))
        helper=types.SimpleNamespace(
            read_provider=lambda path:[{'name':n['name'],'type':n['type'],
                                        'server':n['server'],'port':443}
                                       for n in input_nodes],
            choose_free_port=iter([10001,10002]*3).__next__,
            make_probe_config=lambda raw,mixed,ctl:(
                 {'mixed-port':mixed,'external-controller':'127.0.0.1:'+str(ctl),
                  'proxies':[],'proxy-groups':[],'rules':[]},
                 [{'probe_name':f'AWG-PROBE-{i:06d}'} for i in range(1,len(raw)+1)]),
            controller_request=lambda port,path,timeout=None:{
                'proxies':{f'AWG-PROBE-{i:06d}':{}
                           for i in range(1,4)}},
            select_probe=select,
        )
        args=argparse.Namespace(count=3,download_bytes=1500000,
              upload_bytes=300000,per_request_timeout=11,
              sustained_bytes=8000000,confirm_bytes=20000000,
              sustained_upload_bytes=2000000,
              sustained_timeout=20,confirm_timeout=20)
        pool={'provider_sha256':'subscription-test-hash'}
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch:
            d=Path(scratch)
            with patch.object(smart,'STATE_DIR',d), \
                 patch.object(smart.os,'geteuid',return_value=0), \
                 patch.object(smart,'plan',return_value=(pool,'SS',input_nodes)), \
                 patch.object(smart,'load_pool_code',return_value=helper), \
                 patch.object(smart,'load_service_code',return_value=types.SimpleNamespace(
                     assess=lambda request:{'status':'PASS','checks':{}},
                     fetch=lambda *a,**kw:None)), \
                 patch.object(smart,'current_name',return_value='SS'), \
                 patch.object(smart,'probe_http',side_effect=probe), \
                 patch.object(smart.subprocess,'Popen',DummyPopen):
                smart.shadow_scan(args)
                a=json.loads((d/'last.json').read_text())
                self.assertEqual(a['recommendation']['advice'],
                                 'OBSERVE_ONLY_INSUFFICIENT_HISTORY')
                self.assertEqual(a['switches_made'],0)
                self.assertEqual(a['confirmed_count'],2)
                self.assertEqual(a['nominal_byte_cap'],74500000)
                hy=next(x for x in a['results'] if x['name']=='HY')
                self.assertGreater(hy['down_mbps'],120)
                self.assertTrue(hy['confirmed'])
                self.assertEqual(hy['warmup_mbps'],7.0)
                self.assertEqual(hy['type'],'hysteria2')
                self.assertFalse(next(x for x in a['results'] if x['name']=='TR')['confirmed'])
                smart.shadow_scan(args)
                b=json.loads((d/'last.json').read_text())
                self.assertEqual(b['recommendation']['name'],'HY')
                self.assertEqual(b['recommendation']['advice'],'REVIEW_CANDIDATE_MANUALLY')
                h=json.loads((d/'history.json').read_text())
                self.assertEqual(h['version'],3)
                self.assertEqual(h['nodes']['HY'],[1,1])
                self.assertEqual(h['nodes']['SS'],[1,1])
                self.assertNotIn('TR',h['nodes'])

if __name__=='__main__':
    unittest.main()
