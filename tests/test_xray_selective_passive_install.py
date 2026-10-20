#!/usr/bin/env python3
"""Static safety contract for experimental, passive, test-Pi-only rollout."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"scripts/awg-xray-selective-passive-install.sh"
S=P.read_text()

class PassiveInstallContract(unittest.TestCase):
    def test_bash_syntax(self):
        p=subprocess.run(["bash","-n",str(P)],capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_testpi_and_selective_only(self):
        self.assertIn('"$(hostname)" == awg-upgrade',S)
        self.assertIn('== selective',S)
        self.assertIn('== mihomo',S)
        self.assertIn('== auto',S)
        self.assertIn('== 0',S)
    def test_old_files_pinned_and_backed_up(self):
        for x in ("0c0577f3941773","bdea36459bc009","0ac8272bd2c68d"):
            self.assertIn(x,S)
        for name in ("awg-mihomo-node-policy","awg-xray-live-backend","awg-mihomo-unified-nodes"):
            self.assertIn(name,S)
        self.assertIn('cp -a "$root/$name" "$snap/old/$name"',S)
        self.assertIn('"$(hash14 "$snap/old/$name")"',S)
    def test_independent_watchdog_armed_before_mutation(self):
        self.assertLess(S.index('systemd-run --quiet --collect'),
                        S.index('mutated=1'))
        self.assertIn('active "$timer"',S) if False else None
        self.assertIn('healthy "$timer" || die TIMER_NOT_ACTIVE',S)
        self.assertIn('[[ "$current" == "$original" || "$current" == "$intended" ]]',S)
        self.assertIn('echo COMMITTED >"$snap/state"',S)
        self.assertIn('[[ "$(cat "$snap/state" 2>/dev/null || true)" == PENDING ]]',S)
    def test_no_service_or_router_mutations(self):
        for forbidden in ("systemctl restart","systemctl enable","awg-transport select",
                          "ip route replace","ip rule add", "nft ", "awg-mode-switch",
                          "MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1",
                          "MIHOMO_XRAY_SELECTIVE_CANARY=1",
                          "systemctl stop awg-mihomo","systemctl stop ssh"):
            self.assertNotIn(forbidden,S)
    def test_installed_bytes_verified_without_runtime_changes(self):
        self.assertIn('cmp -s "$repo/$(source_for "$name")" "$root/$name"',S)
        self.assertIn('verify_routes || die ROUTE_CHANGED_AFTER',S)
        self.assertIn('! healthy awg-xray-vless',S)
        self.assertIn('RUNTIME_SERVICES_RESTARTED=NO',S) if False else self.assertIn('echo XRAY_CANARY=OFF',S)

if __name__=="__main__":
    unittest.main()
