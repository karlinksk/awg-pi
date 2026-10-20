#!/usr/bin/env python3
"""Passive Xray one-file incremental patch safety contract (rootless/static)."""
from pathlib import Path
import hashlib
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"scripts/awg-xray-socks-warmup-passive-install.sh"
BACKEND=ROOT/"src/awg-xray-live-backend.py"
S=PATCH.read_text()
class WarmupPassiveInstaller(unittest.TestCase):
    def test_shell_syntax(self):
        p=subprocess.run(["bash","-n",str(PATCH)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_pinned_source(self):
        self.assertIn("NEW="+hashlib.sha256(BACKEND.read_bytes()).hexdigest(),S)
        self.assertIn("OLD=ee60c9736c162475923d580d88e7b10ae95db2020abb74b2d1887ef973c889cc",S)
        self.assertIn('[[ "$(hash "$TARGET")" == "$OLD" ]]',S)
        self.assertIn('[[ "$(hash "$SOURCE")" == "$NEW" ]]',S)
        self.assertIn('BACKUP_INTEGRITY',S)
    def test_testpi_awg_preconditions(self):
        for needle in ["hostname", "awg-upgrade", "NOT_SELECTIVE",
                       "AWG_NOT_SELECTED", "AWG_UNHEALTHY",
                       "REQUIRED_SERVICE_DOWN_", "CANARY_LIVE",
                       "XRAY_SELECTED", "XRAY_BOOT_BRIDGE",
                       "ACTIVE_OR_STALE_XRAY_WATCHDOG",
                       "AWG_ROUTE_", "AWG_POST_ROUTE_"]:
            self.assertIn(needle,S)
    def test_independent_rollback_before_replace(self):
        armed=S.index("systemd-run --quiet --collect")
        mutation=S.index('mv -f -- "$TARGET.new.$$" "$TARGET"')
        validate=S.index('[[ "$(hash "$TARGET")" == "$NEW" ]]')
        disarm=S.index('systemctl stop "$TIMER" >/dev/null ||')
        self.assertLess(armed,mutation)
        self.assertLess(mutation,validate)
        self.assertLess(validate,disarm)
        self.assertIn("XRAY_ROLLBACK=PASS",S)
        self.assertIn("FOREIGN_FILE_REFUSED",S)
    def test_only_passive_single_file_install(self):
        self.assertNotIn("systemctl restart awg-mihomo",S)
        self.assertNotIn("systemctl start awg-xray",S)
        self.assertNotIn("awg-transport select mihomo",S)
        self.assertNotIn("awg-transport select awg",S)
        self.assertNotIn("awg-pbr-failopen",S)
        self.assertNotIn("awg-transit-routing",S)
        self.assertIn('echo XRAY_EXPERIMENT=NOT_ACTIVATED',S)
if __name__=="__main__":unittest.main()
