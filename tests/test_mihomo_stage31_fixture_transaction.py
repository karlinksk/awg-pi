#!/usr/bin/env python3
"""Unprivileged Stage31 fixture-only transaction and independent recovery tests."""
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

SCRIPT=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage31-fixture-transaction.py"
sp=importlib.util.spec_from_file_location("stage31fixture",SCRIPT)
m=importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="stage31-tests-",dir="/tmp")
        self.root=Path(self.tmp.name)
        (self.root/"live").mkdir(mode=0o700)
        self.initial={}
        for name,value in {
            "config.yaml":"mode: old\n",
            "mode":"legacy\n",
            "service-state":"active\n",
            "route-state":"transit-safe\n",
            "transport":"mihomo\n",
            "direct-state":"verified\n",
        }.items():
            target=self.root/"live"/name
            target.write_text(value)
            target.chmod(0o600)
            self.initial[name]=target.read_bytes()
        conf={
            "tun":{"enable":True,"auto-route":False},
            "proxy-groups":[{"name":"AWG-MIHOMO","type":"fallback","proxies":["primary","backup"]}],
            "proxies":[{"name":"primary","type":"ss","server":"192.0.2.10","port":8080,"password":"FIXTURE_ONLY"},
                       {"name":"backup","type":"ss","server":"192.0.2.20","port":8080,"password":"FIXTURE_ONLY"}]
        }
        (self.root/"candidate.yaml").write_text(yaml.safe_dump(conf))
        (self.root/"candidate.yaml").chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self,*args):
        return subprocess.run([sys.executable,"-B",str(SCRIPT),"--fixture-root",str(self.root),*args],
                              capture_output=True,text=True,timeout=8)

    def assert_initial(self):
        for name,data in self.initial.items():
            self.assertEqual((self.root/"live"/name).read_bytes(),data,name)

    def test_successful_apply_only_fixture(self):
        p=self.run_cli("--apply")
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"transit-safe")
        self.assertFalse((self.root/"transaction.json").exists())
        self.assertFalse((self.root/"backup").exists())

    def test_injected_failure_at_every_phase_restores_all(self):
        for phase in m.PHASES:
            with self.subTest(phase=phase):
                p=self.run_cli("--apply","--fail-after",phase)
                self.assertEqual(p.returncode,2,p.stdout+p.stderr)
                self.assert_initial()
                self.assertFalse((self.root/"transaction.json").exists())

    def test_crash_then_independent_recovery_each_phase(self):
        for phase in m.PHASES:
            with self.subTest(phase=phase):
                crashed=self.run_cli("--apply","--crash-after",phase)
                self.assertEqual(crashed.returncode,42)
                self.assertTrue((self.root/"transaction.json").exists())
                result=self.run_cli("--recover")
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("RECOVERY=PASS",result.stdout)
                self.assert_initial()

    def test_idempotent_recovery(self):
        p=self.run_cli("--recover")
        self.assertEqual(p.returncode,0)
        self.assertIn("NOT_REQUIRED",p.stdout)

    def test_missing_direct_check_refuses_apply(self):
        (self.root/"live"/"direct-state").write_text("unverified\n")
        before=(self.root/"live"/"config.yaml").read_bytes()
        p=self.run_cli("--apply")
        self.assertEqual(p.returncode,2)
        self.assertEqual((self.root/"live"/"config.yaml").read_bytes(),before)

    def test_path_outside_tmp_refused(self):
        with self.assertRaises(m.TransactionError):
            m.private_root("/etc")

    def test_symlink_config_refused(self):
        path=self.root/"live"/"config.yaml"
        path.unlink()
        path.symlink_to(self.root/"candidate.yaml")
        self.assertEqual(self.run_cli("--apply").returncode,2)

    def test_tampered_backup_does_not_restore_corrupt_data(self):
        crashed=self.run_cli("--apply","--crash-after","install")
        self.assertEqual(crashed.returncode,42)
        (self.root/"backup"/"config.yaml").write_bytes(b"tampered")
        result=self.run_cli("--recover")
        self.assertEqual(result.returncode,2)
        self.assertTrue((self.root/"transaction.json").exists())
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")

    def test_simultaneous_transaction_lock(self):
        with open(self.root/"transaction.lock","w") as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            p=self.run_cli("--apply")
            self.assertEqual(p.returncode,2)
            self.assert_initial()
            fcntl.flock(f,fcntl.LOCK_UN)


if __name__=="__main__":
    unittest.main()
