#!/usr/bin/env python3
"""Stage39: end-to-end (synthetic) transaction with real separate-process crashes."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
CLI=HERE/"src"/"awg-mihomo-stage39-coordinator-fixture.py"
sys.path.insert(0,str(HERE/"src"))
import importlib.util
spec=importlib.util.spec_from_file_location("snapshot39",HERE/"src"/"awg-mihomo-stage36-snapshot.py")
snap=importlib.util.module_from_spec(spec);spec.loader.exec_module(snap)

class Integrated(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir="/tmp",prefix="awg-stage36-stage39-")
        self.root=Path(self.tmp.name)
        (self.root/"source").mkdir(mode=0o700)
        self.original={}
        for name in snap.SOURCE_FILES[:2]:
            target=self.root/"source"/name
            target.parent.mkdir(parents=True,exist_ok=True)
            blob=("STAGE39_ORIGINAL_"+name).encode()
            target.write_bytes(blob)
            target.chmod(0o600)
            self.original[name]=blob
        (self.root/"fixture-health.txt").write_bytes(b"READY:HTTPS:DIRECT:GUARD\n")
        (self.root/"fixture-candidate").write_bytes(b"STAGE39_NATIVE_FALLBACK_TEST_ONLY\n")
        self.sstp=self.root/"mikrotik-independent.fixture"
        self.nas=self.root/"nas-independent.fixture"
        self.sstp.write_bytes(b"ROUTER:UNCHANGED")
        self.nas.write_bytes(b"NAS:UNCHANGED")

    def tearDown(self):
        self.tmp.cleanup()

    def runcli(self,*args):
        return subprocess.run([sys.executable,"-B",str(CLI),"--fixture-root",str(self.root),*args],
                              text=True,capture_output=True,timeout=7)

    def check_external(self):
        self.assertEqual(self.sstp.read_bytes(),b"ROUTER:UNCHANGED")
        self.assertEqual(self.nas.read_bytes(),b"NAS:UNCHANGED")

    def check_restored(self):
        for name,blob in self.original.items():
            self.assertEqual((self.root/"source"/name).read_bytes(),blob,name)
        self.assertTrue((self.root/"fixture-lockdown.guard").is_file())
        self.check_external()

    def test_healthy_arm_leaves_pending_and_guard(self):
        r=self.runcli("--start")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("PENDING",r.stdout)
        self.assertTrue((self.root/"stage39-transaction.json").is_file())
        self.assertTrue((self.root/"recovery"/"READY").is_file())
        self.assertTrue((self.root/"fixture-lockdown.guard").is_file())
        self.check_external()

    def test_confirmed_cleanup_preserves_candidate(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        r=self.runcli("--confirm")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("CONFIRMED",r.stdout)
        self.assertFalse((self.root/"stage39-transaction.json").exists())
        self.assertFalse((self.root/"recovery").exists())
        self.assertEqual((self.root/"source"/snap.SOURCE_FILES[0]).read_bytes(),b"STAGE39_NATIVE_FALLBACK_TEST_ONLY\n")
        self.assertTrue((self.root/"fixture-lockdown.guard").exists())

    def test_separate_process_recovery_keeps_guard(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        r=self.runcli("--recover")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("RESTORED_GUARD_HELD",r.stdout)
        self.check_restored()
        self.assertTrue((self.root/"stage39-transaction.json").is_file())
        self.assertTrue((self.root/"recovery"/"READY").is_file())

    def test_all_crash_windows_and_repeated_recovery(self):
        for phase in ("backup","journal","lockdown","candidate","verified"):
            with self.subTest(phase=phase):
                self.assertEqual(self.runcli("--start","--crash-after",phase).returncode,42)
                r=self.runcli("--recover")
                if phase=="backup":
                    self.assertEqual(r.returncode,2)
                    self.assertIn("ORPHAN_QUARANTINED",r.stdout)
                else:
                    self.assertEqual(r.returncode,0,r.stderr)
                    self.assertIn("RESTORED_GUARD_HELD",r.stdout)
                    self.assertEqual(self.runcli("--recover").returncode,0)
                self.check_external()
                if phase!="backup":
                    self.check_restored()
                # Each crash scenario has its own clean fixture.
                from shutil import rmtree
                rmtree(self.root/"recovery")
                (self.root/"stage39-transaction.json").unlink(missing_ok=True)
                (self.root/"fixture-lockdown.guard").unlink(missing_ok=True)
                for name,blob in self.original.items():
                    (self.root/"source"/name).write_bytes(blob)

    def test_interrupt_mid_restore_then_restart(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        self.assertEqual(self.runcli("--recover","--crash-after","restored").returncode,42)
        self.assertEqual(self.runcli("--recover").returncode,0)
        self.check_restored()

    def test_corrupt_backup_rejected_with_guard(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        (self.root/"recovery"/"00.bin").write_bytes(b"BAD")
        r=self.runcli("--recover")
        self.assertEqual(r.returncode,2)
        self.assertIn("ROLLBACK_UNSAFE_QUARANTINED",r.stdout)
        self.assertTrue((self.root/"fixture-lockdown.guard").exists())
        self.assertTrue((self.root/"stage39-transaction.json").exists())
        self.check_external()

    def test_invalid_journal_quarantined(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        (self.root/"stage39-transaction.json").write_text("garbled")
        r=self.runcli("--recover")
        self.assertEqual(r.returncode,2)
        self.assertIn("CORRUPT_JOURNAL_QUARANTINED",r.stdout)
        self.assertTrue((self.root/"fixture-lockdown.guard").exists())

    def test_reject_start_without_healthy_preflight(self):
        (self.root/"fixture-health.txt").write_text("BROKEN")
        r=self.runcli("--start")
        self.assertEqual(r.returncode,2)
        self.assertFalse((self.root/"recovery").exists())

    def test_confirm_rejects_candidate_mismatch(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        (self.root/"source"/snap.SOURCE_FILES[0]).write_bytes(b"DIFFERENT")
        r=self.runcli("--confirm")
        self.assertEqual(r.returncode,2)
        self.assertTrue((self.root/"stage39-transaction.json").exists())

    def test_concurrent_maintenance_owner_blocks_start(self):
        with open(self.root/".maintenance.lock","w") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            self.assertEqual(self.runcli("--start").returncode,2)
            self.assertFalse((self.root/"recovery").exists())
            fcntl.flock(file, fcntl.LOCK_UN)

    def test_fixture_rejects_production_paths(self):
        r=subprocess.run([sys.executable,"-B",str(CLI),"--fixture-root","/etc","--recover"],
                         text=True,capture_output=True,timeout=6)
        self.assertEqual(r.returncode,2)

    def test_confirmed_journal_cleanup_without_rollback(self):
        self.assertEqual(self.runcli("--start").returncode,0)
        snap.atomic_write(self.root/"stage39-transaction.json",json.dumps({"schema":1,"status":"confirmed"}).encode())
        r=self.runcli("--recover")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("COMMIT_CLEANUP",r.stdout)
        self.assertEqual((self.root/"source"/snap.SOURCE_FILES[0]).read_bytes(),b"STAGE39_NATIVE_FALLBACK_TEST_ONLY\n")
        self.assertFalse((self.root/"recovery").exists())
        self.check_external()

if __name__=="__main__":
    unittest.main()
