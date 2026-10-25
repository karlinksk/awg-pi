#!/usr/bin/env python3
"""Offline read-only IP-CONNECT preflight gate; no network or root required."""
import importlib.machinery
import importlib.util
import inspect
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/awg-mihomo-smart"
loader = importlib.machinery.SourceFileLoader("ip_connect_review_smart", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
smart = importlib.util.module_from_spec(spec)
loader.exec_module(smart)


class IpConnectCandidateGateTests(unittest.TestCase):
    def run_gate(self, *, exitcode=0, stdout=None):
        if stdout is None:
            stdout = (
                "IP_CONNECT_MODE=PROXY\n"
                "IP_CONNECT_STATE=PASS\n"
                "IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n"
                "IP_CONNECT_CHECKED_IPV4=2\n"
                "IP_CONNECT_SCOPE=LOOPBACK_PROXY\n"
            )
        with tempfile.TemporaryDirectory(prefix="ip-connect-gate-") as d:
            helper = Path(d) / "probe.py"
            helper.write_text("# test fixture\n")
            seen = []
            def runner(args, **kw):
                seen.append((args, kw))
                return subprocess.CompletedProcess(args, exitcode, stdout, "")
            result = smart.ip_connect_shadow_probe(17891, probe=helper, runner=runner)
            return result, seen

    def test_good_vless_could_pass(self):
        res, calls = self.run_gate()
        self.assertEqual(res, ('PASS', 'ALL_CHECKED_IPV4_HTTPS_OK'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][-2:], ['--proxy-port', '17891'])
        self.assertLessEqual(calls[0][1]['timeout'], 21)

    def test_tls_eof_is_not_pass(self):
        output = ("IP_CONNECT_MODE=PROXY\nIP_CONNECT_STATE=UNKNOWN\n"
                  "IP_CONNECT_REASON=TLS_FAILED\nIP_CONNECT_CHECKED_IPV4=1\n"
                  "IP_CONNECT_SCOPE=LOOPBACK_PROXY\n")
        result, _ = self.run_gate(exitcode=1, stdout=output)
        self.assertEqual(result, ('UNKNOWN', 'TLS_FAILED'))

    def test_scan_reports_validated_ip_connect_reason(self):
        # The scan must surface the structured verifier result, not stderr
        # or a provider URL, before returning UNKNOWN.
        output = ("IP_CONNECT_MODE=PROXY\nIP_CONNECT_STATE=UNKNOWN\n"
                  "IP_CONNECT_REASON=TLS_FAILED\nIP_CONNECT_CHECKED_IPV4=1\n"
                  "IP_CONNECT_SCOPE=LOOPBACK_PROXY\n")
        result, _ = self.run_gate(exitcode=1, stdout=output)
        self.assertEqual(result, ('UNKNOWN', 'TLS_FAILED'))
        source = inspect.getsource(smart.service_scan)
        self.assertIn("print('SERVICE_IP_CONNECT_STATE=' + ip_state)", source)
        self.assertIn("print('SERVICE_IP_CONNECT_REASON=' + ip_reason", source)
        self.assertLess(
            source.index("print('SERVICE_IP_CONNECT_REASON=' + ip_reason"),
            source.index("if ip_state != 'PASS' and strict_ip:")
        )

    def test_selective_rejects_unverified_numeric_ip_and_transit_records_it(self):
        with tempfile.TemporaryDirectory(prefix="gateway-mode-test-") as td:
            mode = Path(td) / 'mode'
            for value, strict in (('selective', True), ('transit', False),
                                  ('unknown', True), ('', True)):
                mode.write_text(value)
                self.assertEqual(smart.strict_ip_connect_required(mode), strict)
            mode.unlink()
            self.assertTrue(smart.strict_ip_connect_required(mode))
        source = inspect.getsource(smart.service_scan)
        self.assertIn("if ip_state != 'PASS' and strict_ip:", source)
        self.assertIn("'TRANSIT_TELEMETRY'", source)
        self.assertIn("'STRICT_GATE'", source)
        self.assertLess(source.index("if ip_state != 'PASS' and strict_ip:"),
                        source.index('result = assess_services_with_stage18('))
        self.assertIn('force_media=True', source)

    def test_shadow_warmup_recovers_from_cold_connection_before_ip_gate(self):
        outcomes = [RuntimeError("cold"), RuntimeError("cold"), (401, {}, b"")]
        calls = []
        def fetch(port, url, **kw):
            calls.append((port, url, kw))
            entry = outcomes.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return entry
        clock_ticks = iter([0.0, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07])
        clock = lambda: next(clock_ticks)
        ok, attempts, ms = smart.isolated_shadow_ready(
            fetch, 17891, clock=clock, pause=lambda sec: None)
        self.assertTrue(ok)
        self.assertEqual(attempts, 3)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c[1] == 'https://api.openai.com/v1/models' for c in calls))
        self.assertTrue(all(c[2]['timeout'] <= 6 for c in calls))

    def test_warmup_never_converts_failures_or_403_into_service_pass(self):
        clock = lambda: 0.0
        fail = lambda *a, **kw: (_ for _ in ()).throw(TimeoutError())
        ok, count, _ = smart.isolated_shadow_ready(fail, 7890, clock=clock,
                                                  pause=lambda sec: None)
        self.assertFalse(ok)
        self.assertEqual(count, 4)
        # HTTP 403 is transport-level HTTPS reachability, never logged-in chat.
        ok, count, _ = smart.isolated_shadow_ready(
            lambda *a, **kw: (403, {}, b""), 7890, clock=clock,
            pause=lambda sec: None)
        self.assertTrue(ok)
        self.assertEqual(count, 1)
        src = inspect.getsource(smart.service_scan)
        self.assertIn('SERVICE_CONNECT_STATE=', src)
        self.assertIn('SERVICE_CHECK_YOUTUBE_VIDEO=UNKNOWN', src)
        self.assertIn('not_run_connect', src)

    def test_domain_only_pass_with_missing_ip_verifier_is_rejected(self):
        result = smart.ip_connect_shadow_probe(17891, probe=Path('/no/such/program'))
        self.assertEqual(result, ('UNKNOWN', 'HELPER_MISSING'))

    def test_invalid_stdout_not_pass(self):
        good = ("IP_CONNECT_MODE=PROXY\nIP_CONNECT_STATE=PASS\n"
                "IP_CONNECT_REASON=ALL_CHECKED_IPV4_HTTPS_OK\n"
                "IP_CONNECT_CHECKED_IPV4=2\nIP_CONNECT_SCOPE=LOOPBACK_PROXY\n")
        for txt in (good.replace("PROXY", "TUN"),
                    good.replace("2\n", "0\n"),
                    good+"IP_CONNECT_STATE=PASS\n",
                    good.replace("ALL_CHECKED_IPV4_HTTPS_OK", "FAKE_REASON"),
                    good.replace("LOOPBACK_PROXY", "PI_BOUND_TUN")):
            result, _ = self.run_gate(stdout=txt)
            self.assertNotEqual(result[0], 'PASS', txt)

    def test_nonzero_exit_even_with_fake_pass(self):
        result, _ = self.run_gate(exitcode=1)
        self.assertNotEqual(result[0], 'PASS')

    def test_invalid_port(self):
        self.assertEqual(smart.ip_connect_shadow_probe(0)[0], 'UNKNOWN')

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            helper = Path(d) / "probe.py"
            helper.touch()
            def runner(*args, **kwargs):
                raise subprocess.TimeoutExpired('probe', 20)
            self.assertEqual(smart.ip_connect_shadow_probe(1234, probe=helper, runner=runner),
                             ('UNKNOWN', 'PROBE_UNAVAILABLE'))


if __name__ == '__main__':
    unittest.main()
