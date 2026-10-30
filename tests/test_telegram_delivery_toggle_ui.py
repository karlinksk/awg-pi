#!/usr/bin/env python3
"""Telegram delivery toggling must not open per-systemctl result boxes.

All Bash service and menu invocations are mocked: these tests do not touch
systemd, Telegram credentials, Raspberry Pi settings or network routes.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENU = (ROOT / "src/awg-menu").read_text()

def function(name):
    start = MENU.index(name + "(){")
    end = MENU.index("\n}\n", start) + 2
    return MENU[start:end] + "\n"

MOCK = r'''
systemctl(){
  printf '%s\n' "$*" >> "$COMMANDS"
  # These are simulated systemctl messages that must be hidden from the UI.
  printf "Removed '/etc/systemd/system/timers.target.wants/awg-notify-flush.timer'.\n"
  printf 'technical systemctl warning\n' >&2
  [[ "$*" != "$FAIL" ]]
}
notify_sync_daily_schedule(){
  printf 'daily:%s\n' "$1" >> "$COMMANDS"
  echo 'systemctl daily technical log'
  [[ "$FAIL" != "daily" ]]
}
msg(){
  printf 'TITLE:%s\nTEXT:%s\n' "$1" "$2" >> "$ALERTS"
}
''' + function("notify_apply_delivery") + r'''
notify_apply_delivery "$DESIRED" "$DAILY_PREF"
'''

class DeliveryToggleUX(unittest.TestCase):
    def perform(self, desired, daily="", fail=""):
        with tempfile.TemporaryDirectory(prefix="awg-tg-toggle-") as temp:
            path = Path(temp)
            env = {
                **os.environ,
                "COMMANDS": str(path / "commands"),
                "ALERTS": str(path / "alerts"),
                "DESIRED": desired,
                "DAILY_PREF": daily,
                "FAIL": fail,
            }
            completed = subprocess.run(
                ["bash", "-Eeuo", "pipefail", "-c", MOCK],
                env=env, capture_output=True, text=True, timeout=5)
            commands = (path / "commands").read_text().splitlines() \
                if (path / "commands").exists() else []
            alerts = (path / "alerts").read_text() \
                if (path / "alerts").exists() else ""
            return completed, commands, alerts

    def test_disable_runs_every_existing_unit_without_success_dialog(self):
        result, commands, alerts = self.perform("off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, [
            "disable --now awg-notify-flush.timer",
            "disable --now awg-notify-watch.timer",
            "disable --now awg-notify-daily.timer",
            "disable --now awg-notify-boot.service",
        ])
        self.assertEqual(alerts, "")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_enable_selected_daily_runs_existing_schedule_without_dialog(self):
        result, commands, alerts = self.perform("on", "DAILY_REPORT")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, [
            "enable --now awg-notify-flush.timer",
            "enable --now awg-notify-watch.timer",
            "enable awg-notify-boot.service",
            "daily:DAILY_REPORT",
        ])
        self.assertEqual(alerts, "")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_enable_without_daily_preserves_deselection(self):
        result, commands, alerts = self.perform("on")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[-1], "daily:")
        self.assertEqual(alerts, "")

    def test_single_failure_still_attempts_remaining_units_and_warns(self):
        fail = "disable --now awg-notify-flush.timer"
        result, commands, alerts = self.perform("off", fail=fail)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(commands), 4)
        self.assertIn("TITLE:Доставка Telegram", alerts)
        self.assertIn("Не удалось изменить настройки: доставки", alerts)
        self.assertNotIn("Removed '", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_daily_failure_is_not_masked(self):
        result, commands, alerts = self.perform("on", "DAILY_REPORT", "daily")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(commands), 4)
        self.assertIn("ежедневной сводки", alerts)
        self.assertEqual(result.stdout, "")

    def test_menu_confirmation_preserved_without_capture_ui(self):
        section = function("notify_menu")
        self.assertIn('confirm "Доставка Telegram"', section)
        self.assertIn('notify_apply_delivery off ""', section)
        self.assertIn('notify_apply_delivery on "DAILY_REPORT"', section)
        self.assertIn('notify_apply_delivery on ""', section)
        self.assertNotIn('capture systemctl', section)
        self.assertNotIn('title="Telegram — выключение доставки"', section)
        self.assertNotIn('title="Telegram — включение доставки"', section)
        self.assertIn('systemctl is-enabled --quiet awg-notify-flush.timer', section)
        self.assertIn('current="$(/usr/local/sbin/awg-notify status', section)
        self.assertNotIn("capture systemctl", function("notify_apply_delivery"))
        self.assertIn(">/dev/null 2>&1", function("notify_apply_delivery"))

    def test_unknown_action_is_refused_without_mutation(self):
        result, commands, alerts = self.perform("invalid")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(commands, [])
        self.assertEqual(alerts, "")

if __name__ == "__main__":
    unittest.main()
