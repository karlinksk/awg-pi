#!/usr/bin/env python3
"""Test-Pi-only Telegram checkbox/producer matrix and a single real AWG-bound TEST.

Never edits real event preferences, queue, bot credentials, VPN/route/services,
or MikroTik. The isolated queue is under /run and destroyed after testing.
"""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest import mock
import hashlib

NOTIFIER = Path("/usr/local/sbin/awg-notify")
NOTIFIER_SHA = "6eab64b8ea3dab459130c32516b693c049f17d1d0e631c1d17a76157ac0139a3"
NAMES = ("VPN_LOST", "VPN_RESTORED", "BOOT", "DAILY_REPORT",
         "NODE_SWITCH", "TRANSPORT_SWITCH")
TEST_MESSAGE = (
    "ТЕСТ AWG Pi Gateway — проверка Telegram после failover. "
    "6 переключателей проверены с включением и выключением "
    "на изолированной очереди. Транспорт AWG активен; "
    "этот текст НЕ означает реальную аварию или переключение."
)


def check_source():
    if NOTIFIER.is_symlink() or not NOTIFIER.is_file():
        raise RuntimeError("Unexpected notifier file")
    if hashlib.sha256(NOTIFIER.read_bytes()).hexdigest() != NOTIFIER_SHA:
        raise RuntimeError("Installed notifier SHA mismatch")


