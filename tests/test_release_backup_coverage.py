"""Release regression: gateway backup/rollback includes newly installed files."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "src/awg-update").read_text()
INSTALL = (ROOT / "install.sh").read_text()
BACKUP = UPDATE.split("backup_gateway(){", 1)[1].split("restore_gateway(){", 1)[0]
RESTORE = UPDATE.split("restore_gateway(){", 1)[1].split("gateway_update(){", 1)[0]

NEW_SCRIPTS = (
    "usr/local/bin/awg-dc",
    "usr/local/sbin/awg-system-node",
    "usr/local/sbin/awg-mihomo-stage18-ram-runtime",
    "usr/local/sbin/awg-mihomo-tun-check",
    "usr/local/sbin/awg-mihomo-pool",
    "usr/local/sbin/awg-mihomo-limits.py",
    "usr/local/sbin/awg-mihomo-service-check.py",
    "usr/local/sbin/awg-mihomo-video-decode.py",
    "usr/local/sbin/awg-mihomo-service-eligibility.py",
    "usr/local/sbin/awg-mihomo-network-eligibility.py",
    "usr/local/sbin/awg-mihomo-smart",
)
NEW_UNITS = (
    "etc/systemd/system/awg-dc-remote@.service",
    "etc/systemd/system/awg-mihomo-pool-refresh.service",
    "etc/systemd/system/awg-mihomo-pool-refresh.timer",
    "etc/systemd/system/awg-mihomo-stage18-ram-runtime.service",
    "etc/systemd/system/awg-mihomo-stage18-ram-runtime.timer",
    "etc/systemd/system/awg-mihomo-stage18-ram-runtime.path",
)


class ReleaseBackupCoverage(unittest.TestCase):
    def test_every_new_script_saved_and_reverted(self):
        for rel in NEW_SCRIPTS:
            with self.subTest(path=rel):
                self.assertIn("    " + rel + " \\\n", BACKUP)
                self.assertIn("    /" + rel, RESTORE)

    def test_new_service_units_saved_and_reverted(self):
        for rel in NEW_UNITS:
            with self.subTest(unit=rel):
                self.assertIn("    " + rel + " \\\n", BACKUP)
                self.assertIn("    /" + rel, RESTORE)

    def test_managed_node_link_and_target_recover(self):
        self.assertIn("    usr/local/bin/node \\\n", BACKUP)
        self.assertIn("    usr/local/lib/awg-pi \\\n", BACKUP)
        self.assertIn('[[ -L /usr/local/bin/node ]]', RESTORE)
        self.assertIn('readlink -- /usr/local/bin/node', RESTORE)
        self.assertIn('== /usr/local/lib/awg-pi/node/*/node', RESTORE)
        self.assertNotIn("rm -f /usr/bin/node", RESTORE)
        self.assertNotIn("rm -rf /usr/local/bin", RESTORE)

    def test_stage18_media_cache_is_saved_and_rollback_removes_stale_cache(self):
        self.assertIn("var/lib/awg-pbr/stage18-runtime", BACKUP)
        self.assertIn("rm -rf /var/lib/awg-pbr/stage18-runtime", RESTORE)
        self.assertIn("var/lib/awg-pbr/hot-pool", BACKUP)
        self.assertIn("var/lib/awg-pbr/mihomo", BACKUP)

    def test_optional_system_watchdog_is_part_of_rollback_snapshot(self):
        self.assertIn("etc/systemd/system.conf.d/99-awg-gateway-watchdog.conf", BACKUP)
        self.assertIn("/etc/systemd/system.conf.d/99-awg-gateway-watchdog.conf", RESTORE)
        self.assertIn('WATCHDOG_DROPIN="/etc/systemd/system.conf.d/99-awg-gateway-watchdog.conf"', INSTALL)

    def test_mihomo_health_pool_cli_backed_up(self):
        self.assertIn('install -m 755 "$_mihomo_pool_tmp" "$MIHOMO_POOL_CLI"', INSTALL)
        self.assertIn('MIHOMO_POOL_CLI="/usr/local/sbin/awg-mihomo-pool"', INSTALL)
        self.assertIn("usr/local/sbin/awg-mihomo-pool", BACKUP)
        self.assertIn("/usr/local/sbin/awg-mihomo-pool", RESTORE)

    def test_device_secrets_never_backed_up_from_home(self):
        self.assertNotIn(".desktop-commander-device/device.json", UPDATE)
        self.assertNotIn("home/karlinks", UPDATE)
        self.assertNotIn("SUDO_USER", UPDATE)

    def test_dc_agent_not_disabled_during_vpn_rollback(self):
        self.assertNotIn("systemctl stop awg-dc", RESTORE)
        self.assertNotIn("awg-dc-remote@*.service", RESTORE)

    def test_install_contains_all_new_items(self):
        for name in (
            "scripts/awg-system-node.sh",
            "src/awg-dc",
            "src/awg-mihomo-tun-check",
            "scripts/awg-mihomo-stage18-ram-runtime.sh",
            "units/awg-dc-remote@.service",
            "units/awg-mihomo-stage18-ram-runtime.timer",
        ):
            with self.subTest(install=name):
                self.assertIn(name, INSTALL)


if __name__ == "__main__":
    unittest.main()
