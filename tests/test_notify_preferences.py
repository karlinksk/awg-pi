"""Telegram event switches: persistence, queue filtering and safety."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "src" / "awg-notify.py"
spec = importlib.util.spec_from_file_location("notify_prefs", MODULE)
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)


class NotificationPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "events-policy.json"
        self.owner = os.getuid()
        patch = mock.patch.object(notify, "PREFERENCES_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)
        self.db = notify.open_db(self.folder / "db" / "events.sqlite3")
        self.addCleanup(self.db.close)

    def test_upgraded_install_keeps_existing_alerts(self):
        values = notify.load_preferences(owner_uid=self.owner)
        for key in ("VPN_LOST", "VPN_RESTORED", "BOOT", "DAILY_REPORT"):
            self.assertIs(values[key], True)
        for key in ("NODE_SWITCH", "TRANSPORT_SWITCH"):
            self.assertIs(values[key], False)

    def test_atomic_save_and_reload_check_permissions(self):
        enabled = {"VPN_LOST", "NODE_SWITCH"}
        notify.save_preferences(enabled, owner_uid=self.owner)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual({k for k,v in notify.load_preferences(owner_uid=self.owner).items() if v}, enabled)
        self.assertFalse(notify.event_enabled("TRANSPORT_FAILOVER", owner_uid=self.owner))
        self.assertTrue(notify.event_enabled("NODE_SWITCH", owner_uid=self.owner))
        self.assertFalse(notify.event_enabled("DAILY_REPORT", owner_uid=self.owner))

    def test_refuse_invalid_or_symlink_policy(self):
        with self.assertRaises(ValueError):
            notify.save_preferences({"UNKNOWN"}, owner_uid=self.owner)
        other = self.folder / "other.json"
        other.write_text("{}")
        self.path.symlink_to(other)
        with self.assertRaises(ValueError):
            notify.save_preferences({"BOOT"}, owner_uid=self.owner)
        self.assertFalse(notify.event_enabled("VPN_LOST", owner_uid=self.owner))

    def test_no_queued_alert_when_watch_category_off(self):
        notify.save_preferences(set(), owner_uid=self.owner)
        secret = self.folder / "telegram.json"
        secret.write_text("{}")
        with mock.patch.object(notify, "SECRET_PATH", secret), \
             mock.patch.object(notify, "event_enabled",
                               side_effect=lambda k, *a: False):
            self.assertEqual(notify.observe_transport(self.db, "mihomo", lambda x: False), "suspect")
            self.assertEqual(notify.observe_transport(self.db, "mihomo", lambda x: False), "down")
            self.assertEqual(notify.observe_transport(self.db, "mihomo", lambda x: True), "up")
            self.assertFalse(notify.enqueue_daily(self.db))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_existing_queue_not_deleted_by_preference_changes(self):
        notify.enqueue(self.db, "VPN_LOST", "critical", "queued before disable")
        notify.save_preferences(set(), owner_uid=self.owner)
        self.assertEqual(self.db.execute("SELECT kind FROM events").fetchall(), [("VPN_LOST",)])

    def test_cli_guarded_input(self):
        source = MODULE.read_text()
        self.assertIn('sub.add_parser("preferences-set")', source)
        self.assertIn("NOTIFY_PREFERENCES=SAVED", source)
        self.assertIn("PREFERENCE_KIND_MAP", source)
        menu = (MODULE.parents[0] / "awg-menu").read_text()
        self.assertIn("--separate-output --checklist", menu)
        self.assertIn('4 "Типы уведомлений [галочки]"', menu)
        self.assertIn('4) notify_types_menu ;;', menu)
        self.assertIn("awg-matrix-compositor.py", menu)
        self.assertIn('9 "Telegram — уведомления"', menu)


if __name__ == "__main__":
    unittest.main()
