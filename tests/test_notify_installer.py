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

    def test_source_notifies_after_transport_postcheck(self):
        code = (ROOT / "src/awg-transport").read_text()
        self.assertLess(code.index('if [[ "$target" == mihomo ]]; then mihomo_tun_https_ok; fi'),
                        code.index("--kind TRANSPORT_FAILOVER"))
        self.assertIn("timeout 2s /usr/local/sbin/awg-notify", code)
        self.assertIn("/etc/awg-pbr/notify/telegram.json", code)

    def test_monitor_does_not_send_network_messages(self):
        code = (ROOT / "src/awg-selection-monitor").read_text()
        self.assertIn("--kind NODE_SWITCH", code)
        self.assertIn("timeout 2s /usr/local/sbin/awg-notify emit", code)
        self.assertNotIn("api.telegram.org", code)

    def test_no_router_or_dns_modifications(self):
        code = (ROOT / "src/awg-notify.py").read_text()
        for keyword in ("ip route replace", "nft add", "mikrotik login", "dnsmasq restart"):
            self.assertNotIn(keyword, code)
        self.assertIn('"eth0"', code)


if __name__ == "__main__":
    unittest.main()
