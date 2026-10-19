#!/usr/bin/env python3
"""Offline installer-first Hot Pool delivery tests (no real services/files touched).

Execute only the guarded installer block with mocked systemctl/fetch helpers
inside a private temporary directory; cover active/disabled timer, fresh,
race, custom unit, partial failure and rollback preservation.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "install.sh").read_text(encoding="utf-8")
START = SOURCE.index("# Hot Pool is SHADOW_ONLY. Fetch verified components")
END_MARK = "unset _hot_stage _hot_targets _hot_names _hot_timer_running _hot_failed"
END = SOURCE.index("ok \"Hot Pool continuity SHADOW_ONLY:", START)
END = SOURCE.index("\n", END)
BLOCK = SOURCE[START:END]
assert "install_project_python_helper extras/mihomo-hot-pool-shadow/awg-mihomo-hot-pool.py" in BLOCK
assert "install_project_helper extras/mihomo-hot-pool-shadow/awg-mihomo-hot-continuity-run" in BLOCK
assert "install_project_unit extras/mihomo-hot-pool-shadow/awg-mihomo-hot-pool.timer" in BLOCK
assert "systemctl stop awg-mihomo-hot-pool.timer" in BLOCK
assert "systemctl start awg-mihomo-hot-pool.timer" in BLOCK
assert "cp -p --" in BLOCK
assert "systemctl daemon-reload" in BLOCK
assert "HOT_POOL_READY=" not in BLOCK  # never mint eligibility or mutate READY

class InstallerHotPoolDelivery(unittest.TestCase):
    def run_case(self, *, present=True, timer=True, busy=False,
                 race=False, custom=False, fail_at=0, stop_fail=False):
        with tempfile.TemporaryDirectory(prefix="awg-hot-installer-") as directory:
            base=Path(directory)
            sbin=base/"sbin";units=base/"units"
            sbin.mkdir();units.mkdir()
            destinations=[
                sbin/"awg-mihomo-hot-pool",
                sbin/"awg-mihomo-hot-service-scan",
                sbin/"awg-hot-pool-continuity.py",
                sbin/"awg-mihomo-hot-continuity-run",
                units/"awg-mihomo-hot-pool.service",
                units/"awg-mihomo-hot-pool.timer"
            ]
            if present:
                for i,dest in enumerate(destinations):
                    data=(("ExecStart="+str(sbin/"awg-mihomo-hot-continuity-run")+"\n") if i==4 and not custom else "CUSTOM UNIT\n" if i==4 else "OLD FILE "+str(i))
                    dest.write_text(data)
            before=[d.read_bytes() if d.exists() else None for d in destinations]
            code=BLOCK
            for original,modified in [
                ("/run/awg-hot-pool-install.",str(base/"stage.")),
                ("/usr/local/sbin/",str(sbin)+"/"),
                ("/etc/systemd/system/",str(units)+"/"),
                ("/var/lib/awg-pbr/hot-pool/continuity",str(base/"private-vault")),
                ("/run/awg-pbr/hot-pool/continuity",str(base/"private-union"))
            ]:
                code=code.replace(original,modified)
            # Replace the expected ExecStart path with the test sandbox form
            # so the real custom-unit check is still exercised.
            prefix="""set -Eeuo pipefail
