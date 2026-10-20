"""Installer contract for guarded Xray/AWG Selective recovery assets."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class XrayInstallerDelivery(unittest.TestCase):
    def test_cross_core_components_persist_in_installer(self):
        installer = (ROOT / "install.sh").read_text()
        for source, target in (
            ("src/awg-xray-install", "awg-xray-install"),
            ("src/awg-xray-vless.py", "awg-xray-vless"),
            ("src/awg-xray-activation-transaction.py", "awg-xray-activation-transaction"),
            ("src/awg-xray-live-backend.py", "awg-xray-live-backend"),
            ("src/awg-xray-failover-contract.py", "awg-xray-failover-contract"),
            ("src/awg-xray-recovery-runner.py", "awg-xray-recovery-runner"),
        ):
            with self.subTest(source=source):
                self.assertTrue((ROOT / source).is_file())
                self.assertIn(f"{source} /usr/local/sbin/{target}", installer)
        self.assertIn("units/awg-xray-vless.service /etc/systemd/system/awg-xray-vless.service", installer)

    def test_experimental_auto_not_enabled_by_installer(self):
        installer = (ROOT / "install.sh").read_text()
        self.assertNotIn("MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1", installer)
        self.assertNotIn("MIHOMO_XRAY_SELECTIVE_CANARY=1", installer)
        self.assertNotIn("systemctl enable awg-xray-vless.service", installer)
        self.assertNotIn("systemctl start awg-xray-vless.service", installer)

if __name__ == "__main__":
    unittest.main()
