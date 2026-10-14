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


if __name__ == '__main__':
    unittest.main()