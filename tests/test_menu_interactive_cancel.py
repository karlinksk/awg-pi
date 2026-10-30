#!/usr/bin/env python3
"""System/SSH handoff: Esc and Cancel return to the parent menu.

Runs with fake dialogs and fake route commands. No sudo, Pi/network writes,
VPN changes or terminal sessions.
"""
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


class SSHHandoffCancel(unittest.TestCase):
    def run_case(self, confirm_rc, from_system):
        with tempfile.TemporaryDirectory(prefix="awg-ssh-handoff-") as tmp:
            path = Path(tmp)
            trace = path / "trace"
            chosen = path / "chosen"
            route = path / "fake-route"
            route.write_text("#!/bin/sh\nprintf 'ROUTE_STARTED\\n' >> \"$TRACE\"\nexit 0\n")
            route.chmod(0o700)
            shell = r'''set -Eeuo pipefail
dialog(){
  printf 'DIALOG:%s\n' "$*" >> "$TRACE"
  if [[ " $* " == *" --yesno "* ]]; then
    return "$CONFIRM_RC"
  fi
  if [[ " $* " == *" --menu "* ]]; then
    # Real dialog emits the choice on stderr; the TUI swaps fds 3>&1 1>&2 2>&3.
    if [[ ! -e "$CHOSEN" ]]; then
      : > "$CHOSEN"
      printf '3\n' >&2
    else
      printf '0\n' >&2
    fi
    return 0
  fi
  return 91
}
clear(){ printf 'CLEAR\n' >> "$TRACE"; }
operating_mode_badge(){ echo TRANSIT; }
BACKTITLE="AWG Pi Gateway v1.3.0"
AWG_ROUTE="$FAKE_ROUTE"
''' + function("run_interactive") + "\n"
            if from_system:
                shell += function("system_menu") + "\nsystem_menu\n"
            else:
                shell += 'run_interactive "Перенастройка сети" "$AWG_ROUTE" network reconfigure\n'
            result = subprocess.run(
                ["bash", "-c", shell],
                input="\n", text=True, capture_output=True, timeout=5,
                env={**os.environ, "TRACE": str(trace), "CHOSEN": str(chosen),
                     "FAKE_ROUTE": str(route), "CONFIRM_RC": str(confirm_rc)}
            )
            return result, trace.read_text() if trace.exists() else ""

    def test_cancel_button_returns_to_system_without_network_operation(self):
        result, trace = self.run_case(1, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(trace.count("DIALOG:"), 3)
        self.assertEqual(trace.count(" --menu "), 2)
        self.assertEqual(trace.count(" --yesno "), 1)
        self.assertIn('--yes-label ОК --no-label Отмена', trace)
        self.assertNotIn("ROUTE_STARTED", trace)
        self.assertNotIn("CLEAR", trace)

    def test_escape_returns_to_system_without_exiting_ssh_menu(self):
        result, trace = self.run_case(255, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(trace.count(" --menu "), 2)
        self.assertEqual(trace.count(" --yesno "), 1)
        self.assertNotIn("ROUTE_STARTED", trace)

    def test_ok_starts_interactive_operation_and_returns_cleanly(self):
        result, trace = self.run_case(0, False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(trace.count(" --yesno "), 1)
        self.assertIn("ROUTE_STARTED", trace)
        self.assertIn("CLEAR", trace)
        self.assertIn("Операция завершена.", result.stdout)

    def test_all_interactive_callers_share_the_guarded_handoff(self):
        self.assertIn('run_interactive "Перенастройка сети"', function("system_menu"))
        for title in ("Настройка Telegram-бота",
                      "Проверка отправки Telegram",
                      "Подготовка Desktop Commander",
                      "Авторизация Desktop Commander"):
            self.assertIn('run_interactive "' + title + '"', MENU)
        handoff = function("run_interactive")
        self.assertIn('--yes-label "ОК" --no-label "Отмена"', handoff)
        self.assertIn('if ! dialog', handoff)
        self.assertLess(handoff.index("return 0"), handoff.index("  clear"))
        self.assertNotIn('msg "Переход в SSH-терминал"', handoff)


if __name__ == "__main__":
    unittest.main()
