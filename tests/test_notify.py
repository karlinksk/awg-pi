"""No-network/rootless contract tests for AWG Notify."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "src" / "awg-notify.py"
spec = importlib.util.spec_from_file_location("awg_notify", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="awg-notify-test-")
        self.addCleanup(self.work.cleanup)
        self.folder = Path(self.work.name)
        self.db = mod.open_db(self.folder / "queue" / "events.sqlite3")
        self.addCleanup(self.db.close)
        self.secret = self.folder / "telegram.json"
        self.secret.write_text(json.dumps({
            "token": "12345678:" + "A" * 35,
            "chat_id": "123456789"
        }))
        self.secret.chmod(0o600)

    def test_dedupe_and_expiry(self):
        self.assertTrue(mod.enqueue(self.db, "NODE_SWITCH", "info", "old -> new", "same", 1000))
        self.assertFalse(mod.enqueue(self.db, "NODE_SWITCH", "info", "old -> new", "same", 1100))
        self.assertTrue(mod.enqueue(self.db, "NODE_SWITCH", "info", "old -> new", "same", 1120))
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 2)

    def test_invalid_inputs(self):
        for kind, sev, msg in [("BAD", "info", "x"), ("BOOT", "bad", "x"),
                               ("BOOT", "info", ""), ("BOOT", "info", "z" * 3001)]:
            with self.assertRaises(ValueError):
                mod.enqueue(self.db, kind, sev, msg)

    def test_secret_permissions(self):
        self.assertEqual(mod.load_secret(self.secret)[1], "123456789")
        self.secret.chmod(0o644)
        with self.assertRaises(ValueError):
            mod.load_secret(self.secret)

    def test_queue_survives_network_failure_and_recovers(self):
        mod.enqueue(self.db, "VPN_LOST", "critical", "Lost")
        calls = []
        def failed(token, payload, route):
            calls.append(route)
            return False, 0, 0
        with mock.patch.object(mod, "now", return_value=5000000000):
            result = mod.flush(self.db, failed, self.secret, active="awg")
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(calls, ["awg0", "mihomo0", "eth0"])
        self.db.execute("UPDATE events SET next_try=0")
        self.db.commit()
        def delivered(token, payload, route):
            return (route == "mihomo0", 200 if route == "mihomo0" else 0, 0)
        with mock.patch.object(mod, "now", return_value=5000000001):
            result = mod.flush(self.db, delivered, self.secret, active="awg")
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(self.db.execute("SELECT value FROM meta WHERE key='last_success_route'").fetchone()[0], "mihomo0")

    def test_missing_credentials_preserves_queue(self):
        mod.enqueue(self.db, "BOOT", "info", "Restart")
        self.secret.unlink()
        result = mod.flush(self.db, secret_path=self.secret)
        self.assertEqual(result["reason"], "not_configured")
        self.assertEqual(result["pending"], 1)

    def test_invalid_token_stops_fanout(self):
        mod.enqueue(self.db, "TEST", "info", "test")
        calls = []
        def reject(token, payload, route):
            calls.append(route)
            return False, 401, 0
        with mock.patch.object(mod, "now", return_value=5000000000):
            result = mod.flush(self.db, reject, self.secret)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["reason"], "telegram_rejected_401")

    def test_router_route_is_not_labeled_sstp(self):
        self.assertEqual(mod.route_order("mihomo"), ["mihomo0", "awg0", "eth0"])
        self.assertEqual(mod.route_order("awg"), ["awg0", "mihomo0", "eth0"])
        self.assertNotIn("sstp", mod.ROUTES)

    def test_curl_token_not_in_argv_or_stderr(self):
        token = "12345678:" + "A" * 35
        def fake_run(argv, **kwargs):
            self.assertNotIn(token, " ".join(argv))
            self.assertIn(token, kwargs["input"])
            self.assertIn("if!awg0", argv)
            return mock.Mock(returncode=0, stdout='{"ok":true}\n200', stderr="")
        with mock.patch.object(mod.subprocess, "run", side_effect=fake_run):
            self.assertEqual(mod.curl_api(token, {"chat_id": "12", "text": "hello"}, "awg0"), (True, 200, 0))

    def test_telegram_retry_after(self):
        with mock.patch.object(mod.subprocess, "run", return_value=mock.Mock(
            returncode=0, stdout='{"ok":false,"parameters":{"retry_after":95}}\n429', stderr="")):
            self.assertEqual(mod.curl_api("12345678:" + "A"*35, {"text":"x"}, "eth0"),
                             (False, 429, 95))

    def test_quota_drops_oldest_info_before_critical(self):
        old = mod.MAX_PENDING
        with mock.patch.object(mod, "MAX_PENDING", 3):
            mod.enqueue(self.db, "VPN_LOST", "critical", "alarm 1", timestamp=1000)
            mod.enqueue(self.db, "BOOT", "info", "info 1", timestamp=1000)
            mod.enqueue(self.db, "BOOT", "info", "info 2", timestamp=1000)
            mod.enqueue(self.db, "BOOT", "info", "info 3", timestamp=1000)
        remaining = [v[0] for v in self.db.execute("SELECT message FROM events")]
        self.assertIn("alarm 1", remaining)
        self.assertNotIn("info 1", remaining)


if __name__ == "__main__":
    unittest.main()
