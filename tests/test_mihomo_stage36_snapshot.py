#!/usr/bin/env python3
"""Stage36 protected source manifest, real local filesystem integration fixtures."""
import fcntl
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage36-snapshot.py"
spec=importlib.util.spec_from_file_location("stage36",SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Stage36Snapshot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="awg-stage36-",dir="/tmp")
        self.root=Path(self.temp.name)
        (self.root/"source").mkdir(mode=0o700)
        for name in m.SOURCE_FILES[:2]:
            path=self.root/"source"/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(f"SYNTHETIC_{name.replace('/','_')}\n")
        self.sentinel=self.root/"EXTERNAL_MIKROTIK_NAS_FIXTURE"
        self.sentinel.write_text("independent appliances immutable")
        self.marker=self.sentinel.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def cli(self,*args):
        return subprocess.run([sys.executable,"-B",str(SCRIPT),"--fixture-root",str(self.root),*args],
                              capture_output=True,text=True,timeout=8)

    def original(self):
        self.assertEqual(self.sentinel.read_bytes(),self.marker)

    def test_two_required_snapshot_and_independent_verification(self):
        capture=self.cli("--snapshot")
        self.assertEqual(capture.returncode,0,capture.stderr)
        self.assertIn("entries=2",capture.stdout)
        verify=self.cli("--verify")
        self.assertEqual(verify.returncode,0,verify.stderr)
        self.assertIn("entries=2",verify.stdout)
        self.original()

    def test_optional_existing_snapshot_stays_private(self):
        path=self.root/"source"/m.SOURCE_FILES[6]
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("node-policy=manual\n")
        self.assertEqual(self.cli("--snapshot").returncode,0)
        self.assertEqual(self.cli("--verify").returncode,0)
        for f in (self.root/"recovery").iterdir():
            self.assertEqual(stat.S_IMODE(f.stat().st_mode),0o600)

    def test_snapshots_are_not_overwritten(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        self.assertEqual(self.cli("--snapshot").returncode,2)
        self.assertEqual(self.cli("--verify").returncode,0)

    def test_corrupt_backup_rejected(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        (self.root/"recovery"/"00.bin").write_bytes(b"malicious")
        self.assertEqual(self.cli("--verify").returncode,2)

    def test_missing_ready_rejected(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        (self.root/"recovery"/"READY").unlink()
        self.assertEqual(self.cli("--verify").returncode,2)

    def test_added_file_rejected(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        (self.root/"recovery"/"unexpected").write_bytes(b"unexpected")
        self.assertEqual(self.cli("--verify").returncode,2)

    def test_required_file_missing_rejected_no_ready(self):
        (self.root/"source"/m.SOURCE_FILES[1]).unlink()
        self.assertEqual(self.cli("--snapshot").returncode,2)
        self.assertFalse((self.root/"recovery"/"READY").exists())

    def test_symlink_required_source_rejected(self):
        src=self.root/"source"/m.SOURCE_FILES[0]
        src.unlink()
        src.symlink_to(self.sentinel)
        self.assertEqual(self.cli("--snapshot").returncode,2)
        self.assertFalse((self.root/"recovery"/"READY").exists())

    def test_symlink_backup_rejected(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        snap=self.root/"recovery"/"00.bin"
        snap.unlink()
        snap.symlink_to(self.sentinel)
        self.assertEqual(self.cli("--verify").returncode,2)

    def test_external_path_refused(self):
        r=subprocess.run([sys.executable,"-B",str(SCRIPT),"--fixture-root","/etc","--snapshot"],
                         capture_output=True,text=True,timeout=6)
        self.assertEqual(r.returncode,2)

    def test_production_denied_without_root(self):
        if os.geteuid()==0:
            self.skipTest("not meaningful under root")
        p=subprocess.run([sys.executable,"-B",str(SCRIPT),"--production","--snapshot",
            "--acknowledge-production-snapshot"],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,2)
        self.assertNotIn("password",p.stdout+p.stderr)

    def test_fixture_refuses_live_ack(self):
        self.assertEqual(self.cli("--snapshot","--acknowledge-production-snapshot").returncode,2)

    def test_corrupt_manifest_rejected(self):
        self.assertEqual(self.cli("--snapshot").returncode,0)
        (self.root/"recovery"/"manifest.json").write_text("invalid")
        self.assertEqual(self.cli("--verify").returncode,2)

    def test_lock_contention_refuses_snapshot(self):
        with open(self.root/".stage36-snapshot.lock","w") as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            self.assertEqual(self.cli("--snapshot").returncode,2)
            self.assertFalse((self.root/"recovery").exists())
            fcntl.flock(f,fcntl.LOCK_UN)

    def test_recovery_parent_refuses_world_writable(self):
        self.root.chmod(0o777)
        self.assertEqual(self.cli("--snapshot").returncode,2)
        self.root.chmod(0o700)


if __name__=="__main__":
    unittest.main()
