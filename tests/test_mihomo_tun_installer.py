"""Regression checks for optional real Pi-bound TUN acceptance on install."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "install.sh").read_text()
POSTCHECK = (ROOT / "src/awg-mihomo-ready-postcheck-tun").read_text()
HELPER = (ROOT / "src/awg-mihomo-tun-check").read_text()


class InstallerTunAcceptance(unittest.TestCase):
    def test_installer_installs_helper_before_running(self):
        self.assertLess(
            INSTALL.index('install_project_helper src/awg-mihomo-tun-check'),
            INSTALL.index('if "$MIHOMO_TUN_CHECK" >/dev/null 2>&1; then'),
        )
        self.assertIn('bash -n "$MIHOMO_TUN_CHECK"', INSTALL)
        self.assertIn('sudo awg-mihomo-tun-check', INSTALL)

    def test_install_never_blocks_on_unusable_node(self):
        self.assertIn('warn "Mihomo backend может работать', INSTALL)
        self.assertNotIn('die "Mihomo backend может работать', INSTALL)
        self.assertIn('if [[ "$ACTIVE_TRANSPORT" == mihomo ]]; then', INSTALL)

    def test_postcheck_cannot_use_inherited_http_proxy(self):
        self.assertEqual(POSTCHECK.count("-q -4 --noproxy '*' --interface"), 2)
        self.assertIn('https://api.ipify.org', POSTCHECK)
        self.assertIn('https://api.openai.com/v1/models', POSTCHECK)
        self.assertIn('READY_TUN_SCOPE=PI_BOUND_TUN_NOT_FORWARDED_CLIENT', POSTCHECK)

    def test_check_reports_scoped_status_without_mutation(self):
        self.assertIn('MIHOMO_TUN_CHECK=PASS', HELPER)
        self.assertIn('MIHOMO_TUN_CHECK=NOT_CONFIRMED', HELPER)
        self.assertIn('MIHOMO_TUN_CHECK=NOT_ACTIVE', HELPER)
        self.assertIn('MIHOMO_TUN_SCOPE=PI_BOUND_TUN_NOT_LAN_CLIENT', HELPER)
        self.assertIn('timeout --signal=TERM --kill-after=5s 100s "$POSTCHECK"', HELPER)
        for forbidden in ('systemctl restart', 'ip route replace',
                          'mihomo-configure node select', 'nft add'):
            self.assertNotIn(forbidden, HELPER)


if __name__ == "__main__":
    unittest.main()
