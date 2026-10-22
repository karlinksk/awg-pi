"""AWG Notify installer/selector safety contract tests."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NotifyWiringTests(unittest.TestCase):
    def test_installer_passive(self):
        install = (ROOT / "install.sh").read_text()
        self.assertIn("install_project_python_helper src/awg-notify.py /usr/local/sbin/awg-notify", install)
        for filename in ("awg-notify-flush.service", "awg-notify-flush.timer"):
            self.assertIn("install_project_unit units/" + filename, install)
        self.assertNotIn("systemctl enable --now awg-notify-flush.timer", install)
        self.assertIn("install -d -o root -g root -m 0700 /etc/awg-pbr/notify /var/lib/awg-pbr/notify", install)

    def test_pair_repair_installed_only_passively(self):
        install = (ROOT / "install.sh").read_text()
        menu = (ROOT / "src/awg-menu").read_text()
        self.assertIn(
            "install_project_python_helper scripts/awg-notify-pair-repair.py "
            "/usr/local/sbin/awg-notify-pair-repair", install)
        self.assertNotIn("sudo /usr/local/sbin/awg-notify-pair-repair", install)
        self.assertIn('8 "Исправить привязку чата"', menu)
        self.assertIn('run_interactive "Исправление Telegram chat ID"', menu)
        self.assertIn('if [[ -x /usr/local/sbin/awg-notify-pair-repair ]]', menu)

    def test_disabled_notification_is_nonintrusive(self):
        transport = (ROOT / "src/awg-transport").read_text()
        selection = (ROOT / "src/awg-selection-monitor").read_text()
        self.assertIn("systemctl is-enabled --quiet awg-notify-flush.timer", transport)
        self.assertIn("systemctl is-enabled --quiet awg-notify-flush.timer", selection)
        self.assertIn("notify_kind=TRANSPORT_SWITCH", transport)
        self.assertIn("notify_kind=TRANSPORT_FAILOVER", transport)
        self.assertIn('AWG_NOTIFY_AUTOMATIC=1 "$AWG_TRANSPORT_CLI" select', selection)

    def test_source_notifies_after_transport_postcheck(self):
        code = (ROOT / "src/awg-transport").read_text()
        self.assertLess(code.index('if [[ "$target" == mihomo ]]; then mihomo_tun_https_ok; fi'),
                        code.index('--kind "$notify_kind"'))
        self.assertIn("timeout 2s /usr/local/sbin/awg-notify", code)
        self.assertIn("/etc/awg-pbr/notify/telegram.json", code)

    def test_monitor_does_not_send_network_messages(self):
        code = (ROOT / "src/awg-selection-monitor").read_text()
        self.assertIn("--kind NODE_SWITCH", code)
        self.assertIn("timeout 2s /usr/local/sbin/awg-notify emit", code)
        self.assertNotIn("api.telegram.org", code)

    def test_passive_watcher_scheduled_only_with_notifications(self):
        install = (ROOT / "install.sh").read_text()
        menu = (ROOT / "src/awg-menu").read_text()
        for name in ("awg-notify-watch.service", "awg-notify-watch.timer"):
            self.assertIn("install_project_unit units/" + name, install)
        self.assertNotIn("systemctl enable --now awg-notify-watch.timer", install)
        self.assertIn("systemctl enable --now awg-notify-watch.timer", menu)
        self.assertIn("systemctl disable --now awg-notify-watch.timer", menu)
        self.assertIn("OnUnitActiveSec=90sec", (ROOT / "units/awg-notify-watch.timer").read_text())

    def test_watch_sandbox_allows_read_only_netlink_health(self):
        unit = (ROOT / "units/awg-notify-watch.service").read_text()
        transport = (ROOT / "src/awg-transport").read_text()
        self.assertIn(
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK",
            unit)
        self.assertIn('"$IP_BIN" link show "$MIHOMO_TUN_IF"', transport)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ReadWritePaths=/var/lib/awg-pbr/notify", unit)
        self.assertNotIn("CapabilityBoundingSet=", unit)

    def test_test_pi_watch_acceptance_script_expands_shell_variables(self):
        path = ROOT / "scripts/awg-notify-watch-netlink-test-install.sh"
        script = path.read_text()
        self.assertIn('[[ ${EUID:-$(id -u)} -eq 0 ]]', script)
        self.assertIn('"${source_sha%% *}"', script)
        self.assertIn('"--unit=awg-notify-netlink-${flavor}-$$"', script)
        self.assertNotIn('\\${', script)
        self.assertIn('systemctl daemon-reload', script)
        self.assertIn('NOTIFY_WATCH_TIMER=DISABLED', script)
        self.assertNotIn('systemctl enable ', script)
        if os.geteuid() != 0:
            proc = subprocess.run(["bash", str(path)], text=True,
                                  capture_output=True, check=False, timeout=5)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("ROOT_REQUIRED", proc.stderr)
            self.assertNotIn("ROOT_REQUIRED", proc.stdout)

    def test_notify_upgrade_rollback_manifest_and_optin(self):
        upgrade = (ROOT / "src/awg-update").read_text()
        for name in ("awg-notify", "awg-notify-pair-repair"):
            self.assertIn("usr/local/sbin/" + name, upgrade)
        for unit in ("awg-notify-flush.timer", "awg-notify-watch.timer",
                     "awg-notify-daily.timer", "awg-notify-boot.service",
                     "awg-notify-flush.service", "awg-notify-watch.service",
                     "awg-notify-daily.service"):
            self.assertIn("etc/systemd/system/" + unit, upgrade)
        self.assertIn("var/lib/awg-pbr/notify", upgrade)
        self.assertIn('notify-activation-$unit', upgrade)
        self.assertIn('notify-activation-$notify_unit', upgrade)
        self.assertIn('systemctl disable --now awg-notify-flush.timer '
                      'awg-notify-watch.timer awg-notify-daily.timer '
                      'awg-notify-boot.service', upgrade)
        self.assertIn('systemctl enable --now "$notify_unit"', upgrade)
        self.assertIn('systemctl enable "$notify_unit"', upgrade)
        # No production VPN mutation should be added for a notifier backup.
        self.assertIn('systemctl daemon-reload', upgrade)

    def test_boot_notice_only_when_enabled(self):
        install = (ROOT / "install.sh").read_text()
        menu = (ROOT / "src/awg-menu").read_text()
        unit = (ROOT / "units/awg-notify-boot.service").read_text()
        self.assertIn("install_project_unit units/awg-notify-boot.service", install)
        self.assertIn("systemctl enable awg-notify-boot.service", menu)
        self.assertIn("systemctl disable --now awg-notify-boot.service", menu)
        self.assertIn("ConditionPathExists=/etc/awg-pbr/notify/telegram.json", unit)
        self.assertIn("ExecStart=/usr/local/sbin/awg-notify emit --kind BOOT", unit)
        self.assertNotIn("systemctl enable awg-notify-boot.service", install)

    def test_daily_timer_is_passive(self):
        install = (ROOT / "install.sh").read_text()
        for unit in ("awg-notify-daily.service", "awg-notify-daily.timer"):
            self.assertIn("install_project_unit units/" + unit, install)
        self.assertNotIn("systemctl enable --now awg-notify-daily.timer", install)
        timer = (ROOT / "units/awg-notify-daily.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 09:00:00", timer)

    def test_telegram_menu_is_in_system_area(self):
        menu = (ROOT / "src/awg-menu").read_text()
        self.assertIn('10 "Telegram — уведомления"', menu)
        self.assertIn('10) notify_menu ;;', menu)
        self.assertIn('run_interactive "Настройка Telegram-бота"', menu)
        self.assertIn("systemctl enable --now awg-notify-flush.timer", menu)
        self.assertIn('NOTIFY_CONFIGURED=yes', menu)

    def test_live_ui_and_initial_onboarding_survive_telegram_merge(self):
        menu = (ROOT / "src/awg-menu").read_text()
        self.assertIn('9 "Desktop Commander — удалённый доступ"', menu)
        self.assertIn('9) desktop_commander_menu ;;', menu)
        self.assertIn('10 "Telegram — уведомления"', menu)
        self.assertIn('10) notify_menu ;;', menu)
        self.assertIn('notify_menu) label="Telegram" ;;', menu)
        self.assertIn("use_scrollbar = OFF", menu)
        self.assertIn("screen_color = (BLACK,CYAN,OFF)", menu)
        self.assertIn("title_color = (WHITE,BLUE,ON)", menu)
        self.assertIn("first_transport_setup(){", menu)
        self.assertIn("secondary_transport_setup(){", menu)
        self.assertIn('7 "Добавить / настроить транспорт"', menu)
        self.assertIn('8 "Добавить / настроить транспорт"', menu)
        self.assertIn('7) secondary_transport_setup ;;', menu)
        self.assertIn('8) secondary_transport_setup ;;', menu)
        self.assertEqual(menu.count('10 "Telegram — уведомления"'), 1)

    def test_test_pi_menu_upgrade_preserves_live_and_secrets(self):
        installer = (ROOT / "install.sh").read_text()
        script = (ROOT / "scripts/awg-notify-menu-test-install.py").read_text()
        self.assertIn("install_project_helper src/awg-menu /usr/local/sbin/awg-menu", installer)
        self.assertIn("install_project_python_helper scripts/awg-notify-pair-repair.py", installer)
        self.assertIn("install_project_unit units/awg-notify-watch.service", installer)
        self.assertIn("MENU_ACCEPTED = {", script)
        self.assertIn("MENU_INSTALL=ALREADY_INSTALLED_TEST_PI_ONLY", script)
        self.assertIn("mode=0o700", script)
        self.assertIn("MENU_NEW = ", script)
        self.assertIn("PAIR_NEW = ", script)
        self.assertIn("REFUSED_DEPLOYED_MENU_HAS_CHANGED", script)
        self.assertIn("MENU_INSTALL=ROLLED_BACK", script)
        self.assertIn("CORE_SERVICES_AND_PBR=UNCHANGED", script)
        self.assertIn("NOTIFY_TIMERS=UNCHANGED", script)
        self.assertNotIn("systemctl restart", script)
        self.assertNotIn("systemctl enable", script)
        self.assertNotIn("mikrotik", script.lower())
        if os.geteuid() != 0:
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/awg-notify-menu-test-install.py")],
                capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn("ROOT_REQUIRED", result.stdout)

    def test_telegram_checklist_installer_and_matrix_compatibility(self):
        install = (ROOT / "install.sh").read_text()
        menu = (ROOT / "src/awg-menu").read_text()
        sender = (ROOT / "src/awg-notify.py").read_text()
        installer = (ROOT / "scripts/awg-notify-switches-test-install.py").read_text()
        self.assertIn("install_project_python_helper src/awg-notify.py", install)
        self.assertIn("install_project_helper src/awg-menu", install)
        self.assertIn("notify_types_menu(){", menu)
        self.assertIn("--separate-output --checklist", menu)
        self.assertIn('9 "Типы уведомлений [галочки]"', menu)
        self.assertIn("appearance_menu(){", menu)
        self.assertIn("awg-matrix-compositor.py", menu)
        self.assertIn('10 "Telegram — уведомления"', menu)
        self.assertIn('9 "Desktop Commander — удалённый доступ"', menu)
        self.assertIn("first_transport_setup(){", menu)
        self.assertIn("secondary_transport_setup(){", menu)
        self.assertIn('sub.add_parser("preferences-set")', sender)
        self.assertIn("PREFERENCES_PATH", sender)
        self.assertIn("NOTIFY_PREFERENCES=SAVED", sender)
        self.assertIn("NOTIFY_SWITCHES_INSTALL=ROLLED_BACK", installer)
        self.assertIn("TIMER_ENABLEMENT=UNCHANGED", installer)
        self.assertNotIn("systemctl restart", installer)
        self.assertNotIn("systemctl enable", installer)
        if os.geteuid() != 0:
            res = subprocess.run(
                ["python3", str(ROOT / "scripts/awg-notify-switches-test-install.py")],
                capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(res.returncode, 2)
            self.assertIn("ROOT_REQUIRED", res.stdout)

    def test_event_checklist_menu_and_installer_contract(self):
        menu = (ROOT / "src/awg-menu").read_text()
        backend = (ROOT / "src/awg-notify.py").read_text()
        for token in ("notify_types_menu(){", "--checklist", "--separate-output",
                      "preferences-set --enabled", "VPN_LOST", "VPN_RESTORED",
                      "NODE_SWITCH", "TRANSPORT_SWITCH", "BOOT", "DAILY_REPORT"):
            self.assertIn(token, menu)
        self.assertIn("PREFERENCES_PATH", backend)
        self.assertIn("NOTIFY_PREFERENCES=SAVED", backend)
        self.assertIn("save_preferences(enabled)", backend)
        self.assertIn('install_project_python_helper src/awg-notify.py /usr/local/sbin/awg-notify',
                      (ROOT / "install.sh").read_text())
        self.assertIn("appearance_menu(){", menu)
        self.assertIn("awg-matrix-compositor.py", menu)

    def test_checklist_test_pi_upgrade_pinned_and_read_only(self):
        script = (ROOT / "scripts/awg-notify-checklist-test-install.py").read_text()
        for term in ("CHECKLIST_INSTALL=PASS_TEST_PI_ONLY",
                     "CHECKLIST_INSTALL=ROLLED_BACK",
                     "REFUSE_CHECKSUM_CHANGED",
                     "TELEGRAM_EVENT_SWITCHES=6",
                     "MATRIX_AND_DESKTOP_COMMANDER=PRESERVED",
                     "NOTIFY_POLICY_FILE=UNMODIFIED",
                     "EXISTING_QUEUE_AND_BOT_SECRET=UNMODIFIED",
                     "NETWORK_AND_NOTIFIER_UNCHANGED=YES"):
            self.assertIn(term, script)
        self.assertNotIn("systemctl restart", script)
        self.assertNotIn("systemctl enable", script)
        if os.geteuid() != 0:
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/awg-notify-checklist-test-install.py")],
                text=True, capture_output=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("ROOT_REQUIRED", result.stderr)

    def test_no_router_or_dns_modifications(self):
        code = (ROOT / "src/awg-notify.py").read_text()
        for keyword in ("ip route replace", "nft add", "mikrotik login", "dnsmasq restart"):
            self.assertNotIn(keyword, code)
        self.assertIn('"eth0"', code)


if __name__ == "__main__":
    unittest.main()