MOCK_TIMER_RUNNING="${MOCK_TIMER_RUNNING:-0}"
MOCK_SERVICE_RUNNING="${MOCK_SERVICE_RUNNING:-0}"
MOCK_STOP_COUNT=0
MOCK_INSTALL_COUNT=0
systemctl(){
  case "$1" in
    is-active)
      if [[ "${3:-}" == awg-mihomo-hot-pool.service ]]; then
        [[ "$MOCK_SERVICE_RUNNING" == 1 ]]
      else
        [[ "$MOCK_TIMER_RUNNING" == 1 ]]
      fi ;;
    stop)
      echo STOP >> "$MOCK_LOG"
      [[ "$MOCK_STOP_FAIL" == 0 ]] || return 1
      MOCK_TIMER_RUNNING=0
      if [[ "$MOCK_RACE" == 1 ]]; then MOCK_SERVICE_RUNNING=1; fi ;;
    start) echo START >> "$MOCK_LOG"; MOCK_TIMER_RUNNING=1 ;;
    daemon-reload) echo RELOAD >> "$MOCK_LOG" ;;
    *) return 20 ;;
  esac
}
install_project_python_helper(){ printf 'CANDIDATE:%s\\n' "$1" > "$2"; }
install_project_helper(){ printf 'CANDIDATE:%s\\n' "$1" > "$2"; }
install_project_unit(){ printf 'CANDIDATE:%s\\n' "$1" > "$2"; }
install(){
  if [[ "$1" == -d ]]; then
    for p in "${@: -2}"; do mkdir -p "$p"; done
    return 0
  fi
  MOCK_INSTALL_COUNT=$((MOCK_INSTALL_COUNT+1))
  if [[ "$MOCK_INSTALL_COUNT" == "$MOCK_FAIL_AT" ]]; then return 1; fi
  command install "$@"
}
die(){ echo "MOCK_DIE:$*" >&2; exit 29; }
ok(){ echo "MOCK_OK:$*" >> "$MOCK_LOG"; }
""" + "\n" + code + "\n"
            # Path-safe validation: only private temp paths in operations.
            env=dict(os.environ, MOCK_TIMER_RUNNING=str(int(timer)),
                     MOCK_SERVICE_RUNNING=str(int(busy)),
                     MOCK_RACE=str(int(race)),MOCK_STOP_FAIL=str(int(stop_fail)),
                     MOCK_FAIL_AT=str(fail_at),MOCK_LOG=str(base/"systemctl.log"))
            result=subprocess.run(["bash","-c",prefix],text=True,capture_output=True,env=env,timeout=12)
            after=[d.read_bytes() if d.exists() else None for d in destinations]
            events=(base/"systemctl.log").read_text().splitlines() if (base/"systemctl.log").exists() else []
            return result, before, after, events

    def test_clean_install_populates_all_components(self):
        r,b,a,ev=self.run_case(present=False,timer=False)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(sum(x is not None for x in a),6)
        self.assertNotIn("STOP",ev);self.assertNotIn("START",ev)
        self.assertIn("RELOAD",ev)

    def test_enabled_idle_timer_receives_upgrade_and_resumes(self):
        r,b,a,ev=self.run_case(timer=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotEqual(a,b)
        self.assertEqual(sum(x.startswith(b"CANDIDATE:") for x in a),6)
        self.assertEqual(ev.count("STOP"),1);self.assertEqual(ev.count("START"),1)

    def test_disabled_timer_upgrade_does_not_enable(self):
        r,b,a,ev=self.run_case(timer=False)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotEqual(a,b)
        self.assertNotIn("START",ev);self.assertNotIn("STOP",ev)

    def test_active_scan_blocks_without_modifying_files(self):
        r,b,a,ev=self.run_case(busy=True,timer=True)
        self.assertEqual(r.returncode,29)
        self.assertEqual(a,b)
        self.assertNotIn("STOP",ev)

    def test_timer_race_blocks_and_restores_running_state(self):
        r,b,a,ev=self.run_case(race=True,timer=True)
        self.assertEqual(r.returncode,29)
        self.assertEqual(a,b)
        self.assertEqual(ev,["STOP","START"])

    def test_partial_install_failure_rolls_back_all(self):
        r,b,a,ev=self.run_case(timer=True,fail_at=3)
        self.assertEqual(r.returncode,29)
        self.assertEqual(a,b)
        self.assertEqual(ev.count("STOP"),1)
        self.assertEqual(ev.count("START"),1)
        self.assertIn("RELOAD",ev)

    def test_stop_timer_failure_preserves_every_file(self):
        r,b,a,ev=self.run_case(timer=True,stop_fail=True)
        self.assertEqual(r.returncode,29)
        self.assertEqual(a,b)
        self.assertEqual(ev.count("START"),0)

    def test_unknown_managed_unit_refused(self):
        r,b,a,ev=self.run_case(custom=True,timer=True)
        self.assertEqual(r.returncode,29)
        self.assertEqual(a,b)
        self.assertNotIn("STOP",ev)

if __name__=="__main__":
    unittest.main()
