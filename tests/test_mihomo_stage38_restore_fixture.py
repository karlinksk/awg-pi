#!/usr/bin/env python3
"""Stage38 exact-restore fixture tests, never touches real VPN configs."""
import fcntl
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

PROGRAM=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage38-restore-fixture.py"
spec=importlib.util.spec_from_file_location("stage38",PROGRAM)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
snap=mod.snap


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix="awg-stage36-",dir="/tmp")
        self.root=Path(self.t.name)
        (self.root/"source").mkdir(mode=0o700)
        self.initial={}
        for name in snap.SOURCE_FILES[:2]:
            p=self.root/"source"/name
            p.parent.mkdir(parents=True,exist_ok=True)
            data=("ORIGINAL_TEST_ONLY_"+name).encode()
            p.write_bytes(data)
            p.chmod(0o600)
            self.initial[name]=data
        self.sstp=self.root/"mikrotik-unchanged.fixture"
        self.nas=self.root/"nas-unchanged.fixture"
        self.sstp.write_bytes(b"MIKROTIK_EXCLUDED")
        self.nas.write_bytes(b"NAS_EXCLUDED")
        self.assertEqual(snap.capture(self.root/"source",self.root/"recovery",os.geteuid()),2)
        self.guard=self.root/"fixture-lockdown.guard"
        self.guard.write_bytes(mod.GUARD)
        self.guard.chmod(0o600)
        (self.root/"source"/snap.SOURCE_FILES[0]).write_bytes(b"BROKEN_CURRENT_CONFIG")
        (self.root/"source"/snap.SOURCE_FILES[1]).write_bytes(b"BROKEN_CURRENT_PROVIDER")

    def tearDown(self):
        self.t.cleanup()

    def cli(self,*args):
        return subprocess.run([sys.executable,"-B",str(PROGRAM),"--fixture-root",str(self.root),*args],
                              capture_output=True,text=True,timeout=9)

    def assert_original(self):
        for name,content in self.initial.items():
            p=self.root/"source"/name
            self.assertEqual(p.read_bytes(),content)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
        self.assertEqual(self.sstp.read_bytes(),b"MIKROTIK_EXCLUDED")
        self.assertEqual(self.nas.read_bytes(),b"NAS_EXCLUDED")
        self.assertTrue(self.guard.exists())

    def test_exact_restoration_and_lockdown_remains(self):
        r=self.cli("--restore")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("RESTORED_GUARD_HELD",r.stdout)
        self.assert_original()
        self.assertTrue((self.root/"recovery"/"READY").exists())

    def test_replay_idempotent(self):
        self.assertEqual(self.cli("--restore").returncode,0)
        self.assertEqual(self.cli("--restore").returncode,0)
        self.assert_original()

    def test_restores_absence_of_optional_state(self):
        optional=self.root/"source"/snap.SOURCE_FILES[3]
        optional.write_text("ADDED_AFTER_SNAPSHOT")
        self.assertEqual(self.cli("--restore").returncode,0)
        self.assertFalse(optional.exists())

    def test_missing_guard_blocks_restore(self):
        self.guard.unlink()
        self.assertEqual(self.cli("--restore").returncode,2)
        self.assertEqual((self.root/"source"/snap.SOURCE_FILES[0]).read_bytes(),b"BROKEN_CURRENT_CONFIG")

    def test_bad_guard_permission_blocks_restore(self):
        self.guard.chmod(0o644)
        self.assertEqual(self.cli("--restore").returncode,2)

    def test_corrupt_backup_blocks_before_mutating_source(self):
        (self.root/"recovery"/"00.bin").write_bytes(b"tampered")
        result=self.cli("--restore")
        self.assertEqual(result.returncode,2)
        self.assertEqual((self.root/"source"/snap.SOURCE_FILES[0]).read_bytes(),b"BROKEN_CURRENT_CONFIG")
        self.assertTrue(self.guard.exists())

    def test_symlink_source_target_blocks_restore(self):
        p=self.root/"source"/snap.SOURCE_FILES[0]
        p.unlink()
        p.symlink_to(self.sstp)
        self.assertEqual(self.cli("--restore").returncode,2)
        self.assertEqual(self.sstp.read_bytes(),b"MIKROTIK_EXCLUDED")

    def test_interrupt_then_independent_resumption(self):
        for index in (0,1,4):
            with self.subTest(index=index):
                # Return changed sources before each simulation.
                (self.root/"source"/snap.SOURCE_FILES[0]).write_bytes(b"BROKEN_CURRENT_CONFIG")
                (self.root/"source"/snap.SOURCE_FILES[1]).write_bytes(b"BROKEN_CURRENT_PROVIDER")
                r=self.cli("--restore","--crash-after-index",str(index))
                self.assertEqual(r.returncode,42,r.stderr)
                self.assertEqual(self.cli("--restore").returncode,0)
                self.assert_original()

    def test_maintenance_lock_race_refuses(self):
        with open(self.root/".maintenance.lock","w") as file:
            fcntl.flock(file,fcntl.LOCK_EX)
            self.assertEqual(self.cli("--restore").returncode,2)
            fcntl.flock(file,fcntl.LOCK_UN)
        self.assertEqual(self.cli("--restore").returncode,0)

    def test_external_path_cannot_be_target(self):
        bad=subprocess.run([sys.executable,"-B",str(PROGRAM),"--fixture-root","/etc","--restore"],
                           capture_output=True,timeout=8)
        self.assertEqual(bad.returncode,2)

    def test_readonly_verify_without_guard(self):
        self.guard.unlink()
        r=self.cli("--verify")
        self.assertEqual(r.returncode,0,r.stderr)


if __name__=="__main__":
    unittest.main()
