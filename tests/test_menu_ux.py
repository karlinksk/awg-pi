#!/usr/bin/env python3
"""Rootless behavioral contract for Russian SSH UI; does not change VPN state."""
import fcntl
import os
from pathlib import Path
import pty
import re
import struct
import subprocess
import tempfile
import termios
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/awg-menu").read_text()


def body(name):
    start = SOURCE.index(name + "(){")
    end = SOURCE.index("\n}\n", start)
    return SOURCE[start:end + 2]


class MenuUX(unittest.TestCase):
    def test_fresh_install_neither_health_error_nor_missing_engine(self):
        with tempfile.TemporaryDirectory(prefix="awg-menu-clean-") as td:
            root = Path(td)
            for filename in ("awg", "mihomo", "traffic", "transport"):
                script = root / filename
                script.write_text("#!/bin/sh\n" + (
                    "echo unconfigured\n" if filename == "transport"
                    else "echo 'Сегодня: 0 | Месяц: 0'\n" if filename == "traffic"
                    else "exit 0\n"))
                script.chmod(0o700)
            code = body("quick_summary")
            code = code.replace("/usr/local/bin/mihomo", str(root / "mihomo"))
            code = code.replace("/etc/amnezia/amneziawg/awg0.conf", str(root / "awg0.conf"))
            code = code.replace("/etc/awg-pbr/transports/mihomo/node-name", str(root / "node-name"))
            shell = ("""
operating_mode_id(){ echo selective; }
operating_mode_label(){ echo 'Выборочный шлюз'; }
operating_mode_badge(){ echo SELECTIVE; }
current_timezone(){ echo UTC; }
cpu_temperature(){ echo '42°C'; }
system_uptime(){ echo '1ч'; }
memory_summary(){ echo '100/400 MiB'; }
disk_summary(){ echo '1/10 GiB'; }
hot_pool_summary(){ echo 'ожидает подписку'; }
ip(){ return 1; }
systemctl(){ return 1; }
command(){ if [[ "$1" == -v && "$2" == awg ]]; then return 0; fi; builtin command "$@"; }
""" + code + f"""
AWG_TRANSPORT='{root / "transport"}'
AWG_TRAFFIC='{root / "traffic"}'
PI_IP='0.0.0.0'
ROUTER_IP='0.0.0.0'
quick_summary
""")
            r = subprocess.run(["bash", "-c", shell], text=True,
                               capture_output=True, timeout=8)
            self.assertEqual(r.returncode, 0, r.stderr)
            for required in (
                "VPN: ожидает настройки",
                "AWG: не настроен",
                "Mihomo: не настроен",
                "ГОРЯЧИЙ РЕЗЕРВ: ожидает подписку",
                "DIRECT (FAIL-OPEN)",
            ):
                self.assertIn(required, r.stdout)
            self.assertNotIn("VPN: сбой", r.stdout)
            self.assertNotIn("AWG: неисправен", r.stdout)

    def run_dialog(self, rows, cols, prompt):
        with tempfile.TemporaryDirectory(prefix="awg-menu-tty-") as td:
            root = Path(td)
            mock = root / "dialog"
            out = root / "args"
            mock.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$AWG_MENU_CAPTURE"\n')
            mock.chmod(0o700)
            master, slave = pty.openpty()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
                # Provide a controlling terminal for stty size </dev/tty.
                def term_session():
                    os.setsid()
                    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                shell = body("dialog") + "\n" + (
                    'dialog --backtitle test --title test --item-help --menu "$PROMPT" '
                    '31 116 14 "1" "Первый пункт" "Русская подсказка"'
                )
                env = dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                           AWG_MENU_CAPTURE=str(out), PROMPT=prompt)
                proc = subprocess.run(["bash", "-c", shell], stdin=slave,
                                      stdout=slave, stderr=slave, env=env,
                                      preexec_fn=term_session, timeout=5)
                args = [chunk.decode() for chunk in out.read_bytes().split(b"\x00") if chunk] if out.exists() else []
                return proc.returncode, args
            finally:
                os.close(slave)
                os.close(master)

    def test_long_dashboard_fits_80_by_24(self):
        rc, args = self.run_dialog(24, 80, "\n".join(["Строка состояния"] * 11))
        self.assertEqual(rc, 0)
        at = args.index("--menu")
        self.assertLessEqual(int(args[at + 2]), 22)
        self.assertLessEqual(int(args[at + 3]), 78)
        self.assertLessEqual(int(args[at + 4]), 6)
        self.assertGreaterEqual(int(args[at + 4]), 3)

    def test_full_size_dialog_is_not_shrunk(self):
        rc, args = self.run_dialog(40, 140, "Выберите действие.")
        self.assertEqual(rc, 0)
        at = args.index("--menu")
        self.assertEqual(args[at + 2:at + 5], ["31", "116", "14"])

    def test_too_small_terminal_is_rejected_without_running_dialog(self):
        rc, args = self.run_dialog(18, 64, "Введите настройку.")
        self.assertNotEqual(rc, 0)
        self.assertEqual(args, [])

    def test_explicit_outcome_and_safe_reentry(self):
        with tempfile.TemporaryDirectory(prefix="awg-menu-result-") as td:
            root = Path(td)
            log = root / "operation"
            log.write_text("Завершился этап проверки.\n")
            mock = root / "dialog"
            mock.write_text("#!/bin/sh\nexit 0\n")
            mock.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"])
            shell = body("show_operation_result") + f"""
TMP='{log}'
BACKTITLE=Тест
show_operation_result 7 'Проверка подписки'
"""
            proc = subprocess.run(["bash", "-c", shell], env=env,
                                  capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(log.read_text().startswith("Результат: ОШИБКА (код 7)"))
            self.assertIn("Завершился этап проверки.", log.read_text())
        for action in ("gateway", "all"):
            self.assertIn(f'if capture "$AWG_UPDATE" --yes {action}; then', SOURCE)
            self.assertNotIn(f'capture "$AWG_UPDATE" --yes {action} || true', SOURCE)

    def test_initial_setup_is_native_dialog_not_hidden_ssh(self):
        fn = SOURCE[SOURCE.index("first_transport_setup(){"):
                    SOURCE.index("secondary_transport_setup(){")]
        self.assertIn('Первичная настройка VPN', fn)
        self.assertIn('mihomo_initial_setup_flow normal', fn)
        self.assertIn('awg_config_menu', fn)
        self.assertIn('Настроить позже', fn)
        self.assertNotIn('run_interactive', fn)
        self.assertIn('capture "$AWG_FIRST_RUN" awg-file "$PASTE_TMP"', SOURCE)
        self.assertIn('capture "$AWG_FIRST_RUN" awg-file "$path"', SOURCE)
        self.assertIn('run_with_progress "$title" "$MIHOMO_CONFIGURE" node prepare', SOURCE)
        self.assertIn('run_with_progress "$title" "$MIHOMO_CONFIGURE" provider candidate prepare', SOURCE)

    def test_evidence_semantics_and_russian_auto(self):
        self.assertIn('hot_pool_summary(){', SOURCE)
        self.assertIn('awg-mihomo-hot-pool status', SOURCE)
        self.assertIn('if [[ "$transport" == "не настроен" ]]', SOURCE)
        self.assertIn('Смена узлов Mihomo управляется отдельной политикой', SOURCE)
        self.assertIn('только если профиль AWG настроен и работоспособен', SOURCE)
        self.assertNotIn('узел и страна Mihomo не переключаются автоматически', SOURCE)


if __name__ == "__main__":
    unittest.main()
