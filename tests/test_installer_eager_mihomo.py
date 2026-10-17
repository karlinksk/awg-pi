#!/usr/bin/env python3
"""Regression: the pinned Mihomo engine ships before provider onboarding."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / 'install.sh').read_text()


class EagerMihomoInstaller(unittest.TestCase):
    def test_pinned_engine_installed_before_first_run(self):
        install = INSTALL.index('"$MIHOMO_INSTALL_SCRIPT" ensure --mode auto')
        wizard = INSTALL.index('"$FIRST_RUN_CLI" wizard')
        self.assertLess(install, wizard)
        self.assertIn('"$MIHOMO_INSTALL_SCRIPT" status || die', INSTALL)
        self.assertIn('[[ -x /usr/local/bin/mihomo ]] || die', INSTALL)

    def test_engine_installation_is_fresh_only(self):
        start = INSTALL.index('# A clean install ships BOTH VPN engines')
        end = INSTALL.index('install_project_python_helper', start)
        region = INSTALL[start:end]
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then', region)
        self.assertIn('else\n  # Do not replace a running engine', region)
        self.assertIn('"$MIHOMO_INSTALL_SCRIPT" ensure --mode auto', region)
        self.assertNotIn('"$MIHOMO_INSTALL_SCRIPT" ensure --mode auto', region.split('else\n  # Do not replace a running engine')[1])

    def test_fresh_install_enables_conservative_transport_failover(self):
        self.assertIn('"$SELECTION_CLI" mode auto mihomo awg', INSTALL)
        self.assertIn('if (( UPGRADE_EXISTING == 0 )); then', INSTALL)

    def test_install_is_independent_of_subscription(self):
        start = INSTALL.index('if (( UPGRADE_EXISTING == 0 )); then', INSTALL.index('# A clean install ships BOTH VPN engines'))
        end = INSTALL.index('install_project_python_helper', start)
        self.assertNotIn('subscription.yaml', INSTALL[start:end])
        self.assertNotIn('provider.env', INSTALL[start:end])

if __name__ == '__main__':
    unittest.main()
