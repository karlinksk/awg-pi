#!/usr/bin/env python3
"""Quick one-node service-scan safety / bounded failover contract tests."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SMART=ROOT/"src"/"awg-mihomo-smart"
NODE=ROOT/"src"/"awg-mihomo-node-policy"
loader=importlib.machinery.SourceFileLoader("servicequick",str(SMART))
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec)
loader.exec_module(m)

class QuickServiceTests(unittest.TestCase):
    @staticmethod
    def runner(default="default via 192.168.112.1 dev eth0\n",
               route="203.0.113.12 via 192.168.112.1 dev eth0 src 192.168.112.34\n"):
        def fake(cmd,**kw):
            return subprocess.CompletedProcess(cmd,0,default if "show" in cmd else route,"")
        return fake

    def test_direct_candidate_route_verified(self):
        # 203.0.113.12 is documentation address; Python ipaddress declares
        # it non-global, so use a synthetic globally-routable public address.
        route="93.184.216.34 via 192.168.112.1 dev eth0 src 192.168.112.34\n"
        self.assertTrue(m.verify_candidate_direct({"server":"93.184.216.34"},
                                                  self.runner(route=route)))

    def test_rejects_vpn_recursive_route(self):
        route="93.184.216.34 dev mihomo0 src 10.8.1.2\n"
        with self.assertRaises(RuntimeError):
            m.verify_candidate_direct({"server":"93.184.216.34"},self.runner(route=route))

    def test_rejects_different_gateway(self):
        route="93.184.216.34 via 192.168.112.99 dev eth0\n"
        with self.assertRaises(RuntimeError):
            m.verify_candidate_direct({"server":"93.184.216.34"},self.runner(route=route))

    def test_rejects_private_ip(self):
        with self.assertRaises(RuntimeError):
            m.verify_candidate_direct({"server":"192.168.112.55"},self.runner())

    def test_rejects_unresolved_domain(self):
        with self.assertRaises(RuntimeError):
            m.verify_candidate_direct({"server":"node.example"},self.runner())

    def test_cli_service_scan_cannot_run_unprivileged(self):
        import os
        if os.geteuid()==0:
            self.skipTest("requires an unprivileged fixture user")
        res=subprocess.run(["python3","-B",str(SMART),"service-scan","--node","fake-node"],
                           capture_output=True,text=True,timeout=8)
        self.assertEqual(res.returncode,2)
        self.assertIn("requires root",res.stderr)

    def test_stale_cached_node_requires_live_pass(self):
        source=NODE.read_text()
        func="service_candidate_allowed(){"+source.split("service_candidate_allowed(){",1)[1].split("\n}\n",1)[0]+"\n}\n"
        with tempfile.TemporaryDirectory(prefix="awg-one-node-gate-",dir="/tmp") as temp:
            base=Path(temp)
            cache=base/"cache"
            quick=base/"quick"
            cache.write_text("#!/bin/sh\necho SERVICE_ELIGIBILITY=UNKNOWN\nexit 1\n")
            cache.chmod(0o700)
            quick.write_text("#!/bin/sh\necho SERVICE_ELIGIBILITY=PASS\nexit 0\n")
            quick.chmod(0o700)
            command=(func+"MIHOMO_SERVICE_GATE_MODE=require\n"
                     +f"MIHOMO_SERVICE_GATE_BIN={cache}\nMIHOMO_SERVICE_QUICKCHECK_BIN={quick}\n"
                     +"service_candidate_allowed node-good\n")
            result=subprocess.run(["bash","-c",command],capture_output=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)
            quick.write_text("#!/bin/sh\necho SERVICE_ELIGIBILITY=UNKNOWN\nexit 0\n")
            result=subprocess.run(["bash","-c",command],capture_output=True,timeout=8)
            self.assertNotEqual(result.returncode,0)

    def test_try_limit_is_bounded_in_both_policies(self):
        source=NODE.read_text()
        fixed=source.split("failover_fixed(){",1)[1].split("failover_auto(){",1)[0]
        auto=source.split("failover_auto(){",1)[1].split("failover(){",1)[0]
        for section in (fixed,auto):
            self.assertIn("attempts < 3",section)
            self.assertIn("service_candidate_allowed",section)

if __name__=="__main__":
    unittest.main()
