#!/usr/bin/env python3
"""Stage32: independent deadline, health and reboot-recovery fixture tests."""
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

PROGRAM=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage32-fixture-watchdog.py"
spec=importlib.util.spec_from_file_location("stage32_fixture",PROGRAM)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class WatchdogFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="stage32-fixture-",dir="/tmp")
        self.root=Path(self.tmp.name)
        (self.root/"live").mkdir(mode=0o700)
        self.original={
          "config.yaml":b"mode: legacy\n",
          "mode":b"legacy\n",
          "service-state":b"active\n",
          "route-state":b"transit-safe\n",
          "transport":b"mihomo\n",
          "direct-state":b"verified\n",
        }
        for name,data in self.original.items():
            (self.root/"live"/name).write_bytes(data)
        candidate={"tun":{"enable":True},
                   "proxy-groups":[{"name":"AWG-MIHOMO","type":"fallback","proxies":["n1","n2"]}],
                   "proxies":[{"name":"n1","type":"ss"},{"name":"n2","type":"ss"}]}
        (self.root/"candidate.yaml").write_text(yaml.safe_dump(candidate))

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self,*args,now=1000,boot="BOOT_A"):
        return subprocess.run(
            [sys.executable,"-B",str(PROGRAM),"--fixture-root",str(self.root),
             "--simulated-now",str(now),"--simulated-boot-id",boot,*args],
            capture_output=True,text=True,timeout=9)

    def assert_restored(self):
        for name,data in self.original.items():
            self.assertEqual((self.root/"live"/name).read_bytes(),data,name)
        self.assertFalse((self.root/"transaction.json").exists())
        self.assertFalse((self.root/"watchdog.json").exists())

    def test_armed_pending_until_explicit_confirmation(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        self.assertIn("PENDING_ACK",self.cli("--check",now=1050).stdout)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        confirm=self.cli("--confirm",now=1051)
        self.assertEqual(confirm.returncode,0,confirm.stderr)
        self.assertIn("CONFIRMED",confirm.stdout)
        self.assertIn("IDLE",self.cli("--check",now=1060).stdout)

    def test_expired_deadline_restores(self):
        self.assertEqual(self.cli("--arm","--timeout-seconds","30").returncode,0)
        outcome=self.cli("--check",now=1030)
        self.assertIn("ROLLBACK_DEADLINE",outcome.stdout)
        self.assert_restored()

    def test_changed_boot_id_restores_before_expiry(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        outcome=self.cli("--check",now=1001,boot="BOOT_B")
        self.assertIn("ROLLBACK_BOOT_CHANGED",outcome.stdout)
        self.assert_restored()

    def test_bad_health_rolls_back_early(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"live"/"direct-state").write_text("unsafe\n")
        outcome=self.cli("--check",now=1001)
        self.assertIn("ROLLBACK_HEALTH",outcome.stdout)
        self.assert_restored()

    def test_expired_confirmation_cannot_commit(self):
        self.assertEqual(self.cli("--arm","--timeout-seconds","15").returncode,0)
        result=self.cli("--confirm",now=1015)
        self.assertEqual(result.returncode,2)
        self.assert_restored()

    def test_crash_and_independent_recovery_all_phases(self):
        for phase in ("armed","quarantine","install","verify"):
            with self.subTest(phase=phase):
                crash=self.cli("--arm","--crash-after",phase)
                self.assertEqual(crash.returncode,42,crash.stderr)
                outcome=self.cli("--check",now=1001,boot="BOOT_B")
                self.assertIn("ROLLBACK_BOOT_CHANGED",outcome.stdout)
                self.assert_restored()

    def test_manual_cancel_immediate_restoration(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        result=self.cli("--cancel")
        self.assertIn("RECOVERED",result.stdout)
        self.assert_restored()

    def test_corrupt_lease_restores_from_verified_backup(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"watchdog.json").write_text("garbled")
        result=self.cli("--check")
        self.assertIn("ROLLBACK_INVALID_LEASE",result.stdout)
        self.assert_restored()

    def test_corrupt_backup_refused_and_journal_retained(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"backup"/"config.yaml").write_bytes(b"bad")
        result=self.cli("--check",now=1060)
        self.assertEqual(result.returncode,2)
        self.assertTrue((self.root/"transaction.json").exists())

    def test_pending_second_arm_rejected(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        result=self.cli("--arm")
        self.assertEqual(result.returncode,2)
        self.assertIn("PENDING_ACK",self.cli("--check").stdout)

    def test_outside_private_tmp_refused(self):
        result=subprocess.run([sys.executable,"-B",str(PROGRAM),
            "--fixture-root","/etc","--check"],capture_output=True,text=True,timeout=6)
        self.assertEqual(result.returncode,2)

    def test_bounds_on_deadline(self):
        self.assertEqual(self.cli("--arm","--timeout-seconds","1").returncode,2)
        self.assertEqual(self.cli("--arm","--timeout-seconds","9999").returncode,2)
        self.assertFalse((self.root/"transaction.json").exists())

    def test_backwards_clock_restores_instead_of_extending_lease(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        outcome=self.cli("--check",now=999)
        self.assertIn("ROLLBACK_CLOCK_ROLLBACK",outcome.stdout)
        self.assert_restored()

    def test_missing_lease_restores_pending_journal(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"watchdog.json").unlink()
        outcome=self.cli("--check")
        self.assertIn("ROLLBACK_INVALID_LEASE",outcome.stdout)
        self.assert_restored()

    def test_interrupted_commit_after_backup_delete_does_not_rollback(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        mod.stage31.set_phase(self.root,"confirmed")
        import shutil
        shutil.rmtree(self.root/"backup")
        outcome=self.cli("--check",now=1002)
        self.assertIn("COMMIT_CLEANUP",outcome.stdout)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        self.assertFalse((self.root/"transaction.json").exists())

    def test_interrupted_commit_before_backup_delete_is_reconciled(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        mod.stage31.set_phase(self.root,"confirmed")
        outcome=self.cli("--check",now=1002,boot="BOOT_B")
        self.assertIn("COMMIT_CLEANUP",outcome.stdout)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        self.assertFalse((self.root/"backup").exists())

    def test_lock_contended_cannot_arm(self):
        with open(self.root/"transaction.lock","w") as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            self.assertEqual(self.cli("--arm").returncode,2)
            fcntl.flock(f,fcntl.LOCK_UN)
        self.assertFalse((self.root/"transaction.json").exists())

if __name__=="__main__":
    unittest.main()
