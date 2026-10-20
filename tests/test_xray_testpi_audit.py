#!/usr/bin/env python3
"""Read-only audit guard and deterministic FIXED order unit tests."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/awg-xray-testpi-audit.py"
spec=importlib.util.spec_from_file_location("xray_testpi_audit",SCRIPT)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class PreflightAuditTests(unittest.TestCase):
    def test_exact_one_way_fixed_chain(self):
        self.assertEqual(mod.later_nodes("HY2",["HY2","XHTTP","GRPC"]),["XHTTP","GRPC"])
        self.assertEqual(mod.later_nodes("XHTTP",["HY2","XHTTP","GRPC"]),["GRPC"])
        self.assertEqual(mod.later_nodes("GRPC",["HY2","XHTTP","GRPC"]),[])
    def test_broken_fixed_chains_have_no_candidates(self):
        self.assertEqual(mod.later_nodes("OLD",["HY2","XHTTP"]),[])
        self.assertEqual(mod.later_nodes("HY2",["HY2","XHTTP","HY2"]),[])
    def test_no_network_change_commands_in_readonly_auditor(self):
        source=SCRIPT.read_text()
        for forbidden in ('systemctl","restart','systemctl","start','systemctl","enable',
                          'systemctl","stop','"ip","route","replace','"ip","rule","add',
                          "node select-auto",'"awg-transit-routing","disable"'):
            self.assertNotIn(forbidden,source)
        self.assertIn('XRAY_AUDIT_',source)
        self.assertIn('"ROOT_TEST_PI_REQUIRED"',source)
        self.assertNotIn('192.168.',source)
        self.assertNotIn('Provider URL:',source)
    def test_passive_installer_contains_no_private_lan_address(self):
        source=(ROOT/"scripts/awg-xray-passive-stage-testpi.sh").read_text()
        self.assertNotIn("192.168.",source)
        self.assertNotIn("hostname -I",source)
    def test_rootless_audit_refuses(self):
        import os
        if os.geteuid()==0:self.skipTest("privilege-negative test requires normal user")
        p=subprocess.run([sys.executable,str(SCRIPT),"--check"],text=True,
                         capture_output=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("XRAY_AUDIT_ERROR=ROOT_TEST_PI_REQUIRED",p.stdout)

if __name__=="__main__":unittest.main()
