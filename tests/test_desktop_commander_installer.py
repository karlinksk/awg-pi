"""Regression tests for safe optional Remote Desktop Commander installation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
CLI = ROOT / "src/awg-dc"
UNIT = ROOT / "units/awg-dc-remote@.service"


class DesktopCommanderInstaller(unittest.TestCase):
    def test_bash_syntax(self):
        for source in (INSTALL, CLI):
            result = subprocess.run(
                ["bash", "-n", str(source)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_help_needs_no_root_and_starts_no_agent(self):
        result = subprocess.run(
            ["bash", str(CLI), "help"], capture_output=True, text=True, timeout=5
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("awg-dc pair", result.stdout)
        self.assertIn("sudo awg-dc enable USER", result.stdout)

    def test_cli_always_staged_on_fresh_and_upgrade(self):
        install = INSTALL.read_text()
        self.assertIn('DC_CLI="/usr/local/bin/awg-dc"', install)
        self.assertIn("https://raw.githubusercontent.com/karlinksk/awg-pi/", install)
        self.assertIn('install_project_helper src/awg-dc "$DC_CLI"', install)
        self.assertIn(
            'install_project_unit units/awg-dc-remote@.service "$DC_UNIT"', install
        )
        self.assertLess(
            install.index('install_project_helper src/awg-dc'),
            install.index('log "[11/12] Первый запуск"'),
        )
        self.assertIn('bash -n "$DC_CLI"', install)

    def test_package_provision_is_explicit_opt_in(self):
        install = INSTALL.read_text()
        self.assertIn('case "${AWG_DC_PREPARE:-0}" in', install)
        self.assertIn('"$DC_CLI" prepare "$_dc_user"', install)
        self.assertIn('AWG_DC_USER', install)
        self.assertNotIn('systemctl enable --now awg-dc-remote@', install)
        self.assertIn('warn "DC runtime не подготовлен;', install)

    def test_agent_cannot_be_enabled_or_paired_as_root_without_approval(self):
        source = CLI.read_text()
        self.assertIn('(( EUID != 0 )) || fail PAIR_AS_NONROOT_USER', source)
        self.assertIn('session_ok || fail PAIRING_REQUIRED_OR_UNSAFE_SESSION_PERMISSIONS', source)
        self.assertIn('[[ "$owner" == "$DC_UID" && "$mode" == 600 ]]', source)
        self.assertIn('getent passwd "$name"', source)
        self.assertIn('[[ "$home" == "/home/$name"', source)
        self.assertIn('runuser -u "$DC_USER"', source)
        self.assertIn('remote --help', source)
        self.assertIn('typeof WebSocket !== "function"', source)
        self.assertIn('sh -c', source)
        self.assertIn('exec npm exec --yes --package="$DC_NODE_PACKAGE" --package="$DC_PACKAGE" -- desktop-commander remote', source)
        self.assertNotIn('NOPASSWD:ALL', source)
        self.assertNotIn('device.json" >', source)

    def test_service_runs_as_user_no_network_inbound(self):
        unit = UNIT.read_text()
        self.assertIn("User=%i", unit)
        self.assertIn("WorkingDirectory=/home/%i", unit)
        self.assertIn("UMask=0077", unit)
        self.assertIn("ExecStart=/usr/bin/env npm exec --yes --package=node@22", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertNotIn("User=root", unit)
        self.assertNotIn("ExecStartPre=sudo", unit)
        self.assertNotIn("iptables", unit)
        self.assertNotIn("nft", unit)

    def test_version_pinned_to_avoid_unreviewed_updates(self):
        source = CLI.read_text()
        unit = UNIT.read_text()
        pinned = "@wonderwhy-er/desktop-commander@0.2.52"
        self.assertIn(pinned, source)
        self.assertIn(pinned, unit)
        self.assertIn("DC_NODE_PACKAGE='node@22'", source)
        self.assertIn("--package=node@22", unit)
        self.assertIn('node@22', source)
        self.assertNotIn("@latest", source)
        self.assertNotIn("@latest", unit)

    def test_status_is_read_only(self):
        src = CLI.read_text()
        self.assertIn('AWG_DC_AUTOSTART=DISABLED', src)
        self.assertIn('AWG_DC_AGENT_SERVICE=INACTIVE', src)
        self.assertIn('AWG_DC_REMOTE_CONNECTIVITY=CHECK_DASHBOARD', src)
        self.assertIn('systemctl disable --now', src)
        self.assertNotIn('systemctl restart awg-mihomo', src)
        self.assertNotIn('systemctl restart dnsmasq', src)


if __name__ == "__main__":
    unittest.main()
