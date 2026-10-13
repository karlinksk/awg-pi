#!/usr/bin/env python3
"""Static Stage41 systemd contract validation. NEVER installs/restarts a unit."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"examples"/"stage41-boot-contract"
PROTECTED=(
    "awg-pbr-setup.service",
    "awg-mihomo.service",
    "awg-selection-monitor.service",
    "awg-pbr-health.service",
    "awg-quick@awg0.service",
)
RECOVERY="awg-native-fallback-recovery.service"

class Contract(unittest.TestCase):
    def test_five_protected_consumers_required_and_ordered(self):
        for name in PROTECTED:
            p=BASE/(name+".d")/"10-recovery-gate.conf"
            text=p.read_text()
            with self.subTest(name=name):
                self.assertIn("Requires="+RECOVERY,text)
                self.assertIn("After="+RECOVERY,text)

    def test_recovery_early_before_every_consumer(self):
        text=(BASE/RECOVERY).read_text()
        self.assertIn("DefaultDependencies=no",text)
        self.assertIn("After=local-fs.target",text)
        for name in PROTECTED:
            with self.subTest(name=name):
                self.assertIn(name,text)

    def test_local_recovery_mount_required(self):
        text=(BASE/RECOVERY).read_text()
        self.assertIn("RequiresMountsFor=/var/lib/awg-pbr/native-fallback-recovery",text)

    def test_example_cannot_be_mistaken_for_working_recovery(self):
        text=(BASE/RECOVERY).read_text()
        self.assertIn("ExecStart=/usr/bin/false",text)
        self.assertNotIn("[Install]",text)

    def test_static_systemd_unit_syntax(self):
        p=subprocess.run(["systemd-analyze","verify",str(BASE/RECOVERY)],text=True,
                         capture_output=True,timeout=12)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_no_install_or_service_operations_in_examples(self):
        for file in BASE.rglob("*"):
            if not file.is_file():
                continue
            contents=file.read_text()
            self.assertNotIn("systemctl enable",contents)
            self.assertNotIn("systemctl restart",contents)
            self.assertNotIn("ip route add",contents)
            self.assertNotIn("nft add",contents)

if __name__=="__main__":
    unittest.main()
