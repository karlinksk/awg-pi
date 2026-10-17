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
# The test must exercise the repository gate, not a helper that happens to
# be installed on a developer's Pi. Production default stays unchanged.
hot.GATE = str(Path(__file__).resolve().parents[2] / 'src' / 'awg-mihomo-network-eligibility.py')

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

    def test_live_alias_different_port_not_in_reserve(self):
        alias = dict(self.nodes[3], name='active-alias', port=8443)
        nodes = self.nodes + [alias]
        shortlist = hot.shortlist(nodes, self.state, 'vless-a')
        self.assertNotIn('active-alias', [n['name'] for n in shortlist])
        self.assertIn('vless-b', [n['name'] for n in shortlist])

    def test_live_endpoint_excluded_even_if_active_absent_from_pool(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            transport, endpoint = Path(d) / 'transport', Path(d) / 'endpoint'
            transport.write_text('mihomo\\n')
            endpoint.write_text('1.2.3.4\\n')
            with patch.object(hot, 'LIVE_TRANSPORT', transport), patch.object(
                    hot, 'LIVE_ENDPOINT', endpoint):
                shortlist = hot.shortlist(self.nodes, self.state, 'removed-live-name')
        self.assertNotIn('vless-a', [n['name'] for n in shortlist])
        self.assertIn('vless-b', [n['name'] for n in shortlist])

    def test_two_passes_temporally_separated(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 15))
        hot.record_scan(self.state, n, True, self.now + 180)
        self.assertFalse(hot.is_ready(n, self.state, self.now + 180))
        hot.record_scan(self.state, n, True, self.now + 660)
        self.assertTrue(hot.is_ready(n, self.state, self.now + 660))
        self.assertFalse(hot.is_ready(n, self.state, self.now + 4261))

    def test_single_unknown_keeps_proof_but_never_selects_suspect(self):
        n = self.nodes[0]
        hot.record_scan(self.state, n, True, self.now)
        hot.record_scan(self.state, n, True, self.now + 800)
        self.assertTrue(hot.is_ready(n, self.state, self.now + 800))
        hot.record_scan(self.state, n, False, self.now + 950)
        record = self.state['checks'][hot.identity(n)]
        self.assertEqual(record['last_result'], 'SUSPECT')
        self.assertEqual(record['passes'], [self.now, self.now + 800])
        self.assertFalse(hot.is_ready(n, self.state, self.now + 950))
        self.assertIn('HOT_POOL_SUSPECT=1',hot.report([n],self.state,self.now+950,''))
        self.assertFalse(hot.eligible_for_probe(n,self.state,self.now+950))
        self.assertTrue(hot.eligible_for_probe(n,self.state,self.now+1550))
        hot.record_scan(self.state, n, True, self.now + 1600)
        self.assertTrue(hot.is_ready(n, self.state, self.now + 1600))

    def test_two_consecutive_unknowns_clear_proofs(self):
        n=self.nodes[0]
        hot.record_scan(self.state,n,True,self.now)
        hot.record_scan(self.state,n,True,self.now+800)
        hot.record_scan(self.state,n,False,self.now+1000)
        hot.record_scan(self.state,n,False,self.now+1700)
        record=self.state['checks'][hot.identity(n)]
        self.assertEqual(record['last_result'],'FAIL')
        self.assertEqual(record['passes'],[])
        self.assertFalse(hot.eligible_for_probe(n,self.state,self.now+1700))
        self.assertTrue(hot.eligible_for_probe(n,self.state,self.now+2900))

    def test_one_pass_unknown_keeps_history_but_no_ready(self):
        n=self.nodes[0]
        hot.record_scan(self.state,n,True,self.now)
        hot.record_scan(self.state,n,False,self.now+800)
        self.assertEqual(self.state['checks'][hot.identity(n)]['last_result'],'SUSPECT')
        self.assertFalse(hot.is_ready(n,self.state,self.now+800))
        hot.record_scan(self.state,n,True,self.now+1400)
        self.assertTrue(hot.is_ready(n,self.state,self.now+1400))

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

    def test_suspect_state_persists_without_becoming_ready(self):
        n=self.nodes[3]
        hot.record_scan(self.state,n,True,self.now-1400)
        hot.record_scan(self.state,n,True,self.now-600)
        hot.record_scan(self.state,n,False,self.now)
        with tempfile.TemporaryDirectory() as tmp:
            state_path=Path(tmp)/'shadow.json'
            hot.save_state(state_path,self.state)
            loaded=hot.load_state(state_path,'digest',self.now+1)
            self.assertEqual(loaded['checks'][hot.identity(n)]['last_result'],'SUSPECT')
            self.assertFalse(hot.is_ready(n,loaded,self.now+1))
            self.assertEqual(hot.proof_rank(n,loaded,self.now+1),1)
            self.assertNotIn(n['name'], [x['name'] for x in hot.shortlist([n],loaded,'',now=self.now+1) if hot.is_ready(x,loaded,self.now+1)])

    def test_suspect_expiration_cannot_resurrect_old_proofs(self):
        n=self.nodes[0]
        hot.record_scan(self.state,n,True,self.now-2000)
        hot.record_scan(self.state,n,True,self.now-1000)
        hot.record_scan(self.state,n,False,self.now)
        hot.record_scan(self.state,n,True,self.now+5000)
        self.assertFalse(hot.is_ready(n,self.state,self.now+5000))

    def test_suspect_prioritized_for_recovery_not_selection(self):
        ready=self.nodes[3]
        suspect=self.nodes[4]
        for n in (ready,suspect):
            hot.record_scan(self.state,n,True,self.now-2200)
            hot.record_scan(self.state,n,True,self.now-900)
        hot.record_scan(self.state,suspect,False,self.now-650)
        plan=hot.select_probes(hot.shortlist(self.nodes,self.state,'',now=self.now),
                               self.state,self.now)
        self.assertIn(('RECOVER',suspect),plan)
        self.assertNotIn(suspect['name'],[n['name'] for n in self.nodes if hot.is_ready(n,self.state,self.now)])
        self.assertLessEqual(len(plan),2)

    def test_suspect_does_not_steal_emergency_ready_deadline(self):
        a,b=self.nodes[3:5]
        for n in (a,b):
            hot.record_scan(self.state,n,True,self.now-2600)
            hot.record_scan(self.state,n,True,self.now-1400)
        hot.record_scan(self.state,self.nodes[0],True,self.now-2000)
        hot.record_scan(self.state,self.nodes[0],False,self.now-800)
        plan=hot.select_probes(hot.shortlist(self.nodes,self.state,'',now=self.now),
                               self.state,self.now)
        self.assertEqual([mode for mode,_ in plan],['RENEW','RENEW'])

    def test_connect_timings_bounded_history(self):
        n=self.nodes[0]
        for j in range(20):
            hot.record_scan(self.state,n,True,self.now+j*700,connect_ms=j*30)
        self.assertEqual(len(self.state['checks'][hot.identity(n)]['connect_samples_ms']),12)
        self.assertEqual(self.state['checks'][hot.identity(n)]['connect_samples_ms'][-1],570)
        hot.record_scan(self.state,n,False,self.now+20000,connect_ms=120001)
        self.assertEqual(len(self.state['checks'][hot.identity(n)]['connect_samples_ms']),12)

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
        raw = ('SERVICE_IP_CONNECT_STATE=PASS\n'
               'SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n'
               'SERVICE_ELIGIBILITY=UNKNOWN\n'
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

    def test_legacy_scanner_without_ip_proof_never_ready(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_ELIGIBILITY=UNKNOWN\\n'
               'SERVICE_CHECK_OPENAI_API=PASS\\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=PASS\\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\\n')
        def fake(argv, **kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv, 1, raw, '')
            if argv[0] == hot.GATE:
                return subprocess.CompletedProcess(argv, 0, 'NETWORK_ELIGIBILITY=ELIGIBLE\\n', '')
            raise AssertionError('Unexpected executable')
        with patch.object(hot.subprocess, 'run', side_effect=fake):
            allowed, detail = hot.scan_one('vless-a')
        self.assertFalse(allowed)
        self.assertIn('IP_GATE=UNVERIFIED', detail)

    def test_cold_metadata_is_not_forwarded_to_strict_gate(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_DIAG_MODE=ISOLATED_SHADOW_ONLY\n'
               'SERVICE_CONNECT_STATE=PASS\n'
               'SERVICE_COLD_READY_MS=1542\n'
               'SERVICE_CONNECT_ATTEMPTS=2\n'
               'SERVICE_CONNECT_FAMILY=HTTPS_OK\n'
               'SERVICE_REASON_YOUTUBE_VIDEO=youtube_24_video_frames_decoded\n'
               'SERVICE_IP_CONNECT_STATE=PASS\n'
               'SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n'
               'SERVICE_ELIGIBILITY=UNKNOWN\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=PASS\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\n')
        seen = {}
        real_run = subprocess.run
        def tested(argv, **kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv, 1, raw, '')
            if argv[0] == hot.GATE:
                seen['gate_input'] = kwargs['input']
                return real_run(['/usr/bin/python3','-B',hot.GATE],
                    input=kwargs['input'],text=True,capture_output=True,timeout=5)
            raise AssertionError('Unexpected command')
        with patch.object(hot.subprocess, 'run', side_effect=tested):
            ok,details=hot.scan_one('vless-a')
        self.assertTrue(ok)
        self.assertIn('CONNECT_FAMILY=HTTPS_OK',details)
        self.assertIn('COLD_MS=1542',details)
        self.assertNotIn('SERVICE_CONNECT_STATE=', seen['gate_input'])
        self.assertNotIn('SERVICE_REASON_YOUTUBE_VIDEO=', seen['gate_input'])
        self.assertEqual(len(seen['gate_input'].splitlines()),5)
        self.assertIn('GATE_REASON=MEDIUM_NETWORK_CONFIDENCE',details)

    def test_geo_fields_are_collected_but_not_passed_to_balanced_gate(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_IP_CONNECT_STATE=PASS\n'
               'SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n'
               'SERVICE_ELIGIBILITY=UNKNOWN\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=PASS\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\n'
               'SERVICE_GEO_EGRESS_IPV4=139.180.146.200\n'
               'SERVICE_GEO_COUNTRY=SG\n'
               'SERVICE_GEO_STATE=VERIFIED\n'
               'SERVICE_GEO_REASON=NONE\n')
        real_run = subprocess.run
        seen={}
        def fake(argv,**kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv,1,raw,'')
            if argv[0] == hot.GATE:
                seen['gate'] = kwargs['input']
                return real_run(['/usr/bin/python3','-B',hot.GATE],
                                input=kwargs['input'],text=True,capture_output=True,timeout=5)
            raise AssertionError('Unexpected command')
        with patch.object(hot.subprocess,'run',side_effect=fake):
            ok,detail=hot.scan_one('test')
        self.assertTrue(ok)
        self.assertIn('EGRESS_IP=139.180.146.200',detail)
        self.assertIn('COUNTRY=SG',detail)
        self.assertIn('GEO=VERIFIED',detail)
        self.assertEqual(len(seen['gate'].splitlines()),5)
        self.assertNotIn('SERVICE_GEO_',seen['gate'])

    def test_geo_observations_are_ram_bounded_ttl_and_invalid_filtered(self):
        node=self.nodes[0]
        for i in range(300):
            now=self.now + i*270
            details=('SCAN_RC=1 OPENAI=PASS CHATGPT=UNKNOWN YOUTUBE24=PASS '
                     'EGRESS_IP=139.180.146.200 COUNTRY=SG GEO=VERIFIED')
            hot.append_geo_observation(self.state,node,True,details,now)
        rows=self.state['geo_history']
        self.assertEqual(len(rows),hot.GEO_HISTORY_LIMIT)
        self.assertEqual(rows[-1]['country'],'SG')
        self.assertEqual(rows[-1]['youtube'],'PASS')
        with tempfile.TemporaryDirectory() as tmp:
            state_file=Path(tmp)/'shadow.json'
            hot.save_state(state_file,self.state)
            restored=hot.load_state(state_file,'digest',self.now+300*270)
        self.assertTrue(restored['geo_history'])
        self.assertLessEqual(len(restored['geo_history']),hot.GEO_HISTORY_LIMIT)
        self.assertTrue(all(r['country']=='SG' for r in restored['geo_history']))
        self.assertTrue(all(hot.valid_geo_observation(r,self.now+300*270)
                            for r in restored['geo_history']))

    def test_geo_report_groups_youtube_by_actual_exit_country(self):
        node1,node2=self.nodes[0],self.nodes[3]
        hot.append_geo_observation(self.state,node1,False,
            'YOUTUBE24=UNKNOWN VIDEO_REASON=stage18_ytdlp_extract_or_download_failed '
            'EGRESS_IP=139.180.146.200 COUNTRY=SG GEO=VERIFIED', self.now)
        hot.append_geo_observation(self.state,node1,True,
            'YOUTUBE24=PASS VIDEO_REASON=youtube_24_video_frames_decoded '
            'EGRESS_IP=139.180.146.200 COUNTRY=SG GEO=VERIFIED',self.now+1)
        hot.append_geo_observation(self.state,node2,True,
            'YOUTUBE24=PASS EGRESS_IP=193.233.202.250 COUNTRY=RU GEO=VERIFIED',self.now+2)
        report=hot.geo_report(self.state,self.now+3)
        self.assertIn('HOT_POOL_GEO_WINDOW_HOURS=24',report)
        self.assertIn('HOT_POOL_GEO_VERIFIED=3',report)
        self.assertIn('HOT_POOL_GEO_COUNTRY=SG SAMPLES=2 YOUTUBE_PASS=1 '
                      'YOUTUBE_FAIL=0 YOUTUBE_UNKNOWN=1 ELIGIBLE=1 DISTINCT_EGRESS=1', report)
        self.assertIn('HOT_POOL_GEO_IP=193.233.202.250 COUNTRY=RU SAMPLES=1', report)

    def test_geo_history_survives_provider_hash_change_without_ready_proof(self):
        n=self.nodes[0]
        hot.record_scan(self.state,n,True,self.now-800)
        hot.record_scan(self.state,n,True,self.now)
        hot.append_geo_observation(self.state,n,True,
               'YOUTUBE24=PASS EGRESS_IP=139.180.146.200 COUNTRY=SG GEO=VERIFIED',self.now)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            hot.save_state(path,self.state)
            changed=hot.load_state(path,'different-provider-hash',self.now+1)
        self.assertEqual(changed['checks'],{})
        self.assertEqual(len(changed['geo_history']),1)
        self.assertFalse(hot.is_ready(n,changed,self.now+1))

    def test_geo_history_expiration(self):
        n=self.nodes[0]
        hot.append_geo_observation(self.state,n,True,
            'YOUTUBE24=PASS EGRESS_IP=139.180.146.200 COUNTRY=SG GEO=VERIFIED',self.now)
        self.assertIn('HOT_POOL_GEO_SAMPLES=1',hot.geo_report(self.state,self.now))
        self.assertIn('HOT_POOL_GEO_SAMPLES=0',
                      hot.geo_report(self.state,self.now+hot.GEO_HISTORY_TTL+1))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            hot.save_state(path,self.state)
            loaded=hot.load_state(path,'digest',self.now+hot.GEO_HISTORY_TTL+1)
        self.assertEqual(loaded['geo_history'],[])

    def test_geo_unknown_is_recorded_without_changing_ready(self):
        node=self.nodes[3]
        hot.record_scan(self.state,node,True,self.now)
        hot.record_scan(self.state,node,True,self.now+800)
        self.assertTrue(hot.is_ready(node,self.state,self.now+800))
        hot.append_geo_observation(
            self.state,node,True,
            'OPENAI=PASS YOUTUBE24=PASS GEO=UNKNOWN COUNTRY=UNKNOWN EGRESS_IP=UNKNOWN',
            self.now+800)
        self.assertTrue(hot.is_ready(node,self.state,self.now+800))
        self.assertEqual(self.state['geo_history'][-1]['geo_state'],'UNKNOWN')

    def test_geo_sanitizes_private_ips_bad_codes_and_payload(self):
        n=self.nodes[0]
        detail=('YOUTUBE24=FAIL EGRESS_IP=192.168.112.34 '
                'COUNTRY=US GEO=VERIFIED EXTRA=secret-token')
        hot.append_geo_observation(self.state,n,False,detail,self.now)
        row=self.state['geo_history'][-1]
        self.assertEqual(row['geo_state'],'UNKNOWN')
        self.assertEqual(row['egress_ip'],'UNKNOWN')
        self.assertNotIn('EXTRA',str(row))
        self.assertEqual(row['youtube'],'FAIL')
        self.assertFalse(row['eligible'])

    def test_strict_gate_still_rejects_missing_or_duplicate_checks(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_IP_CONNECT_STATE=PASS\n'
               'SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n'
               'SERVICE_ELIGIBILITY=UNKNOWN\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_OPENAI_API=PASS\n'
               'SERVICE_CHECK_CHATGPT_WEB=UNKNOWN\n'
               'SERVICE_CHECK_YOUTUBE_VIDEO=PASS\n'
               'SERVICE_REASON_CHATGPT_WEB=chatgpt_web_http_403\n')
        real_run=subprocess.run
        def fake(argv, **kwargs):
            if argv[0] == hot.SCAN:
                return subprocess.CompletedProcess(argv,1,raw,'')
            if argv[0] == hot.GATE:
                return real_run(['/usr/bin/python3','-B',hot.GATE],
                    input=kwargs['input'],text=True,capture_output=True,timeout=5)
            raise AssertionError('Unexpected executable')
        with patch.object(hot.subprocess,'run',side_effect=fake):
            ok, details=hot.scan_one('vless-a')
        self.assertFalse(ok)
        self.assertIn('GATE_REASON=BAD_OR_DUPLICATE_CHECK_FIELD',details)

    def test_diagnostic_empty_failure(self):
        import subprocess
        from unittest.mock import patch
        with patch.object(hot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'sensitive error')):
            allowed, detail = hot.scan_one('vless-a')
        self.assertFalse(allowed)
        self.assertIn('REASON=SCANNER_EMPTY SCAN_RC=1 SCAN_FAMILY=SCANNER_EXCEPTION', detail)
        self.assertNotIn('sensitive', detail)

    def test_diagnostic_gate_rejects_missing_video(self):
        import subprocess
        from unittest.mock import patch
        raw = ('SERVICE_IP_CONNECT_STATE=PASS\n'
               'SERVICE_IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n'
               'SERVICE_ELIGIBILITY=UNKNOWN\n'
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

    def test_probe_order_prefers_one_pass_then_untried_then_failed(self):
        h, ss, v = self.nodes[0], self.nodes[2], self.nodes[3]
        hot.record_scan(self.state, h, False, self.now - 1500)
        hot.record_scan(self.state, v, True, self.now - 700)
        order = hot.probe_order([h, ss, v], self.state, self.now)
        self.assertEqual([n['name'] for n in order], ['vless-a', 'ss-a', 'hy-a'])

    def test_probe_order_never_repeats_failed_low_latency_before_fresh(self):
        h, ss, v = self.nodes[0], self.nodes[2], self.nodes[3]
        hot.record_scan(self.state, h, False, self.now - 3600)
        got = hot.probe_order([h, ss, v], self.state, self.now)
        self.assertEqual([n['name'] for n in got], ['ss-a', 'vless-a', 'hy-a'])

    def test_failed_retry_keeps_existing_cooldown(self):
        h = self.nodes[0]
        hot.record_scan(self.state, h, False, self.now - 30)
        self.assertFalse(hot.eligible_for_probe(h, self.state, self.now))
        self.assertTrue(hot.eligible_for_probe(h, self.state, self.now + hot.RETRY_FAILED))

    def test_error_family_sanitizes_secret_and_permission(self):
        raw = ('Traceback: Permission denied for token=VERY_SECRET ' +
               'https://example.com/myprivate?auth=VERY_SECRET')
        self.assertEqual(hot.scanner_error_family(raw), 'SANDBOX_PERMISSION_DENIED')
        self.assertNotIn('VERY_SECRET', hot.scanner_error_family(raw))
        self.assertEqual(hot.scanner_error_family('Read-only file system'), 'SANDBOX_READ_ONLY')

    def test_scanner_empty_reports_sandbox_family_without_traceback(self):
        import subprocess
        from unittest.mock import patch
        raw = 'Permission denied token=SENSITIVE_VALUE'
        with patch.object(hot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', raw)):
            allowed, detail = hot.scan_one('vless-a')
        self.assertFalse(allowed)
        self.assertIn('SCAN_FAMILY=SANDBOX_PERMISSION_DENIED', detail)
        self.assertNotIn('SENSITIVE_VALUE', detail)

    def test_literal_ipv4_preflight_rejects_unverifiable_addresses(self):
        self.assertTrue(hot.literal_public_ipv4('194.87.118.184'))
        self.assertFalse(hot.literal_public_ipv4('ragnarok-vpn.ru'))
        self.assertFalse(hot.literal_public_ipv4('10.1.2.3'))
        self.assertFalse(hot.literal_public_ipv4('2001:4860:4860::8888'))

    def test_pool_rejects_hostname_before_eligibility_scan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            provider=p/'provider.yaml'
            provider.write_text('synthetic-no-secrets')
            digest=hashlib.sha256(provider.read_bytes()).hexdigest()
            rows=[dict(self.nodes[0]),
                  {**self.nodes[2], 'name':'dns-only',
                   'server':'unresolvable.example.test'}]
            (p/'pool.json').write_text(json.dumps({
                'provider_sha256':digest, 'scanned_at':self.now,'nodes':rows}))
            got,filtered=hot.load_nodes(p/'pool.json',provider,self.now)
            self.assertEqual(got,digest)
            self.assertEqual([n['name'] for n in filtered],['hy-a'])

    def test_sanitized_trace_point_does_not_emit_sensitive_exception(self):
        raw = ('Traceback (most recent call last):\\n'
               '  File "/usr/local/sbin/awg-mihomo-smart", line 411, in service_scan\\n'
               'RuntimeError: forbidden?key=SECRET_VALUE')
        metadata = hot.sanitized_trace_point(raw.replace('\\n', chr(10)))
        self.assertEqual(metadata, 'ERROR_CLASS=RuntimeError STACK=awg-mihomo-smart:411:service_scan')
        self.assertNotIn('SECRET_VALUE', metadata)

    def test_high_latency_ready_is_retained_beyond_twelve_slot_limit(self):
        cheap = [dict(name='new-' + str(i), type='vless', server='77.16.2.' + str(i+1),
                      port=10000+i, healthy=True, delay_ms=30+i, index=i)
                 for i in range(16)]
        # 4-per-protocol cap plus 12 total: pin a high-latency ready node.
        ready = dict(name='slow-ready', type='vless', server='62.60.233.157',
                     port=8444, healthy=True, delay_ms=3320, index=99)
        hot.record_scan(self.state, ready, True, self.now-2400)
        hot.record_scan(self.state, ready, True, self.now-1200)
        chosen = hot.shortlist(cheap + self.nodes[::2] + [ready],
                               self.state, '', now=self.now)
        self.assertEqual(chosen[0]['name'], 'slow-ready')
        self.assertIn('slow-ready', [n['name'] for n in chosen])
        self.assertLessEqual(len(chosen), 12)
        self.assertLessEqual(sum(n['type']=='vless' for n in chosen), 4)
        self.assertIn('HOT_POOL_READY=1', hot.report(cheap + [ready], self.state, self.now, ''))

    def test_untried_candidates_displace_previously_failed_fast_endpoints(self):
        failed = [dict(name=f'bad-{i}', type='vless',
                       server=f'91.123.20.{i+1}', port=443,
                       healthy=True, delay_ms=10+i, index=i)
                  for i in range(4)]
        fresh = [dict(name=f'new-{i}', type='vless',
                      server=f'91.123.30.{i+1}', port=443,
                      healthy=True, delay_ms=110+i, index=20+i)
                 for i in range(4)]
        for n in failed:
            hot.record_scan(self.state, n, False, self.now-200)
        selected = hot.shortlist(failed+fresh, self.state, '', now=self.now)
        self.assertEqual({n['name'] for n in selected},
                         {n['name'] for n in fresh})
        self.assertTrue(all(hot.proof_rank(n,self.state,self.now)==3
                            for n in failed))
        self.assertTrue(all(hot.proof_rank(n,self.state,self.now)==2
                            for n in fresh))

    def test_second_qualification_precedes_protocol_diversification(self):
        ready = [dict(name=f'ready-{i}', type='vless',
                      server=f'8.88.99.{i+1}', port=443, delay_ms=100+i,
                      index=i, healthy=True) for i in range(2)]
        pending = dict(name='one-pass', type='vless',
                       server='8.88.99.10', port=443, delay_ms=300,
                       index=10, healthy=True)
        alternate = dict(name='ss-unknown', type='ss',
                         server='8.88.99.20', port=8388, delay_ms=80,
                         index=11, healthy=True)
        for n in ready:
            hot.record_scan(self.state, n, True, self.now-1450)
            hot.record_scan(self.state, n, True, self.now-550)
        hot.record_scan(self.state, pending, True, self.now-650)
        shortlisted = hot.shortlist(ready+[pending,alternate],
                                    self.state,'',now=self.now)
        plan = hot.select_probes(shortlisted,self.state,self.now)
        self.assertLessEqual(len(plan),hot.MAX_PROBES)
        self.assertEqual(plan[0][1]['name'],'one-pass')

    def test_ready_proactive_refresh_preserves_two_fresh_passes(self):
        n = self.nodes[3]
        hot.record_scan(self.state, n, True, self.now-2600)
        hot.record_scan(self.state, n, True, self.now-1300)
        self.assertTrue(hot.is_ready(n, self.state, self.now))
        self.assertTrue(hot.needs_ready_refresh(n, self.state, self.now))
        self.assertTrue(hot.eligible_for_probe(n, self.state, self.now))
        self.assertEqual(hot.probe_order([self.nodes[0], n], self.state, self.now)[0]['name'],
                         'vless-a')
        hot.record_scan(self.state, n, True, self.now)
        self.assertTrue(hot.is_ready(n, self.state, self.now+1300))
        self.assertEqual(self.state['checks'][hot.identity(n)]['passes'],
                         [self.now-1300, self.now])

    def test_ready_not_refreshed_too_early(self):
        n = self.nodes[3]
        hot.record_scan(self.state, n, True, self.now-900)
        hot.record_scan(self.state, n, True, self.now-100)
        self.assertTrue(hot.is_ready(n, self.state, self.now))
        self.assertFalse(hot.eligible_for_probe(n, self.state, self.now))

    def test_expired_or_failed_ready_is_not_retained_as_ready(self):
        n = dict(self.nodes[3], delay_ms=3500)
        hot.record_scan(self.state, n, True, self.now-4600)
        hot.record_scan(self.state, n, True, self.now-3900)
        self.assertFalse(hot.is_ready(n, self.state, self.now))
        self.assertNotEqual(hot.proof_rank(n, self.state, self.now), 0)
        self.assertIn('HOT_POOL_READY=0', hot.report([n], self.state, self.now, ''))
        hot.record_scan(self.state, n, False, self.now)
        self.assertFalse(hot.is_ready(n, self.state, self.now))

    def test_alias_of_active_endpoint_cannot_be_reserved(self):
        primary, alias = self.nodes[:2]
        hot.record_scan(self.state, alias, True, self.now-1000)
        hot.record_scan(self.state, alias, True, self.now-200)
        rows = hot.shortlist(self.nodes, self.state, primary['name'], now=self.now)
        self.assertNotIn(primary['name'], [n['name'] for n in rows])
        self.assertNotIn(alias['name'], [n['name'] for n in rows])

    def test_two_ready_aliases_share_single_endpoint_slot(self):
        a, b = self.nodes[:2]
        for n in (a,b):
            hot.record_scan(self.state, n, True, self.now-1300)
            hot.record_scan(self.state, n, True, self.now-600)
        rows = hot.shortlist(self.nodes, self.state, '', now=self.now)
        self.assertEqual(sum(hot.endpoint(n)==hot.endpoint(a) for n in rows), 1)
        self.assertIn('HOT_POOL_READY=1', hot.report(self.nodes, self.state, self.now, ''))

    def test_ready_alias_beats_unverified_faster_alias(self):
        a, b = self.nodes[:2]
        hot.record_scan(self.state, b, True, self.now-1300)
        hot.record_scan(self.state, b, True, self.now-600)
        selected=hot.shortlist(self.nodes, self.state, '', now=self.now)
        self.assertEqual(selected[0]['name'], 'hy-b')

    def test_unhealthy_or_quarantined_ready_dropped(self):
        n = self.nodes[3]
        hot.record_scan(self.state, n, True, self.now-1300)
        hot.record_scan(self.state, n, True, self.now-600)
        healthy=[x for x in self.nodes if x['name']!=n['name']]
        self.assertNotIn(n, hot.shortlist(healthy,self.state,'',now=self.now))
        hot.failure(self.state,self.nodes,n['name'],self.now,'active-health-failed')
        self.assertFalse(hot.is_ready(n, self.state, self.now))
        self.assertNotIn(n, hot.shortlist(self.nodes,self.state,'',now=self.now))

    def test_nonurgent_maintenance_leaves_two_discovery_slots(self):
        ready = self.nodes[3]
        hot.record_scan(self.state, ready, True, self.now-2200)
        hot.record_scan(self.state, ready, True, self.now-900)
        candidates = hot.shortlist(self.nodes, self.state, '', now=self.now)
        plan = hot.select_probes(candidates, self.state, self.now)
        self.assertEqual(len(plan), 2)
        self.assertEqual([x[0] for x in plan], ['DISCOVER', 'DISCOVER'])

    def test_urgent_renewal_both_slots_protects_deadlines(self):
        a, b = self.nodes[3:5]
        for n in (a, b):
            hot.record_scan(self.state, n, True, self.now-2550)
            hot.record_scan(self.state, n, True, self.now-1200)
        selected = hot.shortlist(self.nodes, self.state, '', now=self.now)
        plan = hot.select_probes(selected, self.state, self.now)
        self.assertEqual([mode for mode, _ in plan], ['RENEW','RENEW'])
        self.assertEqual({n['name'] for _,n in plan},{'vless-a','vless-b'})

    def test_empty_reserve_explores_two_distinct_endpoints(self):
        plan = hot.select_probes(
            hot.shortlist(self.nodes,self.state,'',now=self.now),
            self.state, self.now)
        self.assertEqual([mode for mode,_ in plan], ['DISCOVER','DISCOVER'])
        self.assertEqual(len({hot.endpoint(n) for _, n in plan}), 2)

    def test_four_ready_target_suppresses_extra_scanning(self):
        for n in (self.nodes[0],self.nodes[2],self.nodes[3],self.nodes[4]):
            hot.record_scan(self.state, n, True, self.now-1000)
            hot.record_scan(self.state, n, True, self.now-200)
        rows = hot.shortlist(self.nodes,self.state,'',now=self.now)
        self.assertEqual(hot.select_probes(rows,self.state,self.now),[])
        self.assertIn('HOT_POOL_TARGET_READY=4',
                      hot.report(self.nodes,self.state,self.now,''))

    def test_diversity_prefers_missing_protocols_with_2_vless_ready(self):
        a,b=self.nodes[3:5]
        for n in (a,b):
            hot.record_scan(self.state,n,True,self.now-1400)
            hot.record_scan(self.state,n,True,self.now-500)
        rows=hot.shortlist(self.nodes,self.state,'',now=self.now)
        plan=hot.select_probes(rows,self.state,self.now)
        self.assertEqual(len(plan),2)
        self.assertTrue(all(mode=='DISCOVER' for mode,_ in plan))
        self.assertEqual({n['type'] for _,n in plan},{'hysteria2','ss'})

    def test_defers_nonurgent_renewal_for_discovery(self):
        a,b=self.nodes[3:5]
        hot.record_scan(self.state,a,True,self.now-2550)
        hot.record_scan(self.state,a,True,self.now-1100)
        hot.record_scan(self.state,b,True,self.now-2200)
        hot.record_scan(self.state,b,True,self.now-900)
        plan=hot.select_probes(hot.shortlist(self.nodes,self.state,'',now=self.now),
                               self.state,self.now)
        self.assertEqual([mode for mode,n in plan],['RENEW','DISCOVER'])
        self.assertEqual(plan[0][1]['name'],'vless-a')

    def test_scheduler_respects_two_checks_across_many_cycles(self):
        # Two synchronized READY nodes must not permanently starve discovery.
        a,b=self.nodes[3:5]
        for n in (a,b):
            hot.record_scan(self.state,n,True,self.now-2400)
            hot.record_scan(self.state,n,True,self.now-1200)
        test_nodes=[self.nodes[0],self.nodes[2],a,b]
        discovery_count=0
        peak_ready=0
        for cycle in range(10):
            now=self.now+cycle*840  # 12min timer plus typical jitter/scan budget
            selected=hot.shortlist(test_nodes,self.state,'',now=now)
            peak_ready=max(peak_ready,sum(hot.is_ready(n,self.state,now)
                                          for n in selected))
            plan=hot.select_probes(selected,self.state,now)
            self.assertLessEqual(len(plan),hot.MAX_PROBES)
            self.assertEqual(len({hot.endpoint(n) for _,n in plan}),len(plan))
            discovery_count+=sum(mode=='DISCOVER' for mode,n in plan)
            for _,n in plan:
                hot.record_scan(self.state,n,True,now)
        self.assertGreaterEqual(discovery_count,2)
        self.assertGreaterEqual(peak_ready,4)

if __name__ == '__main__':
    unittest.main()
