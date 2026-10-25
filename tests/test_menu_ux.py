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
hot_pool_summary(){ echo 'EXCLUDED_HOT_POOL_CALLED' >&2; }
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
                "AWG: не настроено",
                "Mihomo: не настроено",
                "DIRECT (FAIL-OPEN)",
            ):
                self.assertIn(required, r.stdout)
            self.assertNotIn("ГОРЯЧИЙ РЕЗЕРВ", r.stdout)
            self.assertNotIn("EXCLUDED_HOT_POOL_CALLED", r.stderr)
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
        # Synthetic test has one menu item; no need for fake spacer rows.
        self.assertEqual(int(args[at + 4]), 1)

    def test_menu_fits_real_71_by_33_ssh(self):
        rc, args = self.run_dialog(33, 71, "Выберите узел.")
        self.assertEqual(rc, 0)
        at = args.index("--menu")
        self.assertEqual(args[at + 2:at + 4], ["12", "69"])
        self.assertEqual(args[at + 4], "1")

    def test_sparse_menu_centers_compact_dialog(self):
        rc, args = self.run_dialog(40, 140, "Выберите действие.")
        self.assertEqual(rc, 0)
        at = args.index("--menu")
        self.assertEqual(args[at + 2:at + 5], ["12", "116", "1"])

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
            shell = body("awg_readable_status_text") + "\n" + body("show_operation_result") + f"""
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

    def test_fresh_install_onboarding_is_direct_and_installer_first(self):
        vpn=body("vpn_menu")
        awg=body("awg_config_menu")
        mihomo=body("mihomo_replace_subscription")
        self.assertNotIn("Добавить / настроить транспорт",vpn)
        self.assertNotIn("secondary_transport_setup",vpn)
        self.assertNotIn("first_transport_setup(){",SOURCE)
        self.assertIn('3 "Конфигурация AmneziaWG"',vpn)
        self.assertIn('4 "Mihomo"',vpn)
        self.assertIn('4 "Конфигурация AmneziaWG"',vpn)
        self.assertIn('5 "Mihomo"',vpn)
        self.assertIn('capture "$AWG_FIRST_RUN" awg-file "$PASTE_TMP"',SOURCE)
        self.assertIn('capture "$AWG_FIRST_RUN" awg-file "$path"',SOURCE)
        self.assertIn("mihomo_initial_setup_flow secondary",mihomo)
        self.assertIn("mihomo_initial_setup_flow(){",SOURCE)
        self.assertIn('run_with_progress "$title" "$MIHOMO_CONFIGURE" node prepare',SOURCE)
        self.assertIn('run_with_progress "$title" "$MIHOMO_CONFIGURE" provider candidate prepare',SOURCE)
        self.assertIn("if [[ ! -s \"$previous\" ]]",awg)

    def test_mihomo_additional_settings_are_ui_only_and_compact(self):
        main=body("mihomo_menu")
        additional=body("mihomo_advanced_menu")
        self.assertIn('3 "Точка выхода Mihomo / Xray"',main)
        self.assertIn('5 "Дополнительные настройки"',main)
        self.assertNotIn("Диагностика Xray —",main)
        self.assertIn('1 "Обновить через выбранный канал"',additional)
        self.assertIn('2 "Формат подписки"',additional)
        self.assertIn('0 "Назад"',additional)
        for retired in (
            '3 "$candidate_label"', '4 "Локальное восстановление',
            '5 "Восстановить резерв Mihomo при AWG"',
            '6 "Xray VLESS: диагностика"',
            '3) mihomo_candidate_menu',
            'capture "$MIHOMO_INSTALLER" --file',
            '5) mihomo_standby_repair_menu',
            '6) mihomo_xray_vless_menu',
        ):
            self.assertNotIn(retired,additional)
        # Existing recovery / diagnostics engines are unchanged, just not
        # exposed as duplicate or unsafe day-to-day menu actions.
        self.assertIn("mihomo_candidate_menu(){",SOURCE)
        self.assertIn("mihomo_standby_repair_menu(){",SOURCE)
        self.assertIn("mihomo_xray_vless_menu(){",SOURCE)
        self.assertIn('awg-xray-vless list',body("mihomo_xray_vless_menu"))


    def test_utf8_local_menu_without_system_locale_mutation(self):
        self.assertIn('locale charmap', SOURCE)
        self.assertIn('export LC_ALL=C.UTF-8', SOURCE)
        self.assertIn('locale -a', SOURCE)
        self.assertIn('Для русского меню требуется окно SSH', SOURCE)
        self.assertIn('exit 10', SOURCE)
        self.assertNotIn('localectl set-locale', SOURCE)
        self.assertNotIn('update-locale', SOURCE)

    def test_evidence_semantics_and_russian_auto(self):
        self.assertIn('hot_pool_summary(){', SOURCE)
        self.assertIn('status_args=(--provider', SOURCE)
        self.assertIn('"${status_args[@]}"', SOURCE)
        self.assertIn('if [[ "$transport" == "не настроен" ]]', SOURCE)
        self.assertIn('Смена узлов Mihomo управляется отдельной политикой', SOURCE)
        self.assertIn('только если профиль AWG настроен и работоспособен', SOURCE)
        self.assertNotIn('узел и страна Mihomo не переключаются автоматически', SOURCE)


    def test_persisted_choice_marker_and_unknown_choice(self):
        shell = body("awg_option_label") + """
