#!/usr/bin/env python3
"""Rootless, synthetic contract tests for review-only IP CONNECT probe."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROBE = Path(__file__).resolve().parents[1] / "extras/mihomo-hot-pool-shadow/awg-mihomo-ip-connect-probe.py"


class IpConnectProbe(unittest.TestCase):
    def invoke(self, *args, dns=None, http="200", exit_code="0", fail_ip=""):
        with tempfile.TemporaryDirectory(prefix="awg-ip-connect-test-") as d:
            root = Path(d)
            resolver = root / "getent"
            resolver.write_text(
                "#!/usr/bin/env python3\n"
                "import os,sys\n"
                "assert sys.argv[1:]==['ahostsv4','api.ipify.org']\n"
                "print(os.environ.get('DNS_TEXT',''))\n"
            )
            resolver.chmod(0o755)
            curl = root / "curl"
            curl.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "with open(os.environ['CURL_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                "if os.environ.get('FAIL_IP') and os.environ['FAIL_IP'] in ' '.join(sys.argv): sys.exit(35)\n"
                "print(os.environ.get('CURL_HTTP','200'))\n"
                "sys.exit(int(os.environ.get('CURL_EXIT','0')))\n"
            )
            curl.chmod(0o755)
            log = root / "args.txt"
            env = dict(os.environ,
                       AWG_IP_CONNECT_GETENT=str(resolver),
                       AWG_IP_CONNECT_CURL=str(curl),
                       CURL_LOG=str(log), CURL_HTTP=http,
                       CURL_EXIT=exit_code, FAIL_IP=fail_ip,
                       DNS_TEXT=dns if dns is not None else
                           "104.26.12.205 STREAM api.ipify.org\n"
                           "104.26.12.205 DGRAM api.ipify.org\n"
                           "104.26.13.205 STREAM api.ipify.org")
            r = subprocess.run([sys.executable, str(PROBE), *args],
                               capture_output=True, text=True, env=env, timeout=6)
            cmds = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return r, cmds

    def test_shadow_two_distinct_public_ips_pass(self):
        r, cmds = self.invoke("--shadow-port", "17891")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("IP_CONNECT_STATE=PASS", r.stdout)
        self.assertIn("IP_CONNECT_CHECKED_IPV4=2", r.stdout)
        self.assertEqual(len(cmds), 2)
        self.assertTrue(all("--connect-to" in c and "http://127.0.0.1:17891" in c for c in cmds))
        self.assertTrue(all("--noproxy" in c and "" in c for c in cmds))
        self.assertTrue(all("https://api.ipify.org/" in c for c in cmds))
        self.assertFalse(any("--interface" in c or "--insecure" in c for c in cmds))

    def test_tun_resolve_and_no_proxy(self):
        r, cmds = self.invoke("--tun-interface", "mihomo0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("IP_CONNECT_SCOPE=PI_BOUND_TUN", r.stdout)
        self.assertEqual(len(cmds), 2)
        for c in cmds:
            self.assertIn("--resolve", c)
            self.assertIn("--interface", c)
            self.assertIn("mihomo0", c)
            self.assertIn("*", c)
            self.assertNotIn("--proxy", c)

    def test_domain_only_falsely_healthy_is_unknown(self):
        r, cmds = self.invoke("--shadow-port", "17891", exit_code="35")
        self.assertEqual(r.returncode, 1)
        self.assertIn("IP_CONNECT_REASON=TLS_FAILED", r.stdout)
        self.assertEqual(len(cmds), 1)

    def test_timeout_unknown(self):
        r, _ = self.invoke("--shadow-port", "17891", exit_code="28")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IP_CONNECT_REASON=TIMEOUT", r.stdout)

    def test_http_non200_unknown(self):
        r, _ = self.invoke("--shadow-port", "17891", http="403")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IP_CONNECT_REASON=HTTP_NOT_200", r.stdout)

    def test_second_ip_failure_never_passes(self):
        r, cmds = self.invoke("--shadow-port", "17891", fail_ip="104.26.13.205")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IP_CONNECT_REASON=TLS_FAILED", r.stdout)
        self.assertEqual(len(cmds), 2)

    def test_no_private_or_reserved_targets(self):
        r, cmds = self.invoke("--shadow-port", "17891",
                              dns="192.168.112.1 STREAM x\n198.18.0.1 STREAM x\n127.0.0.1 STREAM x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("IP_CONNECT_REASON=NO_GLOBAL_IPV4", r.stdout)
        self.assertEqual(cmds, [])

    def test_ignored_private_answer_when_valid_exists(self):
        r, cmds = self.invoke("--shadow-port", "17891",
                              dns="192.168.112.1 STREAM x\n104.26.12.205 STREAM x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(cmds), 1)
        self.assertIn("IP_CONNECT_CHECKED_IPV4=1", r.stdout)

    def test_empty_dns_unknown(self):
        r, cmds = self.invoke("--shadow-port", "17891", dns="")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(cmds, [])

    def test_invalid_interface_and_port_rejected(self):
        for args in (("--tun-interface", "eth0;touch/tmp/foo"),
                     ("--shadow-port", "0"), ("--shadow-port", "65536")):
            r, cmds = self.invoke(*args)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(cmds, [])


if __name__ == "__main__":
    unittest.main()
