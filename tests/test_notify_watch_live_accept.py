"""Isolated regression tests for real-systemd AWG Notify Watch acceptance gate."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "awg-notify-watch-live-accept.py"
spec = importlib.util.spec_from_file_location("notify_watch_live_accept", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class WatchLiveAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="watch-accept-tests-")
        self.addCleanup(self.temp.cleanup)
        self.db = sqlite3.connect(str(Path(self.temp.name) / "events.sqlite3"))
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, message TEXT)")
        self.db.execute("INSERT INTO events(message) VALUES ('keep-event')")
        self.db.commit()

    def test_historical_down_reset_without_queue_mutation(self):
        old = {"watch_state": "down", "watch_count": "6",
               "watch_transport": "mihomo"}
        mod.write_watch_meta(self.db, old)
        recovered = mod.reset_false_down(self.db, "mihomo")
        self.assertEqual(recovered, old)
        self.assertEqual(mod.read_watch_meta(self.db), {
            "watch_state": "unknown", "watch_count": "0",
            "watch_transport": "mihomo"})
        self.assertEqual(self.db.execute("SELECT message FROM events").fetchall(),
                         [("keep-event",)])

    def test_transport_mismatch_refused_and_preserved(self):
        old = {"watch_state": "down", "watch_count": "4",
               "watch_transport": "awg"}
        mod.write_watch_meta(self.db, old)
        with self.assertRaises(ValueError):
            mod.reset_false_down(self.db, "mihomo")
        self.assertEqual(mod.read_watch_meta(self.db), old)

    def test_restore_exact_meta_keys(self):
        old = {"watch_state": "suspect", "watch_transport": "mihomo"}
        mod.write_watch_meta(self.db, old)
        mod.reset_false_down(self.db, "mihomo")
        mod.write_watch_meta(self.db, old)
        self.assertEqual(mod.read_watch_meta(self.db), old)

    def test_acceptance_guards_keep_timer_off(self):
        source = SOURCE.read_text()
        self.assertIn("AF_NETLINK", source)
        self.assertIn("if not timer_off()", source)
        self.assertIn("watch_state", source)
        self.assertIn("events.sqlite3", source)
        self.assertIn("ROOT_REQUIRED", source)
        self.assertIn("NOTIFY_WATCH_TIMER=DISABLED", source)
        self.assertNotIn("systemctl\", \"enable", source)
        self.assertNotIn("deleteWebhook", source)
        self.assertNotIn("ip route", source)
        self.assertNotIn("iptables", source)


if __name__ == "__main__":
    unittest.main()