awg_option_label "Все протоколы" all all
printf '\\n'
awg_option_label "VLESS" vless all
printf '\\n'
awg_option_label "Выборочный шлюз" selective ""
printf '\\n'
awg_option_label "Matrix Gradient" matrix matrix
printf '\\n'
"""
        p = subprocess.run(["bash", "-c", shell], capture_output=True,
                           text=True, timeout=5, check=True)
        self.assertEqual(p.stdout.splitlines(), [
            "Все протоколы ✓", "VLESS", "Выборочный шлюз", "Matrix Gradient ✓",
        ])
        for statement in (
            'awg_option_label "Все протоколы" all "$current"',
            'awg_option_label "$mihomo_label" mihomo "$current"',
            'awg_option_label "$selective_label" selective "$current_id"',
            'awg_option_label "Matrix Gradient" matrix "$current"',
            'awg_option_label "MANUAL" manual "$active_policy"',
            'awg_option_label "Включить Xray в AUTO" enabled "$xray_option"',
        ):
            self.assertIn(statement, SOURCE)

    def test_protocol_setting_has_one_ui_entry_point(self):
        # Extra picker action was a duplicate writer of the same pool protocol.
        self.assertIn("mihomo_protocol_settings", body("mihomo_subscription_menu"))
        extra = body("mihomo_pool_pick")
        self.assertNotIn("mihomo_protocol_select ", extra)
        self.assertNotIn('"$MIHOMO_POOL" protocol set', extra)
        self.assertNotIn('3 "Протокол', extra)
        self.assertIn('2 "Фильтр региона', extra)
        self.assertIn('3 "Обновить проверку', extra)
        self.assertIn('5 "Показать все результаты', extra)

    def test_unified_catalog_never_counts_unverified_xray_as_fail(self):
        with tempfile.TemporaryDirectory(prefix="awg-node-evidence-") as td:
            capture = Path(td) / "dialog-args"
            listing = "\n".join([
                "1\tXray-unknown\tvless\tn1.example:443\t-\tXRAY_UNTESTED\t??\t-",
                "2\tXray-good\tvless\tn2.example:443\t-\tXRAY_HTTPS\t??\t-",
                "3\tXray-bad\tvless\tn3.example:443\t-\tXRAY_NETWORK_FAIL\t??\t-",
                "4\tMihomo-fail\thysteria2\tn4.example:2097\t-\tMIHOMO_FAIL\tDE\t-",
            ])
            shell = body("select_tsv_node_dialog") + """
mihomo_clip_node_label(){ printf '%s' "$1"; }
mihomo_display_node_name(){ printf '%s' "$1"; }
dialog(){ printf '%s\\n' "$@" > "$CAPTURE"; return 1; }
MIHOMO_UNIFIED=/bin/false
select_tsv_node_dialog "Точка выхода Mihomo / Xray" "Выберите ноду" "$LISTING" yes candidate
"""
            result = subprocess.run(["bash", "-c", shell],
                                    env={**os.environ, "CAPTURE": str(capture),
                                         "LISTING": listing},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1, result.stderr)
            output = capture.read_text()
            self.assertIn("Xray: OK 1 | FALL 1 | без вердикта 1", output)
            self.assertIn("Mihomo: OK 0 | FALL 1 | без вердикта 0", output)
            self.assertIn("Xray-unknown | Xray | vless | n1.example:443 | — | НЕ ПРОВ.", output)
            self.assertIn("Xray-bad | Xray | vless | n3.example:443 | — | FALL", output)
            self.assertNotIn("Xray OK: 0", output)


if __name__ == "__main__":
    unittest.main()
