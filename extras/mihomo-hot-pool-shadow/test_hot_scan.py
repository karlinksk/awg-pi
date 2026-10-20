import importlib.util
import pathlib
import socket
import ssl
import unittest
import urllib.error

path = pathlib.Path(__file__).with_name('awg-mihomo-hot-service-scan.py')
spec = importlib.util.spec_from_file_location('hot_scan', path)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class Clock:
    def __init__(self):
        self.elapsed = 0.0
    def now(self):
        return self.elapsed
    def pause(self, amount):
        self.elapsed += amount


class ColdConnectTests(unittest.TestCase):
    def test_first_https_counts_as_transport_ready(self):
        clock = Clock()
        def fetch(port, url, **kwargs):
            self.assertEqual(port, 17999)
            self.assertEqual(url, 'https://api.openai.com/v1/models')
            self.assertLessEqual(kwargs['timeout'], 5)
            self.assertEqual(kwargs['max_bytes'], 8192)
            clock.elapsed += 0.7
            return (401, b'{}', url)
        self.assertEqual(scan.cold_connect(fetch, 17999, clock=clock.now,
                         pause=clock.pause), (True, 700, 1, 'HTTPS_OK'))

    def test_retry_warmup_until_actual_https(self):
        clock = Clock()
        attempts = []
        def fetch(port, url, **kwargs):
            attempts.append((url, kwargs['timeout']))
            clock.elapsed += 3.0
            if len(attempts) < 3:
                raise urllib.error.URLError(socket.timeout())
            return (401, b'', url)
        result = scan.cold_connect(fetch, 17999, clock=clock.now,
                                   pause=clock.pause)
        self.assertEqual(result, (True, 11000, 3, 'HTTPS_OK'))
        self.assertEqual(len(attempts), 3)

    def test_four_timeout_attempts_are_bounded(self):
        clock = Clock()
        def fetch(*args, **kwargs):
            clock.elapsed += kwargs['timeout']
            raise urllib.error.URLError(socket.timeout())
        ok, milliseconds, attempts, family = scan.cold_connect(
            fetch, 17999, clock=clock.now, pause=clock.pause)
        self.assertFalse(ok)
        self.assertLessEqual(milliseconds, scan.CONNECT_BUDGET_SECONDS * 1000)
        self.assertLessEqual(attempts, scan.CONNECT_ATTEMPTS)
        self.assertEqual(family, 'TIMEOUT')

    def test_no_more_than_budget(self):
        clock = Clock()
        def fetch(*args, **kwargs):
            clock.elapsed += kwargs['timeout']
            raise urllib.error.URLError(ConnectionResetError())
        ok, ms, attempts, family = scan.cold_connect(
            fetch, 17999, clock=clock.now, pause=clock.pause, budget=7)
        self.assertFalse(ok)
        self.assertLessEqual(ms, 7000)
        self.assertEqual(family, 'CONNECTION_RESET')
        self.assertLessEqual(attempts, 2)

    def test_failure_families_are_secret_free(self):
        self.assertEqual(scan.error_family(
            urllib.error.URLError(ConnectionRefusedError('private-data'))),
            'CONNECTION_REFUSED')
        self.assertEqual(scan.error_family(
            urllib.error.URLError(ssl.SSLError('secret-url'))), 'TLS')
        self.assertEqual(scan.error_family(
            urllib.error.URLError(socket.gaierror(-3, 'private-endpoint'))),
            'DNS')
        self.assertEqual(scan.error_family(
            urllib.error.URLError(RuntimeError('https://secret'))),
            'CONNECTION_UNKNOWN')

    def test_lock_collision_is_infrastructure_not_tls_failure(self):
        self.assertEqual(scan.error_family(BlockingIOError(11, 'secret lock path')), 'LOCK_BUSY')
        self.assertEqual(scan.error_family(
            urllib.error.URLError(BlockingIOError(11, 'private-data'))), 'LOCK_BUSY')

    def test_http_403_is_only_connectivity_not_service_pass(self):
        clock = Clock()
        def fetch(port, url, **kwargs):
            return 403, b'', url
        self.assertEqual(scan.cold_connect(fetch, 17999, clock=clock.now,
                                           pause=clock.pause),
                         (True, 0, 1, 'HTTPS_OK'))

    def test_valid_cloudflare_trace_is_accepted(self):
        self.assertEqual(scan.safe_egress('139.180.146.200', 'SG'),
                         ('139.180.146.200', 'SG', 'VERIFIED'))
        self.assertEqual(scan.safe_egress('147.45.60.160', 'RU'),
                         ('147.45.60.160', 'RU', 'VERIFIED'))

    def test_invalid_and_private_addresses_do_not_leak(self):
        for ip in ('192.168.112.34', '127.0.0.1', '10.8.1.2',
                   'fe80::1', '2001:db8::1', 'broken-secret', ''):
            self.assertEqual(scan.safe_egress(ip, 'US')[0], 'UNKNOWN')
        self.assertEqual(scan.safe_egress('139.180.146.200', 'bogus')[2],
                         'INVALID_COUNTRY')
        self.assertEqual(scan.safe_egress('139.180.146.200', 'U1')[2],
                         'INVALID_COUNTRY')

    def test_existing_egress_geo_used_and_no_proxy_restored(self):
        import os
        from unittest.mock import patch
        class Helper:
            def egress_geo(self, controller, mixed, item):
                self_args=(controller,mixed,item)
                self_assert=self_args == (29001, 29002, {'probe_name':'test'})
                if not self_assert:
                    raise RuntimeError('wrong controller')
                if 'NO_PROXY' in os.environ or 'no_proxy' in os.environ:
                    raise RuntimeError('bypassed')
                return '139.180.146.200', 'SG', ''
        with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': 'localhost'}):
            answer = scan.isolated_egress(
                Helper(), 29001, 29002, {'probe_name':'test'})
            self.assertEqual(os.environ.get('NO_PROXY'), '*')
            self.assertEqual(os.environ.get('no_proxy'), 'localhost')
        self.assertEqual(answer,
                         ('139.180.146.200', 'SG', 'VERIFIED', 'NONE'))

    def test_failed_geo_does_not_turn_into_service_failure(self):
        class Helper:
            def egress_geo(self, *args):
                return '', '', 'curl-28'
        self.assertEqual(scan.isolated_egress(Helper(), 29001, 29002,
                         {'probe_name':'test'}),
                         ('UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'CURL_ERROR'))

    def test_untrusted_http_code_not_connect_ready(self):
        clock = Clock()
        def fetch(port, url, **kwargs):
            clock.elapsed += 0.1
            return 0, b'', url
        state, _, attempts, family = scan.cold_connect(
            fetch, 17999, clock=clock.now, pause=clock.pause)
        self.assertFalse(state)
        self.assertEqual(attempts, 4)
        self.assertEqual(family, 'HTTP_INVALID')


class TestedServiceChainTests(unittest.TestCase):
    class Verdict:
        def __init__(self, state, reason):
            self.state, self.reason = state, reason

    def test_real_24frames_are_authoritative_without_http_range_gate(self):
        calls = []
        class Gate:
            def fetch(self, port, url, **kw):
                calls.append(('fetch', port))
                return (200, b'fixture', url)
            def openai_probe(self, req):
                calls.append(('api',))
                return TestedServiceChainTests.Verdict('PASS', 'api_verified')
            def chatgpt_web_probe(self, req):
                calls.append(('web',))
                return TestedServiceChainTests.Verdict('PASS', 'web_verified')
            def assess(self, *args):
                raise AssertionError('HTTP range video gate must not execute')
        class Video:
            def decode_24_frames(self, port):
                calls.append(('video', port))
                return 'PASS', 'youtube_24_video_frames_decoded'
        class Smart:
            def load_video_decode_code(self):
                return Video()
        result = scan.assess_hot_pool_24(Gate(), Smart(), 18998)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['checks']['youtube_video']['state'], 'PASS')
        self.assertEqual(calls, [('api',), ('web',), ('video', 18998)])

    def test_openai_unknown_skips_decode(self):
        class Gate:
            def openai_probe(self, request):
                return TestedServiceChainTests.Verdict('UNKNOWN', 'no_api')
            def chatgpt_web_probe(self, request):
                return TestedServiceChainTests.Verdict('PASS', 'web')
        class Smart:
            def load_video_decode_code(self):
                raise AssertionError('video should be skipped')
        result = scan.assess_hot_pool_24(Gate(), Smart(), 18998)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['checks']['youtube_video']['state'], 'UNKNOWN')

    def test_openai_fail_skips_decode_and_fails(self):
        class Gate:
            def openai_probe(self, request):
                return TestedServiceChainTests.Verdict('FAIL', 'api_denied')
            def chatgpt_web_probe(self, request):
                return TestedServiceChainTests.Verdict('PASS', 'web')
        class Smart:
            def load_video_decode_code(self):
                raise AssertionError('video should be skipped')
        result = scan.assess_hot_pool_24(Gate(), Smart(), 18998)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['checks']['youtube_video']['state'], 'UNKNOWN')

    def test_ip_connect_is_not_a_required_service_gate(self):
        import inspect
        source = inspect.getsource(scan.inspect_node)
        self.assertNotIn('ip_connect_shadow_probe', source)
        self.assertNotIn('assess_services_with_stage18', source)
        self.assertIn('assess_hot_pool_24(gate, smart, mixed)', source)


if __name__ == '__main__':
    unittest.main()
