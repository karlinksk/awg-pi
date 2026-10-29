#!/usr/bin/env python3
"""Compact timezone menu: single action + Back, current zone in heading.

The tests stub all interactive and system commands. They never call the host
timedatectl or modify the real timezone, VPN, router, or SSH session.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENU = (ROOT / "src/awg-menu").read_text()


def function(name):
    a = MENU.index(name + "(){")
    b = MENU.index("\n}\n", a) + 2
    return MENU[a:b] + "\n"


class CompactTimezoneMenu(unittest.TestCase):
    def run_case(self, first_choice="0", *, confirm_rc=0, set_rc=0):
        with tempfile.TemporaryDirectory(prefix="awg-tz-menu-") as td:
            root = Path(td)
            state = root / "timezone"
            state.write_text("Asia/Novosibirsk\n")
            trace = root / "calls"
            selections = root / "selections"
            shell = r'''
set -Eeuo pipefail
BACKTITLE=TEST
current_timezone(){ cat "$TZ_STATE"; }
dialog(){
  printf 'DIALOG:%s\n' "$*" >> "$TRACE"
  if [[ ! -f "$SELECTIONS" ]]; then
    : > "$SELECTIONS"
    printf '%s\n' "$FIRST_CHOICE" >&2
  else
    printf '%s\n' 0 >&2
  fi
}
select_timezone(){ printf 'SELECT:%s\n' "$1" >> "$TRACE"; printf 'Europe/Amsterdam\n'; }
confirm(){ printf 'CONFIRM:%s\n' "$*" >> "$TRACE"; return "$CONFIRM_RC"; }
timedatectl(){
  printf 'TIMECTL:%s\n' "$*" >> "$TRACE"
  if [[ "$SET_RC" != 0 ]]; then return "$SET_RC"; fi
  if [[ "$1" == set-timezone ]]; then printf '%s\n' "$2" > "$TZ_STATE"; fi
}
msg(){ printf 'MESSAGE:%s\n' "$*" >> "$TRACE"; }
''' + function("timezone_menu") + "\ntimezone_menu\n"
            env = {
                **os.environ,
                "TZ_STATE": str(state), "TRACE": str(trace),
                "SELECTIONS": str(selections),
                "FIRST_CHOICE": str(first_choice),
                "CONFIRM_RC": str(confirm_rc),
                "SET_RC": str(set_rc),
            }
            proc = subprocess.run(
                ["bash", "-c", shell], capture_output=True, text=True,
                timeout=5, env=env,
            )
            return proc, trace.read_text().splitlines(), state.read_text().strip()

    def test_single_action_and_back_with_only_header_status(self):
        proc, calls, zone = self.run_case()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(zone, "Asia/Novosibirsk")
        self.assertEqual(len(calls), 1)
        screen = calls[0]
        self.assertIn("Текущий часовой пояс: Asia/Novosibirsk", screen)
        self.assertIn('1 Изменить часовой пояс', screen)
        self.assertIn('0 Назад', screen)
        self.assertNotIn("Показать текущий часовой пояс", screen)
        self.assertNotIn("Показать список часовых поясов", screen)
        self.assertNotIn("TIMECTL:", screen)

    def test_change_keeps_original_selection_and_confirmation(self):
        proc, calls, zone = self.run_case("1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(zone, "Europe/Amsterdam")
        self.assertIn("SELECT:Asia/Novosibirsk", calls)
        self.assertTrue(any(x.startswith("CONFIRM:") for x in calls))
        self.assertIn("TIMECTL:set-timezone Europe/Amsterdam", calls)
        self.assertTrue(any("MESSAGE:Часовой пояс Часовой пояс установлен" in x for x in calls))
        screens = [x for x in calls if x.startswith("DIALOG:")]
        self.assertEqual(len(screens), 2)
        self.assertIn("Текущий часовой пояс: Europe/Amsterdam", screens[1])

    def test_cancelled_change_does_not_set_system_time(self):
        proc, calls, zone = self.run_case("1", confirm_rc=1)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(zone, "Asia/Novosibirsk")
        self.assertTrue(any(x.startswith("CONFIRM:") for x in calls))
        self.assertFalse(any("TIMECTL:" in x for x in calls))

    def test_escape_returns_without_mutation(self):
        # In dialog, Esc is nonzero. The real menu's command substitution
        # uses || return 0, tested separately by checking the source guard.
        body = function("timezone_menu")
        self.assertIn('3>&1 1>&2 2>&3)" || return 0', body)
        self.assertIn('zone="$(select_timezone "$current")" || continue', body)
        self.assertIn('confirm "Часовой пояс"', body)
        self.assertNotIn("capture timedatectl list-timezones", body)
        self.assertEqual(body.count('1 "Изменить часовой пояс"'), 1)
        self.assertEqual(body.count('0 "Назад"'), 1)


if __name__ == "__main__":
    unittest.main()
