#!/usr/bin/env python3
"""Stage34 boot gate: separate-process recovery in isolated private fixtures."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml

script=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage34-boot-gate-fixture.py"
spec=importlib.util.spec_from_file_location("stage34",script)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class BootGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="stage34-boot-fixture-",dir="/tmp")
        self.root=Path(self.temp.name)
        (self.root/"live").mkdir(mode=0o700)
        self.initial={
            "config.yaml":b"legacy: fixture\n",
            "mode":b"legacy\n",
            "service-state":b"active\n",
            "route-state":b"transit-safe\n",
            "transport":b"mihomo\n",
            "direct-state":b"verified\n"
        }
        for name,val in self.initial.items():
            (self.root/"live"/name).write_bytes(val)
        self.sstp=b"mikrotik-sstp-independent-management-fixture"
        (self.root/"mikrotik-sstp.fixture").write_bytes(self.sstp)
        data={"tun":{"enable":True},
              "proxy-groups":[{"name":"AWG-MIHOMO","type":"fallback","proxies":["a","b"]}],
              "proxies":[{"name":"a","type":"ss"},{"name":"b","type":"ss"}]}
        (self.root/"candidate.yaml").write_text(yaml.safe_dump(data))

    def tearDown(self):
        self.temp.cleanup()

    def provision(self):
        self.assertEqual(m.s33.generate(self.root),6)
        m.s32.arm(self.root,1000,"TEST_BOOT_ID",60)
        self.assertTrue((self.root/"transaction.json").exists())

    def cli(self,fail=None):
        cmd=[sys.executable,"-B",str(script),"--fixture-root",str(self.root)]
        if fail:cmd.extend(["--inject-fail",fail])
        return subprocess.run(cmd,capture_output=True,text=True,timeout=9)

    def assert_original(self):
        for name,data in self.initial.items():
            self.assertEqual((self.root/"live"/name).read_bytes(),data,name)
        self.assertEqual((self.root/"mikrotik-sstp.fixture").read_bytes(),self.sstp)

    def test_pending_reboot_restores_and_keeps_sstp_independent(self):
        self.provision()
        result=self.cli()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("RECOVERED_FAIL_CLOSED",result.stdout)
        self.assert_original()
        self.assertFalse((self.root/"transaction.json").exists())

    def test_unpublished_backup_refuses_and_keeps_lockdown(self):
        self.provision()
        (self.root/"recovery"/"READY").unlink()
        result=self.cli()
        self.assertEqual(result.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")
        self.assertTrue((self.root/"transaction.json").exists())
        self.assertEqual((self.root/"mikrotik-sstp.fixture").read_bytes(),self.sstp)

    def test_tampered_backup_refuses_and_preserves_journal(self):
        self.provision()
        (self.root/"recovery"/"config.yaml").write_bytes(b"corrupt")
        result=self.cli()
        self.assertEqual(result.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")
        self.assertTrue((self.root/"transaction.json").exists())

    def test_recovery_can_resume_after_each_simulated_crash(self):
        for point in ("quarantine","verified","restore:config.yaml","restore:mode","policy"):
            with self.subTest(point=point):
                # Each subtest creates separate mock state; no prod writes.
                self.provision()
                first=self.cli(point)
                self.assertEqual(first.returncode,2,point)
                again=self.cli()
                self.assertEqual(again.returncode,0,again.stderr)
                self.assert_original()
                shutil.rmtree(self.root/"recovery")
                # Reset the fixture candidate and state for subsequent iterations
                for name,val in self.initial.items():
                    (self.root/"live"/name).write_bytes(val)

    def test_confirmed_activation_not_rolled_back(self):
        self.provision()
        m.s31.set_phase(self.root,"confirmed")
        result=self.cli()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("CONFIRMED_CLEANUP",result.stdout)
        self.assertEqual((self.root/"live"/"mode").read_text().strip(),"native")
        self.assertEqual((self.root/"mikrotik-sstp.fixture").read_bytes(),self.sstp)

    def test_no_pending_transaction_has_no_effect(self):
        before=(self.root/"live"/"route-state").read_bytes()
        result=self.cli()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("NO_PENDING",result.stdout)
        self.assertEqual((self.root/"live"/"route-state").read_bytes(),before)

    def test_invalid_pending_journal_forces_lockdown(self):
        self.provision()
        (self.root/"transaction.json").write_text("invalid json")
        result=self.cli()
        self.assertEqual(result.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")
        self.assertEqual((self.root/"mikrotik-sstp.fixture").read_bytes(),self.sstp)

    def test_unexpected_target_directory_refused(self):
        result=subprocess.run([sys.executable,str(script),"--fixture-root","/etc"],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,2)

    def test_invalid_legacy_snapshot_leaves_lockdown(self):
        (self.root/"live"/"direct-state").write_text("unverified\n")
        m.s33.generate(self.root)
        (self.root/"live"/"direct-state").write_text("verified\n")
        m.s32.arm(self.root,1000,"TEST_BOOT_ID",60)
        result=self.cli()
        self.assertEqual(result.returncode,2)
        self.assertEqual((self.root/"live"/"route-state").read_text().strip(),"lockdown")

if __name__=="__main__":
    unittest.main()