def imported_notifier():
    loader = importlib.machinery.SourceFileLoader("awg_notify_matrix", str(NOTIFIER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def emit_cli(module, kind, text, key):
    captured = io.StringIO()
    args = ["emit", "--kind", kind, "--severity", "info",
            "--text", text, "--key", key]
    with contextlib.redirect_stdout(captured):
        ret = module.main(args)
    if ret != 0:
        raise RuntimeError("isolated emit CLI failed")
    lines = captured.getvalue().strip().splitlines()
    if not lines or lines[-1] not in ("NOTIFY_QUEUED=yes",
                                       "NOTIFY_QUEUED=disabled"):
        raise RuntimeError("unexpected emitter result")
    return lines[-1]


def produced_events(module, conn, kind, secret):
    if kind in ("VPN_LOST", "VPN_RESTORED"):
        with mock.patch.object(module, "SECRET_PATH", secret):
            first = module.observe_transport(conn, "awg", lambda _: False)
            second = module.observe_transport(conn, "awg", lambda _: False)
            if (first, second) != ("suspect", "down"):
                raise RuntimeError("Watch suppression/double-check failed")
            if kind == "VPN_RESTORED":
                if module.observe_transport(conn, "awg", lambda _: True) != "up":
                    raise RuntimeError("Watch recovery state mismatch")
    elif kind == "DAILY_REPORT":
        with mock.patch.object(module, "SECRET_PATH", secret), \
             mock.patch.object(module, "daily_snapshot",
                               return_value="ТЕСТ — ежедневная сводка"):
            module.enqueue_daily(conn)
    else:
        emit_cli(module, kind, "ТЕСТ — " + kind, "matrix:" + kind)
    return [row[0] for row in conn.execute(
        "SELECT kind FROM events ORDER BY id").fetchall()]


def run_matrix(module, folder, allow_rootless):
    fake_secret = folder / "fake-secret-exists-only"
    fake_secret.write_text("NOT-A-TELEGRAM-SECRET", encoding="utf-8")
    fake_secret.chmod(0o600)
    prefs = folder / "events-policy.json"
    original_open = module.open_db
    original_event_enabled = module.event_enabled
    uid = os.geteuid()

    def local_event_enabled(kind):
        return original_event_enabled(kind, path=prefs, owner_uid=uid)

    with mock.patch.object(module, "PREFERENCES_PATH", prefs), \
         mock.patch.object(module, "event_enabled",
                           side_effect=local_event_enabled), \
         mock.patch.object(module, "check_root", return_value=None):
        assert tuple(module.PREFERENCE_TYPES) == NAMES
        for kind in NAMES:
            for enabled in (False, True):
                module.save_preferences({kind} if enabled else set(),
                                        path=prefs, owner_uid=uid)
                local_db = folder / ("case-" + kind + "-" +
                                     ("on" if enabled else "off") + ".sqlite3")
                conn = original_open(local_db)
                with mock.patch.object(module, "open_db",
                                       side_effect=lambda: original_open(local_db)):
                    rows = produced_events(module, conn, kind, fake_secret)
                conn.close()
                expected = [kind] if enabled else []
                if rows != expected:
                    raise RuntimeError("MATRIX_FAILED: " + kind + " " +
                                       ("ON" if enabled else "OFF"))
            print("SWITCH_" + kind + "=ON_PASS_OFF_PASS")

        for enabled in (False, True):
            # Automatic failover maps onto the TRANSPORT_SWITCH checkbox.
            module.save_preferences(
                {"TRANSPORT_SWITCH"} if enabled else set(),
                path=prefs, owner_uid=uid)
            db_path = folder / ("alias-" + str(enabled) + ".sqlite3")
            conn = original_open(db_path)
            with mock.patch.object(module, "open_db",
                                   side_effect=lambda: original_open(db_path)):
                result = emit_cli(module, "TRANSPORT_FAILOVER",
                                  "ТЕСТ — автоматический переход",
                                  "matrix:alias")
            rows = [row[0] for row in conn.execute(
                "SELECT kind FROM events").fetchall()]
            conn.close()
            if rows != (["TRANSPORT_FAILOVER"] if enabled else []):
                raise RuntimeError("TRANSPORT_FAILOVER_ALIAS_FILTER_FAILED")
        print("TRANSPORT_FAILOVER_ALIAS=ON_PASS_OFF_PASS")

        # Both old warnings and test message are unaffected by user switches.
        module.save_preferences(set(), path=prefs, owner_uid=uid)
        db_path = folder / "bypass.sqlite3"
        conn = original_open(db_path)
        with mock.patch.object(module, "open_db",
                               side_effect=lambda: original_open(db_path)):
            assert emit_cli(module, "TEST", "ТЕСТ — системная доставка",
                            "matrix:test") == "NOTIFY_QUEUED=yes"
        conn.close()
        print("TEST_EVENT_WITH_SWITCHES_OFF=PASS")

        module.save_preferences({"BOOT"}, path=prefs, owner_uid=uid)
        if prefs.stat().st_mode & 0o077:
            raise RuntimeError("Preference file is not root/private 0600")
        if module.load_preferences(path=prefs, owner_uid=uid)["BOOT"] is not True:
            raise RuntimeError("Preference persistence failed")
        print("PREFERENCES_ATOMIC_PERSISTENCE=PASS")
    print("ISOLATED_MATRIX=PASS_6_SWITCHES_PLUS_FAILOVER_ALIAS")


def live_awg_send(module, folder):
    if os.geteuid() != 0:
        raise RuntimeError("Live send requires root")
    import subprocess
    route = subprocess.run(
        ["/usr/local/sbin/awg-selection", "status"], capture_output=True,
        text=True, timeout=5, check=False)
    if route.returncode != 0 or "Current transport: awg" not in route.stdout:
        raise RuntimeError("Refusing live send: AWG is not selected")
    units = subprocess.run(["systemctl", "is-active", "awg-quick@awg0.service"],
                           capture_output=True, text=True, timeout=5)
    if units.stdout.strip() != "active":
        raise RuntimeError("Refusing live send: AWG service not active")
    # Never touch root's real notification queue or emit to it.
    queue_path = folder / "send-only.sqlite3"
    conn = module.open_db(queue_path)
    try:
        assert module.enqueue(conn, "TEST", "info", TEST_MESSAGE,
                              key="awg-matrix-live-send")
        with mock.patch.object(module, "route_order",
                               side_effect=lambda active="": ["awg0"]):
            report = module.flush(conn, active="awg", limit=1)
        print("LIVE_ROUTE=awg0_ONLY_NO_ETH0_DIRECT")
        print("LIVE_SEND=" + ("PASS" if
              report == {"sent": 1, "pending": 0, "reason": "sent"}
              else "FAIL"))
        print("LIVE_SEND_STATUS=sent_" + str(report["sent"]) +
              "_pending_" + str(report["pending"]) +
              "_reason_" + report["reason"])
        return report == {"sent": 1, "pending": 0, "reason": "sent"}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    check_source()
    folder = Path(tempfile.mkdtemp(prefix="awg-notify-event-matrix-", dir="/run"
                                   if os.geteuid() == 0 else None))
    folder.chmod(0o700)
    try:
        module = imported_notifier()
        run_matrix(module, folder, allow_rootless=args.offline)
        if args.offline:
            print("LIVE_SEND=SKIPPED_OFFLINE")
            return 0
        print("PRODUCTION_PREFERENCES=NOT_MODIFIED")
        print("PRODUCTION_QUEUE=NOT_MODIFIED")
        print("PRODUCTION_BOT_SECRET=NOT_MODIFIED")
        actual = module.load_preferences()
        for kind in NAMES:
            print("CURRENT_PREF_" + kind + "=" +
                  ("on" if actual[kind] else "off"))
        ok = live_awg_send(module, folder)
        return 0 if ok else 4
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # No secret material is ever included in diagnostic exceptions.
        print("MATRIX_TEST=FAIL_SAFE:" + type(e).__name__, file=sys.stderr)
        sys.exit(2)
