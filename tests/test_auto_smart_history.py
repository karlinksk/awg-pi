"""Bounded tmpfs observation and protocol fairness tests (no network or root)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
loader=importlib.machinery.SourceFileLoader('awg_smart_history_test',str(HERE.parent/'src'/'awg-mihomo-smart'))
spec=importlib.util.spec_from_loader(loader.name,loader)
smart=importlib.util.module_from_spec(spec)
loader.exec_module(smart)

def sample(name='HY',download=82.0,*,confirmed=True):
    return {'name':name,'type':'hysteria2','down_mbps':download,
            'up_mbps':20.0,'delay_ms':300,'confirmed':confirmed,
            'sustained_verified':True,'ok':True,'service_ok':True,
            'raw':{'password':'NEVER_PERSIST_THESE_CREDENTIALS'}}

def report(index, source='subscription-hash', name='HY'):
    return {'timestamp':1800000000+index*28800,
            'source_sha256':source,
            'current_at_end':'HY',
            'recommendation':{'name':name,'advice':'CURRENT_BEST'},
            'results':[sample(name,80+index),sample('SS',35,confirmed=False)]}

class ShadowHistoryTests(unittest.TestCase):
    def test_history_is_bounded_and_contains_no_provider_secrets(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch, \
             patch.object(smart,'STATE_DIR',Path(scratch)):
            for i in range(15):
                smart.append_archive(report(i))
            blob=(Path(scratch)/'runs.json').read_text()
            data=json.loads(blob)
            self.assertEqual(len(data['runs']),12)
            self.assertEqual(data['runs'][0]['timestamp'],1800000000+3*28800)
            self.assertNotIn('password',blob)
            self.assertNotIn('NEVER_PERSIST_THESE_CREDENTIALS',blob)
            self.assertEqual((Path(scratch)/'runs.json').stat().st_mode & 0o777,0o600)

    def test_provider_source_change_forgets_old_history(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch, \
             patch.object(smart,'STATE_DIR',Path(scratch)):
            smart.append_archive(report(1,source='provider-before'))
            smart.append_archive(report(2,source='provider-after'))
            data=json.loads((Path(scratch)/'runs.json').read_text())
            self.assertEqual(len(data['runs']),1)
            self.assertEqual(data['source_sha256'],'provider-after')

    def test_history_report_shows_median_without_secrets(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch, \
             patch.object(smart,'STATE_DIR',Path(scratch)):
            smart.append_archive(report(1))
            smart.append_archive(report(2))
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                smart.history_report(types.SimpleNamespace(count=12))
            rendered=output.getvalue()
            self.assertIn('SMART_HISTORY_RUNS=2',rendered)
            self.assertIn('MEDIAN_DOWN_MBPS=81.5',rendered)
            self.assertNotIn('password',rendered)

    def test_rotated_shortlist_preserves_active_and_broadens_protocols(self):
        entries=[
            {'name':'HY','type':'hysteria2','warmup_ok':True,'service_ok':True,'warmup_mbps':8,'delay_ms':90},
            {'name':'SS','type':'ss','warmup_ok':True,'service_ok':True,'warmup_mbps':20,'delay_ms':30},
            {'name':'TR','type':'trojan','warmup_ok':True,'service_ok':True,'warmup_mbps':18,'delay_ms':40},
            {'name':'VL','type':'vless','warmup_ok':True,'service_ok':True,'warmup_mbps':16,'delay_ms':50},
            {'name':'VM','type':'vmess','warmup_ok':True,'service_ok':True,'warmup_mbps':14,'delay_ms':60},
        ]
        results=[smart.calibration_finalists(entries,'HY',3,rotation=i) for i in range(5)]
        self.assertTrue(all(r[0]['name']=='HY' for r in results))
        kinds={row['type'] for r in results for row in r}
        self.assertEqual(kinds,{'ss','trojan','vless','vmess','hysteria2'})
        self.assertTrue(all(len(r)==3 for r in results))

    def test_scoped_smart_report_includes_daypart_summary(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch, \
             patch.object(smart,'STATE_DIR',Path(scratch)):
            doc=report(1)
            smart.append_archive(doc)
            saved={'timestamp':doc['timestamp'], 'current_at_end':'HY',
                   'recommendation':{'name':'HY','advice':'CURRENT_BEST'},
                   'results':[dict(sample('HY'),reliability=1.0,score=60.0)]}
            smart.private_json(Path(scratch)/'last.json',saved)
            buf=io.StringIO()
            with contextlib.redirect_stdout(buf):
                smart.show(types.SimpleNamespace(count=10))
            value=buf.getvalue()
            self.assertIn('SMART_HISTORY_RUNS=1',value)
            self.assertIn('MEDIAN_DOWN_MBPS=81',value)
            self.assertIn('SMART_RECOMMENDATION=HY',value)

    def test_cli_history_command_is_read_only(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as scratch, \
             patch.object(smart,'STATE_DIR',Path(scratch)):
            smart.append_archive(report(1))
            output=io.StringIO()
            with patch.object(smart.sys,'argv',['awg-mihomo-smart','history','--count','1']), \
                 contextlib.redirect_stdout(output):
                smart.main()
            self.assertIn('SMART_HISTORY_RUNS=1',output.getvalue())

if __name__=='__main__':
    unittest.main()
