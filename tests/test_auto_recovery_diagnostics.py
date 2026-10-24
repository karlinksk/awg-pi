#!/usr/bin/env python3
"""Rootless regression: retain safe AUTO fault reason without changing fallback."""
import os
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "src/awg-selection-monitor"
BACKEND = ROOT / "src/awg-xray-live-backend.py"


class AutoRecoveryDiagnostics(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "state"
        self.state.write_text("mihomo\n")
        self.logs = self.root / "events"
        self.events = self.root / "selects"
        self.logs.touch()
        self.events.touch()
        (self.root / "common").write_text(
            'awg_transport_get(){ cat "$STATE"; }\n'
            'awg_transport_backend_valid(){ return 0; }\n'
        )
        (self.root / "selection.env").write_text(
            "SELECTION_MODE=auto\nSELECTION_ORDER=mihomo,awg\n"
        )
        (self.root / "awg0.conf").write_text("fake profile; no keys\n")
        self.script("transport", """case "$1" in
  check) exit 0;;
  network-check) exit 1;;
  select) echo "$2" >> "$SELECTS"; echo "$2" > "$STATE"; exit 0;;
  get) cat "$STATE";;
  *) exit 2;;
esac
""")
        self.script("node", """case "$1" in
 enabled) if [ "$ENABLED" = 1 ]; then exit 0; else exit 1; fi;;
 failover)
   case "$NODE_CASE" in
     fail)
       echo 'MIHOMO_NODE_FAILOVER=UNIFIED_XRAY_ABORT_AWG_FALLBACK' >&2
       echo 'provider-secret=https://secret.example/private?key=UNSAFE' >&2
       exit 1;;
     success)
       echo 'MIHOMO_UNIFIED_RECOVERY_ATTEMPTS=7 ENGINE=XRAY' >&2
       echo 'MIHOMO_NODE_FAILOVER=Native-1->Xray-1'
       exit 0;;
     unknown)
       echo 'unexpected secret error: supersecret' >&2
       exit 2;;
   esac;;
esac
exit 2
""")
        self.script("logger", 'printf "%s\\n" "$*" >> "$EVENT_LOG"\n')

    def script(self, name, body):
        p = self.bin / name
        p.write_text("#!/usr/bin/env bash\n" + body)
        p.chmod(0o755)

    def run_monitor(self, mode="fail", enabled="1"):
        env = {
            **os.environ,
            "STATE": str(self.state), "SELECTS": str(self.events),
            "EVENT_LOG": str(self.logs), "NODE_CASE": mode,
            "ENABLED": enabled,
            "AWG_COMMON_FILE": str(self.root / "common"),
            "AWG_SELECTION_FILE": str(self.root / "selection.env"),
            "AWG_TRANSPORT_CLI": str(self.bin / "transport"),
            "MIHOMO_NODE_POLICY_CLI": str(self.bin / "node"),
            "LOGGER_BIN": str(self.bin / "logger"),
            "AWG_SELECTION_STATE_DIR": str(self.root / "runtime"),
            "AWG_LOCK_FILE": str(self.root / "maintenance.lock"),
            "AWG_AUTO_AWG_CONFIG": str(self.root / "awg0.conf"),
            "AWG_SELECTION_ONCE": "1",
            "AWG_SELECTION_FAILURE_THRESHOLD": "1",
        }
        return subprocess.run(["bash", str(MONITOR)], env=env, text=True,
                              capture_output=True, timeout=8)

    def test_classified_node_error_logged_and_awg_fallback_preserved(self):
        p = self.run_monitor()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.state.read_text().strip(), "awg")
        self.assertEqual(self.events.read_text().strip(), "awg")
        events = self.logs.read_text()
        self.assertIn("AUTO_NODE_RECOVERY_CODE=UNIFIED_XRAY_ABORT_AWG_FALLBACK", events)
        self.assertIn("AUTO_NODE_RECOVERY_EXIT=1", events)
        self.assertNotIn("secret.example", events)
        self.assertNotIn("UNSAFE", events)
        self.assertNotIn("provider-secret", events)

    def test_success_stdout_separated_from_stderr_attempts(self):
        p = self.run_monitor(mode="success")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("MIHOMO_NODE_FAILOVER=Native-1->Xray-1", p.stdout)
        self.assertEqual(self.state.read_text().strip(), "mihomo")
        self.assertFalse(self.events.read_text())
        self.assertNotIn("AUTO_NODE_RECOVERY_EXIT=", self.logs.read_text())

    def test_unknown_error_logs_exit_only_without_private_text(self):
        p = self.run_monitor(mode="unknown")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.state.read_text().strip(), "awg")
        self.assertIn("AUTO_NODE_RECOVERY_EXIT=2", self.logs.read_text())
        self.assertNotIn("supersecret", self.logs.read_text())

    def test_node_policy_not_enabled_is_distinct_from_node_failure(self):
        p = self.run_monitor(enabled="0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("AUTO_NODE_RECOVERY_CODE=NODE_POLICY_DISABLED",
                      self.logs.read_text())
        self.assertEqual(self.state.read_text().strip(), "awg")

    def test_xray_backend_token_logger_never_leaks_private_details(self):
        source = BACKEND.read_text()
        func = ("def auto_fault(stage, code):" +
                source.split("def auto_fault(stage, code):", 1)[1]
                .split("\ndef xray_auto_authorized():", 1)[0])
        observed = []
        fake_subprocess = types.SimpleNamespace(
            run=lambda args, **kwargs: observed.append(args),
            DEVNULL=-1, TimeoutExpired=subprocess.TimeoutExpired)
        scope = {"re": re, "subprocess": fake_subprocess}
        exec(func, scope)
        scope["auto_fault"]("GATE", "LIVE_BASELINE_UNSAFE")
        scope["auto_fault"]("GATE", "profile?token=private-uuid")
        self.assertEqual(observed[0][-1], "AUTO_XRAY_GATE=LIVE_BASELINE_UNSAFE")
        self.assertEqual(observed[1][-1], "AUTO_XRAY_GATE=UNCLASSIFIED")


if __name__ == "__main__":
    unittest.main()
