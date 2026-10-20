#!/usr/bin/env python3
"""Rootless experimental AUTO cross-core contract; no live service changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/awg-mihomo-node-policy").read_text()
FUNCTION = ("auto_xray_candidate(){" +
            SOURCE.split("auto_xray_candidate(){", 1)[1].split("\n}\n", 1)[0] +
            "\n}\n")


class XrayAutoDispatch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "transactions"
        self.log.write_text("")
        self.mode = self.base / "mode"
        self.mode.write_text("transit\n")
        self.mkbin("hostname", "echo awg-upgrade")
        self.mkbin("systemctl", '[ "$1" = is-active ]')
        self.mkbin("transaction",
                   'printf "%s:%s:%s\\n" "$AWG_XRAY_EXPERIMENTAL_APPLY" "$2" "$3" >> "$MOCK_LOG"\n'
                   '[ "$MOCK_RC" = 0 ]')

    def mkbin(self, name, command):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + command + "\n")
        path.chmod(0o755)
        return path

    def run_helper(self, *, optin="0", mode="transit", health="NETWORK_OK",
                   host="awg-upgrade", ready="0", standby="0", rc="0",
                   executor=True, selective_optin="0"):
        self.mode.write_text(mode + "\n")
        self.mkbin("hostname", "echo " + host)
        exe = self.bin / "transaction"
        if not executor:
            exe.unlink(missing_ok=True)
        elif not exe.exists():
            self.mkbin("transaction", 'exit 0')
        env = {**os.environ, "PATH": str(self.bin) + ":" + os.environ["PATH"],
               "MOCK_LOG": str(self.log), "MOCK_RC": rc,
               "MIHOMO_XRAY_AUTO_FAILOVER_CANARY": optin,
               "MIHOMO_XRAY_SELECTIVE_CANARY": selective_optin,
               "MIHOMO_STANDBY_REPAIR": standby,
               "MIHOMO_READY_AUTO_CANARY": ready,
               "MIHOMO_AUTO_MODE_FILE": str(self.mode),
               "MIHOMO_XRAY_TRANSACTION_CLI": str(exe),
               "MIHOMO_AUTO_SYSTEMCTL": str(self.bin/"systemctl"),
               "MIHOMO_AUTO_SERVICE": "awg-mihomo.service"}
        script = FUNCTION + ('auto_xray_candidate FAILED-CURRENT VLESS-CANDIDATE '
                             '"NODE_ENGINE=XRAY\nNODE_BASIC_NETWORK=$1"')
        return subprocess.run(["bash", "-c", script, "test", health],
                              env=env, capture_output=True, text=True, timeout=5)

    def test_default_off_never_invokes_xray(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("XRAY_TRANSACTION_NOT_CERTIFIED", result.stderr)
        self.assertEqual(self.log.read_text(), "")

    def test_explicit_transit_network_ok_can_call_guarded_executor(self):
        result = self.run_helper(optin="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MIHOMO_NODE_FAILOVER=FAILED-CURRENT->VLESS-CANDIDATE", result.stdout)
        self.assertEqual(self.log.read_text().strip(),
                         "TEST_PI_AUTHORIZED:FAILED-CURRENT:VLESS-CANDIDATE")

    def test_selective_does_not_inherit_transit_optin(self):
        result = self.run_helper(optin="1", mode="selective")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.log.read_text(), "")

    def test_selective_requires_both_explicit_canary_flags(self):
        result = self.run_helper(optin="1", mode="selective", selective_optin="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(),
                         "TEST_PI_AUTHORIZED:FAILED-CURRENT:VLESS-CANDIDATE")


    def test_network_unproven_cannot_activate(self):
        result = self.run_helper(optin="1", health="UNKNOWN_HTTP")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.log.read_text(), "")

    def test_non_testpi_refuses(self):
        result = self.run_helper(optin="1", host="production-pi")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.log.read_text(), "")

    def test_hot_pool_ready_does_not_bypass_proof(self):
        result = self.run_helper(optin="1", ready="1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.log.read_text(), "")

    def test_standby_repair_never_interferes_with_awg(self):
        result = self.run_helper(optin="1", standby="1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.log.read_text(), "")

    def test_missing_executor_refuses_without_activation(self):
        result = self.run_helper(optin="1", executor=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("XRAY_TRANSACTION_EXECUTOR_MISSING", result.stderr)
        self.assertEqual(self.log.read_text(), "")

    def test_transaction_failure_forces_transport_level_fallback(self):
        result = self.run_helper(optin="1", rc="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("XRAY_AUTO_TRANSACTION_ABORTED_AWG_FALLBACK", result.stderr)
        self.assertNotIn("MIHOMO_NODE_FAILOVER=FAILED-CURRENT->", result.stdout)

    def test_auto_never_passes_xray_to_legacy_node_select(self):
        part = SOURCE.split("failover_auto(){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('if [[ "$engine" == XRAY ]]; then', part)
        self.assertIn('auto_xray_candidate "$current" "$candidate" "$resolved"', part)
        self.assertIn('(( xray_rc == 2 )) || return 1', part)
        self.assertLess(part.index('if [[ "$engine" == XRAY ]]; then'),
                        part.index('"$MIHOMO_CONFIGURE" node select-auto "$candidate"'))

    def test_active_xray_does_not_use_legacy_recovery(self):
        part = SOURCE.split("failover_auto(){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('systemctl is-active --quiet awg-xray-vless.service', part)
        self.assertIn('XRAY_ACTIVE_DEFER_TO_TRANSPORT_AWG', part)
        # The Xray service can crash while its boot overlay and selection
        # remain. AUTO must still refuse unsafe Mihomo-only recovery.
        self.assertIn('61-awg-xray-bridge.conf', part)
        self.assertIn('/var/lib/awg-pbr/xray-vless/selected.json', part)

    def test_installer_and_menu_do_not_enable_experiment(self):
        for path in (ROOT / "install.sh", ROOT / "src/awg-menu"):
            self.assertNotIn("MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1", path.read_text())


if __name__ == "__main__":
    unittest.main()
