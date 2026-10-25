"""Execute actual legacy timer preservation guards in the simplified installer."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'install.sh').read_text()
CAPTURE=SOURCE.split('UPGRADE_HOT_TIMER_ENABLEMENT=absent',1)[1].split('\nif (( UPGRADE_EXISTING == 1 )); then',1)[0]
CAPTURE='UPGRADE_HOT_TIMER_ENABLEMENT=absent'+CAPTURE
VERIFY='if [[ "$UPGRADE_HOT_TIMER_ENABLEMENT" != absent ]]; then'+SOURCE.split('if [[ "$UPGRADE_HOT_TIMER_ENABLEMENT" != absent ]]; then',1)[1].split('\n  fi',1)[0]+'\nfi\n'

class LegacyTimerPreservation(unittest.TestCase):
    def run_case(self,upgrade=True,present=True,enabled='disabled',runtime='inactive',
                 after_enabled=None,after_runtime=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);unit=root/'timer';log=root/'log'
            if present:unit.write_text('LEGACY OR CUSTOM UNIT\n')
            before=unit.read_bytes() if present else None
            script=r'''set -Eeuo pipefail
systemctl(){
 echo "$*" >> "$LOG"
 case "$1" in
 is-enabled) printf '%s\n' "$ENABLED" ;;
 is-active) printf '%s\n' "$RUNTIME" ;;
 *) exit 50 ;;
 esac
}
die(){ exit 29; }
'''+CAPTURE.replace('/etc/systemd/system/awg-mihomo-hot-pool.timer',str(unit))+r'''
ENABLED="$AFTER_ENABLED"
RUNTIME="$AFTER_RUNTIME"
'''+VERIFY
            r=subprocess.run(['bash','-c',script],text=True,capture_output=True,timeout=3,
              env=dict(os.environ,UPGRADE_EXISTING=str(int(upgrade)),LOG=str(log),
                       ENABLED=enabled,RUNTIME=runtime,
                       AFTER_ENABLED=enabled if after_enabled is None else after_enabled,
                       AFTER_RUNTIME=runtime if after_runtime is None else after_runtime))
            self.assertEqual(unit.read_bytes() if unit.exists() else None,before)
            calls=log.read_text().splitlines() if log.exists() else []
            self.assertTrue(all(c.startswith(('is-enabled ','is-active ')) for c in calls))
            return r,calls

    def test_fresh_install_does_not_manage_legacy_timer(self):
        r,c=self.run_case(upgrade=False)
        self.assertEqual((r.returncode,c),(0,[]))

    def test_missing_legacy_unit_stays_absent(self):
        r,c=self.run_case(present=False)
        self.assertEqual((r.returncode,c),(0,[]))

    def test_enabled_active_preserved(self):
        self.assertEqual(self.run_case(enabled='enabled',runtime='active')[0].returncode,0)

    def test_disabled_inactive_preserved(self):
        self.assertEqual(self.run_case()[0].returncode,0)

    def test_masked_custom_unit_is_not_replaced(self):
        self.assertEqual(self.run_case(enabled='masked')[0].returncode,0)

    def test_runtime_change_requires_rollback(self):
        self.assertEqual(self.run_case(after_runtime='active')[0].returncode,29)

    def test_enablement_change_requires_rollback(self):
        self.assertEqual(self.run_case(after_enabled='enabled')[0].returncode,29)

    def test_unreadable_enablement_refused(self):
        self.assertEqual(self.run_case(enabled='')[0].returncode,29)


if __name__=='__main__':unittest.main()
