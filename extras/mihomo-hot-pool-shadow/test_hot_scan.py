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


class FirstFailDiagnosticTests(unittest.TestCase):
    def test_http403_forces_24frames_but_original_fail_stands(self):
        import copy
        class Video:
            def decode_24_frames(self, port):
                assert port == 18998
                return 'PASS', 'youtube_24_video_frames_decoded'
        class Smart:
            def load_video_decode_code(self):
                return Video()
        gate = {'status': 'FAIL', 'checks': {
            'openai_api': {'state': 'PASS'},
            'youtube_video': {'state': 'FAIL', 'reason': 'youtube_media_http_403'}}}
        before = copy.deepcopy(gate)
        self.assertEqual(scan.diagnose_first_fail(gate, Smart(), 18998),
                         ('PASS', 'youtube_24_video_frames_decoded'))
        self.assertEqual(gate, before)

    def test_unknown_does_not_trigger_extra_decode(self):
        class Smart:
            def load_video_decode_code(self):
                self.fail('Must not launch video')
        gate = {'status': 'UNKNOWN', 'checks': {
            'openai_api': {'state': 'PASS'},
            'youtube_video': {'state': 'UNKNOWN',
                              'reason': 'youtube_sabr_stream_unvalidated'}}}
        self.assertIsNone(scan.diagnose_first_fail(gate, Smart(), 18998))

    def test_openai_not_pass_skips_expensive_diagnostic(self):
        class Smart:
            def load_video_decode_code(self):
                self.fail('Must not launch video')
        gate = {'status': 'FAIL', 'checks': {
            'openai_api': {'state': 'FAIL'},
            'youtube_video': {'state': 'FAIL',
                              'reason': 'youtube_media_http_403'}}}
        self.assertIsNone(scan.diagnose_first_fail(gate, Smart(), 18998))


if __name__ == '__main__':
    unittest.main()