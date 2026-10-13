#!/usr/bin/env python3
"""Stage33 fixture-only crash-consistent backup publication and validation."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

P=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage33-durable-fixture.py"
spec=importlib.util.spec_from_file_location("stage33_fixture",P)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="stage33-fixture-",dir="/tmp")
        self.root=Path(self.tmp.name)
        (self.root/"live").mkdir(mode=0o700)
        (self.root/"live"/"config.yaml").write_text("mock config")
        (self.root/"live"/"mode").write_text("legacy")
        self.orig=(self.root/"live"/"config.yaml").read_bytes()
    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_fsync_published_marker_and_restore_replica(self):
        self.assertEqual(m.generate(self.root),2)
        self.assertEqual(m.validate(self.root)["files"]["config.yaml"]["present"],True)
        self.assertTrue(m.recover_replica(self.root))
        self.assertEqual((self.root/"restored-replica"/"config.yaml").read_bytes(),self.orig)
        self.assertEqual((self.root/"live"/"config.yaml").read_bytes(),self.orig)

    def test_unfinished_backup_without_marker_refused(self):
        with self.assertRaises(m.BackupError):
            m.generate(self.root,abort_after="manifest")
        self.assertFalse((self.root/"recovery"/"READY").exists())
        with self.assertRaises(m.BackupError):m.validate(self.root)

    def test_interruption_each_file_denies_publish(self):
        for name in ("config.yaml","mode","service-state"):
            with self.subTest(name=name):
                # reset previous isolated test target
                import shutil
                shutil.rmtree(self.root/"recovery",ignore_errors=True)
                with self.assertRaises(m.BackupError):m.generate(self.root,abort_after=name)
                self.assertFalse((self.root/"recovery"/"READY").exists())

    def test_corrupted_backup_refused(self):
        m.generate(self.root)
        (self.root/"recovery"/"config.yaml").write_bytes(b"tampered")
        with self.assertRaises(m.BackupError):m.validate(self.root)
        with self.assertRaises(m.BackupError):m.recover_replica(self.root)

    def test_missing_manifest_refused(self):
        m.generate(self.root)
        (self.root/"recovery"/"manifest.json").unlink()
        with self.assertRaises(FileNotFoundError):m.validate(self.root)

    def test_symlink_source_refused(self):
        (self.root/"live"/"mode").unlink()
        (self.root/"live"/"mode").symlink_to(self.root/"live"/"config.yaml")
        with self.assertRaises(m.BackupError):m.generate(self.root)
        self.assertFalse((self.root/"recovery"/"READY").exists())

    def test_symlink_recovery_file_refused(self):
        m.generate(self.root)
        (self.root/"recovery"/"config.yaml").unlink()
        (self.root/"recovery"/"config.yaml").symlink_to(self.root/"live"/"config.yaml")
        with self.assertRaises(m.BackupError):m.validate(self.root)

    def test_private_backup_permissions(self):
        m.generate(self.root)
        for name in ("READY","manifest.json","config.yaml"):
            self.assertEqual(stat.S_IMODE((self.root/"recovery"/name).stat().st_mode),0o600)

    def test_repeated_snapshot_denied(self):
        m.generate(self.root)
        with self.assertRaises(m.BackupError):m.generate(self.root)

    def test_outside_tmp_refused(self):
        with self.assertRaises(m.BackupError):m.fixture_root("/etc")

    def test_file_and_directory_fsync_invoked(self):
        orig=m.os.fsync
        seen=[]
        def tracking(fd):
            seen.append(fd)
            return orig(fd)
        m.os.fsync=tracking
        try:
            m.generate(self.root)
        finally:
            m.os.fsync=orig
        self.assertGreaterEqual(len(seen),7)

if __name__=="__main__":
    unittest.main()
