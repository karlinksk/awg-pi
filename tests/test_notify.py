"""No-network/rootless contract tests for AWG Notify."""
import importlib.util
import os
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
        self.preferences = self.folder / "events-policy.json"
        self.preferences_patch = mock.patch.object(mod, "PREFERENCES_PATH", self.preferences)
        self.preferences_patch.start()
        self.addCleanup(self.preferences_patch.stop)
        self.secret = self.folder / "telegram.json"
        self.secret.write_text(json.dumps({
            "token": "12345678:" + "A" * 35,
            "chat_id": "123456789"
        }))
        self.secret.chmod(0o600)

    def test_dedupe_and_expiry(self):
        self.assertTrue(mod.enqueue(self.db, "TEST", "info", "old -> new", "same", 1000))
        self.assertFalse(mod.enqueue(self.db, "TEST", "info", "old -> new", "same", 1100))
        self.assertTrue(mod.enqueue(self.db, "TEST", "info", "old -> new", "same", 1120))
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 2)


    def test_event_preferences_default_and_disabled_do_not_queue(self):
        self.assertEqual(mod.load_preferences(owner_uid=os.getuid()), mod.PREFERENCE_DEFAULTS)
        self.assertTrue(mod.event_enabled("VPN_LOST", owner_uid=os.getuid()))
        self.assertFalse(mod.event_enabled("NODE_SWITCH", owner_uid=os.getuid()))
        self.assertFalse(mod.event_enabled("TRANSPORT_FAILOVER", owner_uid=os.getuid()))
        # Production emit/watch/daily gates, rather than low-level enqueue(),
        # filter categories; enqueue remains an isolated queue primitive.
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.assertTrue(mod.enqueue(self.db, "TEST", "info", "keep"))
        mod.save_preferences({"BOOT", "NODE_SWITCH"}, self.preferences, owner_uid=os.getuid())
        self.assertEqual(self.preferences.stat().st_mode & 0o777, 0o600)
        self.assertTrue(mod.event_enabled("NODE_SWITCH", owner_uid=os.getuid()))
        self.assertFalse(mod.event_enabled("VPN_LOST", owner_uid=os.getuid()))
        self.assertTrue(mod.event_enabled("BOOT", owner_uid=os.getuid()))
        # Disabled categories are rejected by the producer-level gate.
        self.assertTrue(mod.enqueue(self.db, "NODE_SWITCH", "info", "allowed"))
        self.assertEqual(self.db.execute("SELECT kind FROM events ORDER BY id").fetchall(),
                         [("TEST",), ("NODE_SWITCH",)])

    def test_daily_and_watcher_respect_disabled_categories(self):
        mod.save_preferences({"BOOT"}, self.preferences, owner_uid=os.getuid())
        filter_with_uid = mod.event_enabled
        with mock.patch.object(mod, "event_enabled", side_effect=lambda kind: filter_with_uid(kind, owner_uid=os.getuid())), \
             mock.patch.object(mod, "SECRET_PATH", self.secret), \
             mock.patch.object(mod, "daily_snapshot", return_value="daily"), \
             mock.patch.object(mod.time, "strftime", return_value="2026-10-22"):
            self.assertFalse(mod.enqueue_daily(self.db))
            self.assertEqual(mod.observe_transport(self.db, "mihomo", lambda _: False), "suspect")
            self.assertEqual(mod.observe_transport(self.db, "mihomo", lambda _: False), "down")
            self.assertEqual(mod.observe_transport(self.db, "mihomo", lambda _: True), "up")
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_preferences_refuse_bad_policy_and_symlink(self):
        with self.assertRaises(ValueError):
            mod.save_preferences({"DANGEROUS"}, self.preferences, owner_uid=os.getuid())
        self.preferences.write_text('{"BOOT":"true"}')
        self.preferences.chmod(0o600)
        self.assertFalse(mod.event_enabled("BOOT", owner_uid=os.getuid()))
        with self.assertRaises(ValueError):
            mod.load_preferences(owner_uid=os.getuid())
        self.preferences.unlink()
        target = self.folder / "target.json"
        target.write_text("{}")
        self.preferences.symlink_to(target)
        with self.assertRaises(ValueError):
            mod.save_preferences({"BOOT"}, self.preferences, owner_uid=os.getuid())
        self.assertFalse(mod.event_enabled("BOOT", owner_uid=os.getuid()))

    def test_preferences_keep_existing_queue_and_atomic_update(self):
        mod.enqueue(self.db, "BOOT", "info", "pending boot")
        mod.save_preferences(set(), self.preferences, owner_uid=os.getuid())
        self.assertEqual(self.db.execute("SELECT kind FROM events").fetchall(), [("BOOT",)])
        self.assertFalse(mod.event_enabled("BOOT", owner_uid=os.getuid()))
        mod.save_preferences(set(mod.PREFERENCE_TYPES), self.preferences, owner_uid=os.getuid())
        self.assertTrue(mod.event_enabled("BOOT", owner_uid=os.getuid()))
        self.assertEqual(list(self.folder.glob(".events-policy-*")), [])

    def test_six_checkbox_matrix_emits_only_selected_kind(self):
        # Simulate public CLI emission without touching configured bot, network,
        # selected transport, or the production queue.
        for category in mod.PREFERENCE_TYPES:
            with self.subTest(category=category):
                case = self.folder / (category + ".json")
                alias = ("TRANSPORT_FAILOVER" if category == "TRANSPORT_SWITCH"
                         else category)
                mod.save_preferences({category}, case, owner_uid=os.getuid())
                self.assertTrue(mod.event_enabled(alias, path=case, owner_uid=os.getuid()))
                for other in mod.PREFERENCE_TYPES:
                    if other != category:
                        self.assertFalse(mod.event_enabled(other, path=case, owner_uid=os.getuid()))
                mod.save_preferences(set(), case, owner_uid=os.getuid())
                self.assertFalse(mod.event_enabled(alias, path=case, owner_uid=os.getuid()))
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_watch_both_categories_are_independent(self):
        checker = mod.event_enabled
        with mock.patch.object(mod, "event_enabled", side_effect=
                               lambda k: checker(k, owner_uid=os.getuid())), \
             mock.patch.object(mod, "SECRET_PATH", self.secret):
            mod.save_preferences({"VPN_LOST"}, self.preferences, owner_uid=os.getuid())
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: False), "suspect")
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: False), "down")
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: True), "up")
            self.assertEqual(self.db.execute("SELECT kind FROM events").fetchall(),
                             [("VPN_LOST",)])
            mod.save_preferences({"VPN_RESTORED"}, self.preferences, owner_uid=os.getuid())
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: False), "suspect")
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: False), "down")
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda _: True), "up")
            self.assertEqual(self.db.execute("SELECT kind FROM events").fetchall(),
                             [("VPN_LOST",), ("VPN_RESTORED",)])

    def test_emit_cli_gate_with_enabled_and_disabled_category(self):
        # Verify the actual emit command code path in an isolated test DB.
        import io
        from contextlib import redirect_stdout
        real_open = mod.open_db
        case_db = self.folder / "cli-test" / "events.sqlite3"
        checker = mod.event_enabled
        with mock.patch.object(mod, "check_root", return_value=None), \
             mock.patch.object(mod, "open_db", side_effect=lambda: real_open(case_db)), \
             mock.patch.object(mod, "event_enabled", side_effect=
                               lambda k: checker(k, owner_uid=os.getuid())):
            mod.save_preferences({"TRANSPORT_SWITCH"}, self.preferences,
                                 owner_uid=os.getuid())
            with redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(mod.main(["emit", "--kind", "TRANSPORT_FAILOVER",
                                           "--text", "[ТЕСТ] переключение AWG"]), 0)
            self.assertIn("NOTIFY_QUEUED=yes", printed.getvalue())
            mod.save_preferences(set(), self.preferences, owner_uid=os.getuid())
            with redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(mod.main(["emit", "--kind", "TRANSPORT_FAILOVER",
                                           "--text", "[ТЕСТ] не отправлять"]), 0)
            self.assertIn("NOTIFY_QUEUED=disabled", printed.getvalue())
        with real_open(case_db) as db:
            self.assertEqual(db.execute("SELECT kind FROM events").fetchall(),
                             [("TRANSPORT_FAILOVER",)])

    def test_invalid_inputs(self):
        for kind, sev, msg in [("BAD", "info", "x"), ("BOOT", "bad", "x"),
                               ("BOOT", "info", ""), ("BOOT", "info", "z" * 3001)]:
            with self.assertRaises(ValueError):
                mod.enqueue(self.db, kind, sev, msg)

    def test_secret_permissions(self):
        self.assertEqual(mod.load_secret(self.secret, owner_uid=os.getuid())[1], "123456789")
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
            result = mod.flush(self.db, failed, self.secret, active="awg", secret_uid=os.getuid())
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(calls, ["awg0", "mihomo0"])
        self.db.execute("UPDATE events SET next_try=0")
        self.db.commit()
        def delivered(token, payload, route):
            return (route == "mihomo0", 200 if route == "mihomo0" else 0, 0)
        with mock.patch.object(mod, "now", return_value=5000000001):
            result = mod.flush(self.db, delivered, self.secret, active="awg", secret_uid=os.getuid())
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(self.db.execute("SELECT value FROM meta WHERE key='last_success_route'").fetchone()[0], "mihomo0")

    def test_missing_credentials_preserves_queue(self):
        mod.enqueue(self.db, "BOOT", "info", "Restart")
        self.secret.unlink()
        result = mod.flush(self.db, secret_path=self.secret, secret_uid=os.getuid())
        self.assertEqual(result["reason"], "not_configured")
        self.assertEqual(result["pending"], 1)

    def test_invalid_token_stops_fanout(self):
        mod.enqueue(self.db, "TEST", "info", "test")
        calls = []
        def reject(token, payload, route):
            calls.append(route)
            return False, 401, 0
        with mock.patch.object(mod, "now", return_value=5000000000):
            result = mod.flush(self.db, reject, self.secret, secret_uid=os.getuid())
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["reason"], "telegram_rejected_401")

    def test_router_route_is_not_labeled_sstp(self):
        self.assertEqual(mod.route_order("mihomo", router_approved=False), ["mihomo0", "awg0"])
        self.assertEqual(mod.route_order("mihomo", router_approved=True), ["mihomo0", "awg0", "eth0"])
        self.assertEqual(mod.route_order("awg", router_approved=False), ["awg0", "mihomo0"])
        self.assertNotIn("sstp", mod.ROUTES)

    def test_router_approval_requires_root_only_attestation(self):
        marker = self.folder / "router-sstp-approved"
        self.assertFalse(mod.router_sstp_approved(marker, os.getuid()))
        marker.write_text("SSTP_VERIFIED_FAIL_CLOSED=1\n")
        marker.chmod(0o600)
        self.assertTrue(mod.router_sstp_approved(marker, os.getuid()))
        marker.chmod(0o644)
        self.assertFalse(mod.router_sstp_approved(marker, os.getuid()))
        marker.chmod(0o600)
        marker.write_text("SSTP_VERIFIED_FAIL_CLOSED=0\n")
        self.assertFalse(mod.router_sstp_approved(marker, os.getuid()))

    def test_pairing_matches_only_private_challenge(self):
        def getter(token, route):
            return [
                {"message": {"chat": {"id": 100, "type": "private"},
                             "from": {"id": 100}, "text": "/pair deadbeef"}},
                {"message": {"chat": {"id": 200, "type": "group"},
                             "from": {"id": 200}, "text": "/pair 123abc"}},
                {"message": {"chat": {"id": 300, "type": "private"},
                             "from": {"id": 300}, "text": "/pair 123abc"}},
            ]
        self.assertEqual(mod.find_pair_chat("token", "123abc", fetch=getter), "300")
        self.assertIsNone(mod.find_pair_chat("token", "missing", fetch=getter))

    def test_get_updates_curl_uses_stdin_not_argv(self):
        token = "12345678:" + "A" * 35
        def fake_run(argv, **kwargs):
            self.assertNotIn(token, " ".join(argv))
            self.assertIn(token, kwargs["input"])
            self.assertIn("if!awg0", argv)
            self.assertIn("getUpdates", kwargs["input"])
            self.assertIn("data =", kwargs["input"])
            return mock.Mock(returncode=0, stdout='{"ok":true,"result":[]}' + chr(10) + '200')
        with mock.patch.object(mod.subprocess, "run", side_effect=fake_run):
            self.assertEqual(mod._receive_pairing_updates(token, "awg0"), [])

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

    def test_passive_selected_transport_outage_and_recovery(self):
        with mock.patch.object(mod, "SECRET_PATH", self.secret):
            bad = lambda value: False
            good = lambda value: True
            self.assertEqual(mod.observe_transport(self.db, "awg", bad), "suspect")
            self.assertEqual(mod.observe_transport(self.db, "awg", bad), "down")
            self.assertEqual(mod.observe_transport(self.db, "awg", bad), "down")
            self.assertEqual(mod.observe_transport(self.db, "awg", good), "up")
        events = [row[0] for row in self.db.execute("SELECT kind FROM events ORDER BY id")]
        self.assertEqual(events, ["VPN_LOST", "VPN_RESTORED"])

    def test_passive_watch_skips_unconfigured(self):
        with mock.patch.object(mod, "SECRET_PATH", self.secret):
            self.assertEqual(mod.observe_transport(self.db, "unconfigured", lambda x: False),
                             "unconfigured")
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_passive_watch_resets_failures_on_backend_change(self):
        with mock.patch.object(mod, "SECRET_PATH", self.secret):
            self.assertEqual(mod.observe_transport(self.db, "mihomo", lambda x: False),
                             "suspect")
            self.assertEqual(mod.observe_transport(self.db, "awg", lambda x: False),
                             "suspect")
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_daily_report_once_per_day_without_credentials_leak(self):
        with mock.patch.object(mod, "SECRET_PATH", self.secret), \
             mock.patch.object(mod, "daily_snapshot", return_value="Состояние: норма"), \
             mock.patch.object(mod.time, "strftime", return_value="2026-10-22"):
            self.assertTrue(mod.enqueue_daily(self.db))
            self.assertFalse(mod.enqueue_daily(self.db))
        queued = self.db.execute("SELECT kind,message FROM events").fetchall()
        self.assertEqual(queued, [("DAILY_REPORT", "Состояние: норма")])

    def test_daily_report_unconfigured_is_silent(self):
        self.secret.unlink()
        with mock.patch.object(mod, "SECRET_PATH", self.secret):
            self.assertFalse(mod.enqueue_daily(self.db))
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_daily_report_uses_sanitized_read_only_status(self):
        result = mod.daily_snapshot()
        self.assertIn("Ежедневная сводка AWG Pi Gateway", result)
        self.assertIn("Температура CPU:", result)
        self.assertIn("RAM:", result)
        self.assertIn("Транспорт (выбранный, не подтверждение HTTPS):", result)
        self.assertNotIn("bot", result.lower())

    def test_batch_limit_two(self):
        import inspect
        self.assertEqual(inspect.signature(mod.flush).parameters["limit"].default, 2)

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
