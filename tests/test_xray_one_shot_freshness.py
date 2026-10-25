#!/usr/bin/env python3
"""The one-shot Xray failover test must use fresh 600s candidate evidence."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/awg-xray-selective-one-shot-failover.sh"
SOURCE=SCRIPT.read_text()

class FreshXrayFault(unittest.TestCase):
    def test_syntax(self):
        r=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
    def test_refresh_precedes_fault_and_watchdog(self):
        refresh=SOURCE.index('probe-vless-all')
        certified=SOURCE.index('best --engine XRAY')
        armed=SOURCE.index('systemd-run --quiet --collect')
        fault=SOURCE.index('systemctl stop awg-mihomo')
        self.assertLess(refresh,certified)
        self.assertLess(certified,armed)
        self.assertLess(armed,fault)
    def test_no_outage_if_fresh_proof_missing(self):
        self.assertIn('die XRAY_PASSIVE_SCAN_FAILED',SOURCE)
        self.assertIn('die XRAY_NO_FRESH_NETWORK_OK',SOURCE)
        self.assertIn('die XRAY_NO_CANDIDATE',SOURCE)
        self.assertIn('api mihomo0 && api awg0 || die HTTPS_LOST_AFTER_SCAN',SOURCE)
    def test_no_reconfiguration_of_router_or_dns(self):
        for banned in ['awg-mode-switch transit','systemctl stop dnsmasq',
                       'systemctl stop ssh','/ip/firewall','MIHOMO_READY_AUTO_CANARY=1']:
            self.assertNotIn(banned,SOURCE)

if __name__=="__main__":unittest.main()
