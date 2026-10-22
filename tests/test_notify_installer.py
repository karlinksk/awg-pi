"""AWG Notify installer/selector safety contract tests."""
from pathlib import Path
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
        self.assertIn('9 "Telegram — уведомления"', menu)
        self.assertIn('9) notify_menu ;;', menu)
        self.assertIn('run_interactive "Настройка Telegram-бота"', menu)
        self.assertIn("systemctl enable --now awg-notify-flush.timer", menu)
        self.assertIn('NOTIFY_CONFIGURED=yes', menu)

    def test_no_router_or_dns_modifications(self):
        code = (ROOT / "src/awg-notify.py").read_text()
        for keyword in ("ip route replace", "nft add", "mikrotik login", "dnsmasq restart"):
            self.assertNotIn(keyword, code)
        self.assertIn('"eth0"', code)


if __name__ == "__main__":
    unittest.main()
