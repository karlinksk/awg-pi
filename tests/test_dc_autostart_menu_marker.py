#!/usr/bin/env python3
"""Desktop Commander autostart indicators: rootless state/transition coverage."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MENU = (Path(__file__).resolve().parents[1] / "src/awg-menu").read_text()

def function(name):
    start = MENU.index(name + "(){")
    end = MENU.index("\n}\n", start) + 2
    return MENU[start:end] + "\n"

MOCK = r'''
set -Eeuo pipefail
BACKTITLE=TEST
SUDO_USER=dc-test
systemctl(){
  printf 'SYSTEMCTL:%s\n' "$*" >> "$TRACE"
  if [[ "$1" == is-enabled && "$2" == --quiet &&
        "$3" == "awg-dc-remote@dc-test.service" ]]; then
    [[ "$(cat "$STATE")" == enabled ]]
  else
    return 90
  fi
}
dialog(){
  printf 'MENU:%s\n' "$*" >> "$TRACE"
  if [[ ! -f "$ONCE" ]]; then
    touch "$ONCE"
    printf '%s\n' "$CHOICE" >&2
  else
    printf '0\n' >&2
  fi
}
confirm(){ printf 'CONFIRM:%s\n' "$*" >> "$TRACE"; return "$CONFIRM_RC"; }
capture(){
  printf 'CAPTURE:%s\n' "$*" >> "$TRACE"
  case "$2" in
    enable) echo enabled > "$STATE" ;;
    disable) echo disabled > "$STATE" ;;
  esac
}
input(){ return 1; }
id(){ return 0; }
msg(){ :; }
run_interactive(){ :; }
''' + function("awg_option_label") + function("desktop_commander_menu") + "\ndesktop_commander_menu\n"

class DCAutostartMarker(unittest.TestCase):
    def run_menu(self, initial, choice="0", confirmation=0):
        with tempfile.TemporaryDirectory(prefix="awg-dc-marker-") as td:
            root = Path(td)
            state, trace = root / "state", root / "trace"
            state.write_text(initial + "\n")
            env = {**os.environ, "STATE": str(state), "TRACE": str(trace),
                   "ONCE": str(root / "once"), "CHOICE": choice,
                   "CONFIRM_RC": str(confirmation)}
            result = subprocess.run(["bash", "-c", MOCK], env=env,
                                    capture_output=True, text=True, timeout=5)
            calls = trace.read_text().splitlines() if trace.exists() else []
            return result, calls, state.read_text().strip()

    def marked(self, screen, enabled):
        if enabled:
            self.assertIn("3 Включить автозапуск ✓", screen)
            self.assertNotIn("4 Выключить автозапуск ✓", screen)
        else:
            self.assertIn("4 Выключить автозапуск ✓", screen)
            self.assertNotIn("3 Включить автозапуск ✓", screen)

    def test_enabled_marks_three_only_without_writes(self):
        p, calls, state = self.run_menu("enabled")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(state, "enabled")
        self.marked(next(x for x in calls if x.startswith("MENU:")), True)
        self.assertEqual([c for c in calls if c.startswith("SYSTEMCTL:")],
                         ["SYSTEMCTL:is-enabled --quiet awg-dc-remote@dc-test.service"])
        self.assertFalse(any(c.startswith("CAPTURE:") for c in calls))

    def test_disabled_marks_four_only_without_writes(self):
        p, calls, state = self.run_menu("disabled")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(state, "disabled")
        self.marked(next(x for x in calls if x.startswith("MENU:")), False)

    def test_enable_refreshes_marker_after_success(self):
        p, calls, state = self.run_menu("disabled", choice="3")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(state, "enabled")
        screens = [c for c in calls if c.startswith("MENU:")]
        self.assertEqual(len(screens), 2)
        self.marked(screens[0], False)
        self.marked(screens[1], True)
        self.assertIn("CAPTURE:/usr/local/bin/awg-dc enable dc-test", calls)

    def test_disable_refreshes_marker_after_success(self):
        p, calls, state = self.run_menu("enabled", choice="4")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(state, "disabled")
        screens = [c for c in calls if c.startswith("MENU:")]
        self.assertEqual(len(screens), 2)
        self.marked(screens[0], True)
        self.marked(screens[1], False)
        self.assertIn("CAPTURE:/usr/local/bin/awg-dc disable dc-test", calls)

    def test_cancellation_leaves_marker_and_service_unchanged(self):
        p, calls, state = self.run_menu("enabled", choice="4", confirmation=1)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(state, "enabled")
        screens = [c for c in calls if c.startswith("MENU:")]
        self.assertEqual(len(screens), 2)
        self.marked(screens[1], True)
        self.assertFalse(any(c.startswith("CAPTURE:") for c in calls))

    def test_read_only_probe_and_existing_helper_contract(self):
        source = function("desktop_commander_menu")
        self.assertIn('systemctl is-enabled --quiet "awg-dc-remote@' +
                      '$' + '{dc_user}.service"', source)
        self.assertNotIn("systemctl is-active", source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("systemctl disable", source)

if __name__ == "__main__":
    unittest.main()
