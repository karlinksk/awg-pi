#!/usr/bin/env python3
"""Install only deduplicated Telegram menu on authorized AWG Pi test stand.

This does NOT activate, stop, or modify Telegram timers or any VPN subsystem.
All runtime changes occur only when the user later selects a menu action.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

SRC = Path("/home/karlinks/awg-notify-fixture/src/awg-menu")
DST = Path("/usr/local/sbin/awg-menu")
BACKUPS = Path("/var/backups/awg-gateway")
OLD_SHA = "03fa77837a1c8c624562ec2722b06a42836c30b4c232440a3faf93d7dfeb5b85"
NEW_SHA = "d12c44952db7ba1270b0f71cc48cb0947994f0bd454eff3a0f84b7e73aa2dc53"
SERVICES = ("ssh.service", "dnsmasq.service", "awg-pbr-health.service",
            "awg-selection-monitor.service", "awg-quick@awg0.service")
NOTIFY_UNITS = ("awg-notify-watch.timer", "awg-notify-flush.timer",
                "awg-notify-daily.timer", "awg-notify-boot.service")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise RuntimeError("Refused nonregular file")
    return path.read_bytes(), info


def call(*args):
    res = subprocess.run(args, capture_output=True, text=True, timeout=12,
                         check=False)
    if res.returncode:
        raise RuntimeError("Read-only check failed: " + args[0])
    return res.stdout.strip()


def snapshot():
    return (
        tuple((s, subprocess.run(("systemctl", "is-active", s),
                     capture_output=True, text=True, timeout=5).stdout.strip())
              for s in SERVICES),
        tuple((unit, subprocess.run(("systemctl", "is-enabled", unit),
                        capture_output=True, text=True, timeout=5).stdout.strip())
              for unit in NOTIFY_UNITS),
        call("ip", "-4", "rule", "show"),
        call("ip", "-4", "route", "show", "table", "100"),
        call("ip", "-4", "route", "show", "table", "101"),
    )


def atomic_menu(content):
    handle, temp = tempfile.mkstemp(prefix=".awg-menu-dedupe-", dir=DST.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o755)
        os.replace(temp, DST)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    staged, _ = regular(SRC)
    current, state = regular(DST)
    if digest(staged) != NEW_SHA or digest(current) not in (OLD_SHA, NEW_SHA):
        print("MENU_DEDUPE=REFUSED_HASH_MISMATCH")
        return 2
    if state.st_uid != 0 or stat.S_IMODE(state.st_mode) != 0o755:
        print("MENU_DEDUPE=REFUSED_OWNERSHIP")
        return 2
    if not (
        b'notify_sync_daily_schedule(){' in staged and
        b'notify_types_menu(){' in staged and
        b'appearance_menu(){' in staged and
        b'first_transport_setup(){' in staged and
        b'9 "Desktop Commander' in staged and
        b'10 "Telegram' in staged and
        '4 "Типы уведомлений [галочки]"' in staged.decode("utf-8") and
        '6 "Исправить привязку чата"' in staged.decode("utf-8") and
        '6 "Выключить ежедневную сводку"' not in staged.decode("utf-8") and
        b'--title "Telegram"' in staged
    ):
        print("MENU_DEDUPE=REFUSED_CONTRACT")
        return 2
    call("bash", "-n", str(SRC))
    before = snapshot()
    if any(status != "active" for _, status in before[0]):
        print("MENU_DEDUPE=REFUSED_UNHEALTHY_CORE")
        return 2
    if "awg0" not in before[3] or "awg0" not in before[4]:
        print("MENU_DEDUPE=REFUSED_ACTIVE_ROUTE_NOT_AWG")
        return 2
    if digest(current) == NEW_SHA:
        print("MENU_DEDUPE=ALREADY_INSTALLED")
        print("SERVICES_ROUTES_TIMERS=UNCHANGED")
        return 0

    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="telegram-menu-dedupe-", dir=BACKUPS))
    backup.chmod(0o700)
    copy = backup / "awg-menu.before"
    copy.write_bytes(current)
    copy.chmod(0o600)
    print("BACKUP=" + str(backup), flush=True)
    try:
        atomic_menu(staged)
        if digest(regular(DST)[0]) != NEW_SHA:
            raise RuntimeError("Menu checksum mismatch after replacement")
        if snapshot() != before:
            raise RuntimeError("Gateway, DNS or notifier activation changed")
    except Exception:
        atomic_menu(current)
        print("MENU_DEDUPE=ROLLED_BACK")
        raise
    print("MENU_DEDUPE=PASS_TEST_PI_ONLY")
    print("TELEGRAM_ITEMS=1_SETUP,2_TEST,3_DELIVERY,4_TYPES,5_STATUS,6_PAIR,0_BACK")
    print("MATRIX_AND_DESKTOP_COMMANDER=PRESERVED")
    print("SERVICES_ROUTES_TIMERS=UNCHANGED")
    print("USER_PREFERENCES_BOT_QUEUE=UNCHANGED")
    print("AWG_FAILOVER_HOOKS=NOT_TOUCHED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("MENU_DEDUPE=FAIL_SAFE_" + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
