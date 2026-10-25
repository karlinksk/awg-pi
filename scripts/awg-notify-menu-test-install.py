#!/usr/bin/env python3
"""Test-Pi ONLY: pin-verified passive menu/Telegram pairing upgrade.

Does not start/restart/stop any gateway service, alter network config, or
enable notification timers. Only replaces /usr/local/sbin/awg-menu and an
optional, root-owned pair-repair executable; exact original menu pinned.
"""
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path("/home/karlinks/awg-notify-fixture")
MENU_SRC = ROOT / "stage/awg-menu"
PAIR_SRC = ROOT / "scripts/awg-notify-pair-repair.py"
MENU_DST = Path("/usr/local/sbin/awg-menu")
PAIR_DST = Path("/usr/local/sbin/awg-notify-pair-repair")
BACKUP_ROOT = Path("/var/backups/awg-gateway")
MENU_ACCEPTED = {
    # Originally deployed live-menu baseline
    "1c84248658e43462c9f6d4a740a5c4ad001a60a2e1d4e89c8fa76fb8fb6268fd",
    # Operator-installed first Telegram merge (DC #9, Telegram #10)
    "bcc82ecbf97cc0c1d61fdec8529180e41f3a4f4596c202a3797a3ce3bf155057",
    # Already-installed final complete source, for rerunnable idempotent checks
    "1e46c5cc26f27ed6ac9b1f60c923cdaac29e4fe3bbd6d459ba3618871168c1cb",
}
MENU_NEW = "1e46c5cc26f27ed6ac9b1f60c923cdaac29e4fe3bbd6d459ba3618871168c1cb"
PAIR_NEW = "5b9ee5f72a94670cd9e04a712ab9a729fdbfcd054599781fb9706a0bc34a1d4c"
CORE_SERVICES = ("ssh.service", "dnsmasq.service",
                 "awg-pbr-health.service", "awg-selection-monitor.service",
                 "awg-mihomo.service")
TIMERS = ("awg-notify-flush.timer", "awg-notify-watch.timer",
          "awg-notify-daily.timer", "awg-notify-boot.service")


def cmd(*args, timeout=15):
    return subprocess.run(args, check=True, text=True, capture_output=True,
                          timeout=timeout).stdout.strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise RuntimeError("Refuse nonregular/symlink: " + str(path))
    return info


def snapshot():
    # Safe, non-secret fingerprint: do not print actual policy tables.
    return (
        tuple((svc, cmd("systemctl", "is-active", svc)) for svc in CORE_SERVICES),
        tuple((unit,
               cmd("systemctl", "is-enabled", unit) if
               subprocess.run(("systemctl", "is-enabled", unit),
                              capture_output=True).returncode == 0 else "disabled",
               cmd("systemctl", "is-active", unit) if
               subprocess.run(("systemctl", "is-active", unit),
                              capture_output=True).returncode == 0 else "inactive")
              for unit in TIMERS),
        cmd("ip", "-4", "rule", "show"),
        cmd("ip", "-4", "route", "show", "table", "100"),
        cmd("ip", "-4", "route", "show", "table", "101"),
    )


def atomic_executable(data, path, mode=0o755):
    handle, filename = tempfile.mkstemp(prefix=".awg-notify-stage-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(filename, 0, 0)
        os.chmod(filename, mode)
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    for src, expected in ((MENU_SRC, MENU_NEW), (PAIR_SRC, PAIR_NEW)):
        check_regular(src)
        if digest(src) != expected:
            print("REFUSED_SOURCE_HASH_MISMATCH=" + src.name)
            return 2
    info = check_regular(MENU_DST)
    if info.st_uid != 0 or digest(MENU_DST) not in MENU_ACCEPTED:
        print("REFUSED_DEPLOYED_MENU_HAS_CHANGED")
        return 2
    if PAIR_DST.exists():
        pair_info = check_regular(PAIR_DST)
        if pair_info.st_uid != 0:
            print("REFUSED_PAIR_HELPER_NOT_ROOT_OWNED")
            return 2
        old_pair = PAIR_DST.read_bytes()
    else:
        old_pair = None
    if cmd("bash", "-n", str(MENU_SRC)):
        raise RuntimeError("unexpected bash -n output")
    compile(PAIR_SRC.read_bytes(), str(PAIR_SRC), "exec")
    source = MENU_SRC.read_text()
    for phrase in (
        '9 "Desktop Commander — удалённый доступ"',
        '10 "Telegram — уведомления"',
        '10) notify_menu ;;',
        'first_transport_setup(){',
        'secondary_transport_setup(){',
        'use_scrollbar = OFF',
    ):
        if phrase not in source:
            print("REFUSED_MENU_CONTRACT")
            return 2

    before = snapshot()
    if any(state != "active" for _, state in before[0]):
        print("REFUSED_UNHEALTHY_CORE_SERVICE")
        return 2
    if "mihomo0" not in before[3] or "mihomo0" not in before[4]:
        print("REFUSED_UNEXPECTED_LIVE_ROUTING")
        return 2

    if digest(MENU_DST) == MENU_NEW and old_pair is not None and hashlib.sha256(old_pair).hexdigest() == PAIR_NEW:
        print("MENU_INSTALL=ALREADY_INSTALLED_TEST_PI_ONLY")
        print("CORE_SERVICES_AND_PBR=UNCHANGED")
        print("NOTIFY_TIMERS=UNCHANGED")
        return 0

    BACKUP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(
        prefix="telegram-menu-", dir=str(BACKUP_ROOT)))
    folder.chmod(0o700)
    (folder / "awg-menu.old").write_bytes(MENU_DST.read_bytes())
    (folder / "awg-menu.old").chmod(0o600)
    if old_pair is not None:
        (folder / "awg-notify-pair-repair.old").write_bytes(old_pair)
        (folder / "awg-notify-pair-repair.old").chmod(0o600)

    try:
        atomic_executable(MENU_SRC.read_bytes(), MENU_DST)
        atomic_executable(PAIR_SRC.read_bytes(), PAIR_DST, mode=0o700)
        if digest(MENU_DST) != MENU_NEW or digest(PAIR_DST) != PAIR_NEW:
            raise RuntimeError("installed checksum mismatch")
        if snapshot() != before:
            raise RuntimeError("live services, routes or timers changed")
    except Exception:
        atomic_executable((folder / "awg-menu.old").read_bytes(), MENU_DST)
        if old_pair is None:
            PAIR_DST.unlink(missing_ok=True)
        else:
            atomic_executable(old_pair, PAIR_DST, mode=0o700)
        print("MENU_INSTALL=ROLLED_BACK")
        print("BACKUP=" + str(folder))
        raise
    print("MENU_INSTALL=PASS_TEST_PI_ONLY")
    print("MENU_SHA256=" + MENU_NEW)
    print("TELEGRAM_MENU_ITEM=10")
    print("DESKTOP_COMMANDER_ITEM=9")
    print("PAIR_REPAIR_HELPER=INSTALLED")
    print("CORE_SERVICES_AND_PBR=UNCHANGED")
    print("NOTIFY_TIMERS=UNCHANGED")
    print("BACKUP=" + str(folder))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print("MENU_INSTALL=FAIL_SAFE: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
