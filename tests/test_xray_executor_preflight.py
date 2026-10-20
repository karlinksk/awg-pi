#!/usr/bin/env python3
"""Guarded, read-only Xray live-transaction preflight safety tests."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"scripts/awg-xray-testpi-executor-preflight.py"
BACKEND=ROOT/"src/awg-xray-live-backend.py"
spec=importlib.util.spec_from_file_location("xray_executor_preflight",TARGET)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class TestExecutorPreflight(unittest.TestCase):
    def test_budget_and_semantics(self):
        self.assertIn('300s',BACKEND.read_text())
        self.assertNotIn('"--on-active=180s"',BACKEND.read_text())
        text=TARGET.read_text()
        self.assertIn('impl.preflight(failed,candidate)',text)
        self.assertIn('"MIHOMO_XRAY_VLESS_BRIDGE"]="1"',text)
        self.assertIn('"MIHOMO_XRAY_SELECTED"]=str(marker)',text)
        self.assertIn('"BRIDGE_CONFIG","MIHOMO_VALID"',text)
        self.assertIn('"REAL_TUN_TEST","NOT_PERFORMED"',text)
        self.assertIn('stdin=subprocess.DEVNULL',text)
        for forbidden in ('"systemctl","restart"','"systemctl","stop"',
                          '"systemctl","start"','"ip","route","replace"',
                          '"systemd-run"','"node","select-auto"'):
            self.assertNotIn(forbidden,text)
        self.assertNotIn('192.168.',text)

    def test_cannot_select_current_or_disappeared_xray(self):
        with tempfile.TemporaryDirectory() as d:
            curr=Path(d)/"current";chain=Path(d)/"fixed"
            curr.write_text("HY2"+chr(10))
            chain.write_text("HY2"+chr(10)+"RESERVE-1"+chr(10)+"RESERVE-2"+chr(10)+"XRAY"+chr(10))
            with mock.patch.object(mod,"CURRENT",curr),mock.patch.object(mod,"FIXED",chain):
                self.assertEqual(mod.read_chain(),("HY2","XRAY"))
                chain.write_text("RESERVE-1"+chr(10)+"RESERVE-2"+chr(10)+"XRAY"+chr(10))
                with self.assertRaisesRegex(RuntimeError,"UNSAFE_FIXED_CHAIN"):
                    mod.read_chain()

    def test_reject_duplicate_policy(self):
        with tempfile.TemporaryDirectory() as d:
            curr=Path(d)/"current";chain=Path(d)/"fixed"
            curr.write_text("HY2")
            chain.write_text("HY2"+chr(10)+"BACKUP"+chr(10)+"BACKUP"+chr(10)+"XRAY")
            with mock.patch.object(mod,"CURRENT",curr),mock.patch.object(mod,"FIXED",chain):
                with self.assertRaisesRegex(RuntimeError,"UNSAFE_FIXED_CHAIN"):
                    mod.read_chain()

    def test_rootless_exits_without_privileged_reads(self):
        import os
        if os.geteuid()==0:self.skipTest("test requires nonroot")
        p=subprocess.run([sys.executable,str(TARGET),"--check"],
                          text=True,capture_output=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("XRAY_EXEC_PREFLIGHT_ERROR=ROOT_TEST_PI_ONLY",p.stdout)

    def test_syntax(self):
        p=subprocess.run([sys.executable,"-m","py_compile",str(TARGET)],
                          text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":
    unittest.main()
