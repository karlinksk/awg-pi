import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

p = Path(__file__).with_name('awg-mihomo-hot-pool.py')
spec = importlib.util.spec_from_file_location('hot_pool', p)
hot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hot)

class HotPoolTests(unittest.TestCase):
    def setUp(self):
        self.now = 200000
        self.nodes = [
            dict(name='hy-a', type='hysteria2', server='194.87.118.184', port=2053, healthy=True, delay_ms=80, index=0),
            dict(name='hy-b', type='hysteria2', server='194.87.118.184', port=2053, healthy=True, delay_ms=90, index=1),
            dict(name='ss-a', type='ss', server='5.6.7.8', port=8388, healthy=True, delay_ms=130, index=2),
            dict(name='vless-a', type='vless', server='1.2.3.4', port=443, healthy=True, delay_ms=150, index=3),
            dict(name='vless-b', type='vless', server='6.7.8.9', port=443, healthy=True, delay_ms=160, index=4),
        ]
        self.state = hot.empty('digest')

    def test_distinct_endpoints(self):
        rows = hot.shortlist(self.nodes, self.state, 'ss-a')
        self.assertEqual([n['name'] for n in rows], ['hy-a', 'vless-a', 'vless-b'])

    def test_two_passes_temporally_separated(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 15))
        hot.record_scan(self.state, n, True, self.now + 180)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 180))
        hot.record_scan(self.state, n, True, self.now + 660)
        self.assertTrue(hot.is_ready(n, self.state, self.now + 660))
        self.assertFalse(hot.is_ready(n, self.state, self.now + 4261))

    def test_failed_probes_reset(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        hot.record_scan(self.state, n, False, self.now + 800)
        hot.record_scan(self.state, n, True, self.now + 1100)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 1100))

    def test_endpoint_quarantine_invalidates_aliases(self):
        n, alias = self.nodes[:2]
        hot.record_scan(self.state, n, True, self.now)
        hot.record_scan(self.state, n, True, self.now + 900)
        hot.record_scan(self.state, alias, True, self.now)
        hot.record_scan(self.state, alias, True, self.now + 900)
        self.assertEqual(hot.failure(self.state, self.nodes, n['name'], self.now + 950, 'activation-failed'), 2)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 950))
        self.assertFalse(hot.is_ready(alias, self.state, self.now + 950))
        self.assertEqual([r['name'] for r in hot.shortlist(self.nodes, self.state, '')], ['ss-a','vless-a','vless-b'])

    def test_provider_change_resets_qualification_but_preserves_quarantine(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'shadow.json'
            hot.record_scan(self.state, self.nodes[0], True, self.now)
            hot.failure(self.state, self.nodes, 'hy-a', self.now, 'activation-failed')
            hot.save_state(path, self.state)
            state = hot.load_state(path, 'new_digest', self.now + 12)
            self.assertEqual(state['checks'], {})
            self.assertEqual(len(state['quarantine']), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_old_first_pass_does_not_make_hot_candidate(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        hot.record_scan(self.state, n, True, self.now + hot.READY_MAX_AGE + 5)
        self.assertFalse(hot.is_ready(n, self.state, self.now + hot.READY_MAX_AGE + 5))

    def test_future_timestamp_rejected(self):
        n = self.nodes[0]
        self.state['checks'][hot.identity(n)] = {
            'last_result': 'PASS', 'last_checked': self.now,
            'passes': [self.now + 800, self.now + 1400]}
        self.assertFalse(hot.is_ready(n, self.state, self.now))

    def test_malformed_state_cannot_authorize_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.json'
            key = hot.identity(self.nodes[0])
            p.write_text(json.dumps({
                'version': 1, 'provider_sha256': 'digest',
                'checks': {key: {'passes': 'malicious', 'last_result': 'PASS',
                                 'last_checked': self.now}},
                'quarantine': {'bad': {'until': True, 'reason': 'activation-failed'}}
            }))
            loaded = hot.load_state(p, 'digest', self.now)
            self.assertFalse(hot.is_ready(self.nodes[0], loaded, self.now))
            self.assertEqual(loaded['quarantine'], {})

    def test_ready_expires_and_cold_start_requires_two_passes(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        hot.record_scan(self.state, n, True, self.now + 600)
        self.assertTrue(hot.is_ready(n, self.state, self.now + 600))
        self.assertFalse(hot.is_ready(n, self.state, self.now + 4000))
        self.assertFalse(hot.is_ready(n, hot.empty('digest'), self.now + 600))

    def test_stale_provider_rejected_and_duplicate_name_removed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / 'sub.yaml').write_text('fixture')
            digest = hashlib.sha256(b'fixture').hexdigest()
            rows = self.nodes + [{**self.nodes[-1], 'index': 6}]
            (path / 'pool.json').write_text(json.dumps({'provider_sha256': digest,
                          'scanned_at': self.now, 'nodes': rows}))
            got_hash, filtered = hot.load_nodes(path / 'pool.json', path / 'sub.yaml', self.now)
            self.assertEqual(got_hash, digest)
            self.assertNotIn('vless-b', [x['name'] for x in filtered])
            with self.assertRaises(ValueError):
                hot.load_nodes(path / 'pool.json', path / 'sub.yaml', self.now + 9000)
            (path / 'sub.yaml').write_text('fixture2')
            with self.assertRaises(ValueError):
                hot.load_nodes(path / 'pool.json', path / 'sub.yaml', self.now)

    def test_diagnostic_pass_sanitizes_output(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_ELIGIBILITY=UNKNOWN\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=PASS\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\n'
               'SECRET=private_data_must_not_leak\n')
        def pretend(argv, **kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv, 1, raw, '')
            if argv[0] == hot.GATE:
                return subprocess.CompletedProcess(argv, 0,
                        'NETWORK_ELIGIBILITY=ELIGIBLE\\nNETWORK_REASON=MEDIUM_NETWORK_CONFIDENCE\\n', '')
            raise AssertionError('Unexpected executable')
        with patch.object(hot.subprocess, 'run', side_effect=pretend):
            allowed, detail = hot.scan_one('vless-a')
        self.assertTrue(allowed)
        self.assertIn('OPENAI=PASS', detail)
        self.assertIn('CHATGPT=UNKNOWN', detail)
        self.assertIn('YOUTUBE24=PASS', detail)
        self.assertNotIn('private_data_must_not_leak', detail)

    def test_diagnostic_empty_failure(self):
        import subprocess
        from unittest.mock import patch
        with patch.object(hot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'sensitive error')):
            allowed, detail = hot.scan_one('vless-a')
        self.assertFalse(allowed)
        self.assertEqual(detail, 'REASON=SCANNER_EMPTY SCAN_RC=1')
        self.assertNotIn('sensitive', detail)

    def test_diagnostic_gate_rejects_missing_video(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_ELIGIBILITY=UNKNOWN\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=UNKNOWN\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\n')
        def pretend(argv, **kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv, 1, raw, '')
            if argv[0] == hot.GATE:
                return subprocess.CompletedProcess(argv, 1,
                        'NETWORK_ELIGIBILITY=UNKNOWN\\nNETWORK_REASON=YOUTUBE_VIDEO_NOT_DECODED\\n', '')
            raise AssertionError('Unexpected executable')
        with patch.object(hot.subprocess, 'run', side_effect=pretend):
            allowed, detail = hot.scan_one('vless-a')
        self.assertFalse(allowed)
        self.assertIn('YOUTUBE24=UNKNOWN', detail)
        self.assertIn('SCAN_RC=1', detail)

if __name__ == '__main__':
    unittest.main()