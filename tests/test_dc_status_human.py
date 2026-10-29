#!/usr/bin/env python3
"""Human-readable Desktop Commander status; rootless, no device or VPN changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MENU = (Path(__file__).resolve().parents[1] / "src/awg-menu").read_text()

def function(name):
    a = MENU.index(name + "(){")
    b = MENU.index("\n}\n", a) + 2
    return MENU[a:b] + "\n"

STATUS = """AWG_DC_USER=karlinks
AWG_DC_SYSTEM_NODE=v22.16.0
AWG_DC_NPM=READY
AWG_DC_SYSTEM_WEBSOCKET=AVAILABLE
AWG_DC_PAIRING=LOCAL_SESSION_PRESENT
AWG_DC_AUTOSTART=ENABLED
AWG_DC_AGENT_SERVICE=ACTIVE
AWG_DC_REMOTE_CONNECTIVITY=CHECK_DASHBOARD
"""

class HumanDesktopCommanderStatus(unittest.TestCase):
    def render(self, raw):
        script = function("awg_dc_human_status") + \
            'awg_dc_human_status "$RAW"\n'
        return subprocess.run(
            ["bash", "-Eeuo", "pipefail", "-c", script],
            env={**os.environ, "RAW": raw}, capture_output=True,
            text=True, timeout=5,
        )

    def test_active_agent_is_not_misreported_as_connected(self):
        result = self.render(STATUS)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(
            lines[:2], [
                "Подключение: не подтверждено (проверить в панели Desktop Commander)",
                "Автозапуск: включён",
            ],
        )
        self.assertIn("Пользователь: karlinks", lines)
        self.assertIn("Авторизация устройства: сохранена на этом устройстве", lines)
        self.assertIn("Удалённый агент: работает", lines)
        self.assertIn("Версия Node.js: v22.16.0", lines)
        self.assertIn("Необходимые компоненты: установлены", lines)
        self.assertIn("Поддержка соединения: доступна", lines)
        self.assertIn("Работающий агент сам по себе не подтверждает подключение.", lines)
        self.assertNotIn("Результат: ВЫПОЛНЕНО", result.stdout)
        self.assertNotIn("AWG_DC_", result.stdout)

    def test_inactive_agent_and_disabled_autostart(self):
        raw = (STATUS.replace("AWG_DC_AUTOSTART=ENABLED", "AWG_DC_AUTOSTART=DISABLED")
                     .replace("AWG_DC_AGENT_SERVICE=ACTIVE", "AWG_DC_AGENT_SERVICE=INACTIVE"))
        result = self.render(raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("Подключение: не установлено (агент не запущен)", lines)
        self.assertIn("Автозапуск: выключен", lines)
        self.assertIn("Удалённый агент: не запущен", lines)

    def test_missing_pairing_not_shown_as_connected(self):
        result = self.render(STATUS.replace("LOCAL_SESSION_PRESENT", "NOT_VERIFIED"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Подключение: не настроено (требуется авторизация)", result.stdout)
        self.assertIn("Авторизация устройства: не подтверждена", result.stdout)

    def test_missing_dependencies_and_fallback_are_readable(self):
        raw = """AWG_DC_USER=karlinks
AWG_DC_BOOTSTRAP=MISSING_NODE18_OR_NPM
AWG_DC_SYSTEM_WEBSOCKET=NOT_AVAILABLE_ISOLATED_FALLBACK_REQUIRED
AWG_DC_PAIRING=NOT_VERIFIED
AWG_DC_AUTOSTART=DISABLED
AWG_DC_AGENT_SERVICE=INACTIVE
"""
        result = self.render(raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Необходимые компоненты: требуется установка", result.stdout)
        self.assertIn("Версия Node.js: не определена", result.stdout)
        self.assertIn("Поддержка соединения: используется дополнительный компонент", result.stdout)

    def test_unknown_fields_and_untrusted_values_are_not_exposed(self):
        raw = (STATUS.replace("AWG_DC_USER=karlinks", "AWG_DC_USER=\\033[31mBAD")
                     .replace("AWG_DC_SYSTEM_NODE=v22.16.0", "AWG_DC_SYSTEM_NODE=$(touch BAD)")
                     + "SECRET_ACCESS_TOKEN=never-print-this\n"
                     + "AWG_DC_REMOTE_CONNECTIVITY=CONNECTED\n")
        result = self.render(raw)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Пользователь: неизвестен", result.stdout)
        self.assertIn("Версия Node.js: не определена", result.stdout)
        self.assertNotIn("never-print-this", result.stdout)
        self.assertNotIn("touch BAD", result.stdout)
        self.assertNotIn("BAD", result.stdout)
        self.assertNotIn("Подключение: подключён", result.stdout)

    def test_error_view_is_human_and_no_old_result_prefix(self):
        body = function("desktop_commander_status_screen")
        self.assertIn("Подключение: не удалось проверить", body)
        self.assertIn("Автозапуск: не удалось проверить", body)
        self.assertIn('dialog --backtitle "$BACKTITLE"', body)
        self.assertNotIn('capture /usr/local/bin/awg-dc status', function("desktop_commander_menu"))
        self.assertIn('2) desktop_commander_status_screen "$dc_user" ;;',
                      function("desktop_commander_menu"))

    def test_status_screen_success_and_failure_do_not_show_raw_codes(self):
        fn = function("awg_dc_human_status") + function("desktop_commander_status_screen")
        with tempfile.TemporaryDirectory(prefix="dc-ui-status-test-") as td:
            file = Path(td) / "view"
            fake = Path(td) / "status-helper"
            fake.write_text("#!/bin/sh\nif [ \"$FAIL\" = 1 ]; then exit 2; fi\nprintf '%s\\n' \"$RAW\"\n")
            fake.chmod(0o700)
            mock = r'''
BACKTITLE=TEST
TMP="$OUTPUT"
dialog(){ cp "$TMP" "$CAPTURE"; }
'''
            # Only in the isolated test function, replace the absolute command.
            fn = fn.replace("/usr/local/bin/awg-dc status", str(fake) + " status")
            for fail in ("0", "1"):
                with self.subTest(fail=fail):
                    result = subprocess.run(
                        ["bash", "-Eeuo", "pipefail", "-c", mock + fn + '\ndesktop_commander_status_screen karlinks\n'],
                        env={**os.environ, "FAIL": fail, "RAW": STATUS, "OUTPUT": str(file),
                             "CAPTURE": str(Path(td) / "capture")},
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    content = (Path(td) / "capture").read_text()
                    self.assertTrue(content.startswith("Подключение: "))
                    self.assertIn("Автозапуск: ", content)
                    self.assertNotIn("AWG_DC_", content)
                    self.assertNotIn("Операция: Desktop Commander", content)
                    if fail == "1":
                        self.assertIn("не удалось проверить", content)
                    else:
                        self.assertIn("Пользователь: karlinks", content)

if __name__ == "__main__":
    unittest.main()
