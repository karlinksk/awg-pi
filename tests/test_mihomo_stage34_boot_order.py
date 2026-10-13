#!/usr/bin/env python3
"""Contract tests for UNINSTALLED boot-order examples. No systemd activation."""
import configparser
from pathlib import Path
import subprocess
import unittest

PROJECT=Path(__file__).resolve().parents[1]
EX=PROJECT/"examples"/"stage34-boot-only"

class BootOrderContract(unittest.TestCase):
    def setUp(self):
        self.path=EX/"awg-stage34-boot-recovery.service"
        self.unit=self.path.read_text()

    def test_early_unit_ordered_before_all_pi_forwarding(self):
        self.assertIn("After=local-fs.target",self.unit)
        for name in ("awg-pbr-setup.service","awg-mihomo.service","awg-selection-monitor.service"):
            self.assertIn(name,self.unit)
        self.assertIn("DefaultDependencies=no",self.unit)

    def test_all_consumer_units_require_recovery(self):
        for name in ("awg-pbr-setup","awg-mihomo","awg-selection-monitor"):
            p=EX/f"{name}.service.d"/"10-require-boot-recovery.conf"
            text=p.read_text()
            self.assertIn("Requires=awg-stage34-boot-recovery.service",text)
            self.assertIn("After=awg-stage34-boot-recovery.service",text)

    def test_sample_is_intentionally_unrunnable_and_not_enabled(self):
        self.assertIn("ExecStart=/usr/bin/false",self.unit)
        self.assertNotIn("[Install]",self.unit)
        self.assertIn("RequiresMountsFor=/var/lib/awg-pbr/native-fallback-recovery",self.unit)

    def test_unit_passes_systemd_analyze(self):
        result=subprocess.run(["systemd-analyze","verify",str(self.path)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_sstp_architecture_documented_as_mikrotik_owned(self):
        doc=(PROJECT/"docs"/"SSTP_INDEPENDENCE.md").read_text()
        self.assertIn("SSTP",doc)
        self.assertIn("MikroTik",doc)
        self.assertIn("Raspberry Pi",doc)
        self.assertIn("не должны зависеть",doc)

if __name__=="__main__":
    unittest.main()
