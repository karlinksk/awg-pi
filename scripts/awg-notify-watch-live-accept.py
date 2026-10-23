#!/usr/bin/env python3
"""Test Pi ONLY: prove fixed AWG Notify watch under its real systemd unit.

No VPN/MikroTik/PBR/SSH/DNS changes. The historically false 'down' is
rebaselined to 'unknown' to avoid a fake VPN_RESTORED message. Queue preserved.
Watch timer stays disabled. Creates a root-only /run SQLite backup for rollback.
"""
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile

DB = Path("/var/lib/awg-pbr/notify/events.sqlite3")
WATCH = "awg-notify-watch.service"
TIMER = "awg-notify-watch.timer"
META_KEYS = ("watch_state", "watch_count", "watch_transport")


def command(*argv, timeout=15):
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def timer_off():
    enabled = command("systemctl", "is-enabled", TIMER)
    active = command("systemctl", "is-active", TIMER)
    return bool(enabled and active and enabled.returncode != 0
                and active.returncode != 0)


def read_watch_meta(db):
    return dict(db.execute(
        "SELECT key,value FROM meta WHERE key IN (?,?,?)", META_KEYS))


def write_watch_meta(db, state):
    with db:
        for key in META_KEYS:
            if key in state:
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                           (key, state[key]))
            else:
                db.execute("DELETE FROM meta WHERE key=?", (key,))


def reset_false_down(db, transport):
    before = read_watch_meta(db)
    if before.get("watch_transport", transport) != transport:
        raise ValueError("transport changed since old watch observations")
    if before.get("watch_state", "unknown") not in ("down", "suspect", "unknown", "up"):
        raise ValueError("unknown previous observer state")
    write_watch_meta(db, {"watch_state": "unknown", "watch_count": "0",
                          "watch_transport": transport})
    return before


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    if not timer_off():
        print("REFUSE_WATCH_TIMER_MUST_BE_DISABLED")
        return 2

    props = command("systemctl", "show", WATCH, "-p", "RestrictAddressFamilies",
                    "--value")
    unit = command("systemctl", "cat", WATCH)
    if not props or props.returncode or "AF_NETLINK" not in props.stdout.split():
        print("REFUSE_UNIT_MISSING_NETLINK")
        return 2
    if not unit or unit.returncode or "ExecStart=/usr/local/sbin/awg-notify watch" not in unit.stdout:
        print("REFUSE_UNEXPECTED_WATCH_UNIT")
        return 2

    selected = command("/usr/local/sbin/awg-transport", "get")
    if not selected or selected.returncode or selected.stdout.strip() != "mihomo":
        print("REFUSE_SELECTED_TRANSPORT_NOT_MIhOMO")
        return 2
    health = command("/usr/local/sbin/awg-transport", "check", "mihomo", timeout=20)
    if not health or health.returncode or health.stdout.strip() != "healthy":
        print("REFUSE_ROOT_MIhOMO_HEALTH_NOT_PASS")
        return 2

    try:
        info = DB.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            print("REFUSE_UNSAFE_NOTIFY_DB")
            return 2
    except OSError:
        print("REFUSE_NOTIFY_DB_UNAVAILABLE")
        return 2

    os.umask(0o077)
    backup_dir = Path(tempfile.mkdtemp(prefix="awg-notify-watch-accept-", dir="/run"))
    backup_file = backup_dir / "events.sqlite3"
    with sqlite3.connect(str(DB), timeout=10) as db:
        db.execute("PRAGMA busy_timeout=10000")
        with sqlite3.connect(str(backup_file)) as backup:
            db.backup(backup)
        backup_file.chmod(0o600)

        before = read_watch_meta(db)
        try:
            initial_last_id = db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
            reset_false_down(db, "mihomo")
            print("OLD_FALSE_DOWN_BASELINE=CLEARED")
            run = command("systemctl", "start", WATCH, timeout=40)
            after = read_watch_meta(db)
            last_id = db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
            selected_after = command("/usr/local/sbin/awg-transport", "get")
            passed = (run is not None and run.returncode == 0
                      and after.get("watch_state") == "up"
                      and after.get("watch_count") == "0"
                      and after.get("watch_transport") == "mihomo"
                      and last_id == initial_last_id
                      and selected_after is not None and selected_after.returncode == 0
                      and selected_after.stdout.strip() == "mihomo"
                      and timer_off())
            if not passed:
                write_watch_meta(db, before)
                print("WATCH_RUNTIME=NOT_PASS; ORIGINAL_WATCH_META_RESTORED")
                print("NOTIFY_WATCH_TIMER=DISABLED")
                return 1
        except (sqlite3.Error, ValueError, OSError):
            write_watch_meta(db, before)
            print("WATCH_RUNTIME=NOT_PASS; ORIGINAL_WATCH_META_RESTORED")
            print("NOTIFY_WATCH_TIMER=DISABLED")
            return 1

    print("WATCH_RUNTIME=PASS_UP")
    print("NOTIFY_EVENTS_NEWLY_QUEUED=0")
    print("NOTIFY_WATCH_TIMER=DISABLED")
    print("TRANSPORT_CHANGE=NONE")
    print("UNIT_DB_BACKUP=" + str(backup_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
