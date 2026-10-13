#!/usr/bin/env python3
"""Stage35 persistence fixture tests. Only fake content, never real Pi config."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROGRAM=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage35-persistent-fixture.py"
spec=importlib.util.spec_from_file_location("stage35_fixture",PROGRAM)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DurableIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="awg-stage35-",dir="/tmp")
        self.root=Path(self.temp.name)
        (self.root/"live").mkdir(mode=0o700)
        self.snapshot={
            "config.yaml":b"legacy_fixture_config\n",
            "mode":b"legacy\n",
            "service-state":b"active\n",
            "route-state":b"transit-safe\n",
            "transport":b"mihomo\n",
            "direct-state":b"verified\n",
        }
        for n,data in self.snapshot.items():
            (self.root/"live"/n).write_bytes(data)
        (self.root/"mikrotik.fixture").write_bytes(b"EXTERNAL_SSTP_ON_MIKROTIK_UNCHANGED")
        (self.root/"nas.fixture").write_bytes(b"NAS_CONFIGURATION_UNCHANGED")

    def tearDown(self):
        self.temp.cleanup()

    def cli(self,*args):
        return subprocess.run([sys.executable,"-B",str(PROGRAM),"--fixture-root",str(self.root),*args],
                              capture_output=True,text=True,timeout=9)

    def original(self):
        for n,data in self.snapshot.items():
            self.assertEqual((self.root/"live"/n).read_bytes(),data,n)
        self.assertEqual((self.root/"mikrotik.fixture").read_bytes(),b"EXTERNAL_SSTP_ON_MIKROTIK_UNCHANGED")
        self.assertEqual((self.root/"nas.fixture").read_bytes(),b"NAS_CONFIGURATION_UNCHANGED")

    def test_persistent_journal_new_process_recovers(self):
        armed=self.cli("--arm")
        self.assertEqual(armed.returncode,0,armed.stderr)
        self.assertTrue((self.root/"transaction.json").exists())
        recovered=self.cli("--boot-recover")
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        self.assertIn("RECOVERED",recovered.stdout)
        self.original()

    def test_each_crash_phase_new_process_recovers(self):
        for phase in ("journal","lockdown","install","candidate"):
            with self.subTest(phase=phase):
                self.assertEqual(self.cli("--arm","--crash-after",phase).returncode,42)
                self.assertEqual(self.cli("--boot-recover").returncode,0)
                self.original()

    def test_recovery_resumes_after_restoration_crash(self):
        for phase in ("verify","restore:config.yaml","restore:mode","policy"):
            with self.subTest(phase=phase):
                self.assertEqual(self.cli("--arm").returncode,0)
                self.assertEqual(self.cli("--boot-recover","--crash-after",phase).returncode,42)
                self.assertTrue((self.root/"transaction.json").exists())
                self.assertEqual(self.cli("--boot-recover").returncode,0)
                self.original()

    def test_bad_backup_fails_closed_and_leaves_journal(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"backup"/"config.yaml").write_bytes(b"tampered")
        r=self.cli("--boot-recover")
        self.assertEqual(r.returncode,2,r.stdout)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")
        self.assertTrue((self.root/"transaction.json").exists())

    def test_missing_ready_fails_closed(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"backup"/"READY").unlink()
        self.assertEqual(self.cli("--boot-recover").returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")

    def test_invalid_journal_fails_closed(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"transaction.json").write_bytes(b"not json")
        self.assertEqual(self.cli("--boot-recover").returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")

    def test_confirmed_cleanup_preserves_live_forwarding(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        m.atomic(self.root/"transaction.json",json.dumps({"version":1,"phase":"committed","boot":"TEST"}).encode())
        self.assertEqual(self.cli("--boot-recover").returncode,0)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"transit-safe")
        self.assertFalse((self.root/"transaction.json").exists())
        self.assertFalse((self.root/"backup").exists())

    def test_confirm_rejects_direct_bad(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        (self.root/"live"/"direct-state").write_text("unverified")
        self.assertEqual(self.cli("--confirm").returncode,2)
        self.assertTrue((self.root/"transaction.json").exists())

    def test_successful_confirm_no_recovery_needed(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        self.assertEqual(self.cli("--confirm").returncode,0)
        self.assertIn("IDLE",self.cli("--boot-recover").stdout)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")

    def test_double_arm_rejected(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        self.assertEqual(self.cli("--arm").returncode,2)

    def test_ready_snapshot_without_journal_keeps_lockdown(self):
        m.make_snapshot(self.root)
        r=self.cli("--boot-recover")
        self.assertEqual(r.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")
        self.assertTrue((self.root/"backup"/"READY").exists())

    def test_manifest_symlink_cannot_restore(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        path=self.root/"backup"/"manifest.json"
        path.unlink()
        path.symlink_to(self.root/"mikrotik.fixture")
        r=self.cli("--boot-recover")
        self.assertEqual(r.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")

    def test_outside_fixture_rejected(self):
        r=subprocess.run([sys.executable,str(PROGRAM),"--fixture-root","/etc","--arm"],
                         capture_output=True,timeout=5)
        self.assertEqual(r.returncode,2)

    def test_symlink_source_rejected(self):
        path=self.root/"live"/"config.yaml"
        path.unlink()
        path.symlink_to(self.root/"nas.fixture")
        r=self.cli("--arm")
        self.assertEqual(r.returncode,2)
        self.assertFalse((self.root/"backup"/"READY").exists())

    def test_mikrotik_and_nas_sentinels_are_untouched(self):
        self.assertEqual(self.cli("--arm").returncode,0)
        self.assertEqual(self.cli("--boot-recover").returncode,0)
        self.original()


if __name__=="__main__":
    unittest.main()
