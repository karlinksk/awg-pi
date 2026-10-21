#!/usr/bin/env python3
"""Installer contract: Xray probing after subscription import is NOT a live switch."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
INSTALL=(ROOT/"install.sh").read_text()
class XraySubscriptionScanner(unittest.TestCase):
    def test_install_on_clean_and_upgrade(self):
        for ext in ("service","path","timer"):
            self.assertIn(
                "install_project_unit units/awg-xray-subscription-scan."+ext,
                INSTALL)
        for ext in ("path","timer"):
            self.assertIn("awg-xray-subscription-scan."+ext,INSTALL)
        self.assertIn("systemctl enable --now awg-xray-subscription-scan.path awg-xray-subscription-scan.timer",INSTALL)
        self.assertNotIn("enable --now awg-xray-vless.service",INSTALL)
    def test_service_runs_isolated_bounded_probes(self):
        s=(ROOT/"units/awg-xray-subscription-scan.service").read_text()
        self.assertIn("ExecStart=/usr/local/sbin/awg-mihomo-unified-nodes probe-vless-all",s)
        self.assertIn("ConditionPathExists=/var/lib/awg-pbr/mihomo/providers/subscription.yaml",s)
        self.assertNotIn("awg-transport select",s)
        self.assertNotIn("awg-mihomo.service",s)
        self.assertNotIn("awg-transit",s)
        self.assertIn("TimeoutStartSec=",s)
    def test_provider_directory_watch_and_periodic_refresh(self):
        p=(ROOT/"units/awg-xray-subscription-scan.path").read_text()
        t=(ROOT/"units/awg-xray-subscription-scan.timer").read_text()
        self.assertIn("PathChanged=/var/lib/awg-pbr/mihomo/providers",p)
        self.assertIn("OnUnitInactiveSec=10min",t)
        self.assertIn("awg-xray-subscription-scan.service",t)
    def test_current_fingerprints_cache_only(self):
        s=(ROOT/"src/awg-mihomo-unified-nodes.py").read_text()
        self.assertIn("MAX_PROBE=10",s)
        self.assertIn("PROVIDER_CHANGED_DURING_PROBE",s)
        self.assertIn("transport(n)==\"XRAY\"",s)
        self.assertIn("persist_cache(adapter,sha,updated)",s)
if __name__=="__main__":unittest.main()
