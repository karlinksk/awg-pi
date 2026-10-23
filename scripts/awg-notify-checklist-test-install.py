#!/usr/bin/env python3
"""Pinned test-Pi upgrade of Telegram checkbox menu + notifier only.

Read-only preflight of running gateway; keeps Matrix, DC, credentials,
existing queue and timer activation. Changes only 2 root-owned executables.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

HOME = Path("/home/karlinks/awg-notify-fixture/src")
BIN = Path("/usr/local/sbin")
BKP = Path("/var/backups/awg-gateway")
EXPECTED = {
    "awg-menu": (
        "fd991094b055a8e6d4177c7c1e4c4df805c95f194adf036aaca3b96a966a6959",
        "03fa77837a1c8c624562ec2722b06a42836c30b4c232440a3faf93d7dfeb5b85"),
    "awg-notify": (
        "e475f8af8ba4cec8886fe70e2ad9c84a0c2b7f444594bb2966c21f9fe52b3d94",
        "6eab64b8ea3dab459130c32516b693c049f17d1d0e631c1d17a76157ac0139a3")
}
SERVICES = ("ssh.service", "dnsmasq.service",
            "awg-pbr-health.service", "awg-selection-monitor.service",
            "awg-mihomo.service")
NOTIFY_UNITS = ("awg-notify-flush.timer", "awg-notify-watch.timer",
                "awg-notify-daily.timer", "awg-notify-boot.service")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def call(*args):
    return subprocess.run(args, text=True, check=False, capture_output=True, timeout=18)


def read_checked(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise RuntimeError("Unsafe file type")
    return path.read_bytes(), info


def snapshot():
    services = tuple((unit, call("systemctl", "is-active", unit).stdout.strip())
                     for unit in SERVICES)
    notify = tuple((unit,
                    call("systemctl", "is-enabled", unit).stdout.strip(),
                    call("systemctl", "is-active", unit).stdout.strip())
                   for unit in NOTIFY_UNITS)
    return (services, notify,
            call("ip", "-4", "rule", "show").stdout,
            call("ip", "-4", "route", "show", "table", "100").stdout,
            call("ip", "-4", "route", "show", "table", "101").stdout,
            call("/usr/local/sbin/awg-transport", "get").stdout.strip())


def atomic_write(dst, data):
    fd, name = tempfile.mkstemp(prefix=".awg-checklist-", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chown(name, 0, 0)
        os.chmod(name, 0o755)
        os.replace(name, dst)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED", file=sys.stderr)
        return 2
    images = {}
    originals = {}
    for filename, (old_sha, new_sha) in EXPECTED.items():
        data, stat_src = read_checked(HOME / filename if filename != "awg-notify" else HOME / "awg-notify.py")
        old_data, stat_old = read_checked(BIN / filename)
        if sha(data) != new_sha or sha(old_data) not in (old_sha, new_sha):
            print("REFUSE_CHECKSUM_CHANGED: " + filename)
            return 2
        if stat_old.st_uid != 0 or stat.S_IMODE(stat_old.st_mode) != 0o755:
            print("REFUSE_UNEXPECTED_OWNER_OR_MODE: " + filename)
            return 2
        images[filename], originals[filename] = data, old_data

    text = images["awg-menu"].decode("utf-8")
    for marker in ('notify_types_menu(){', '--checklist', 'preferences-set --enabled',
                   'appearance_menu(){', 'awg-matrix-compositor.py',
                   '9 "Desktop Commander', '10 "Telegram',
                   'first_transport_setup(){', 'secondary_transport_setup(){'):
        if marker not in text:
            print("REFUSE_MENU_CONTRACT")
            return 2
    if call("bash", "-n", str(HOME / "awg-menu")).returncode:
        print("REFUSE_MENU_SYNTAX")
        return 2
    compile(images["awg-notify"], str(HOME / "awg-notify.py"), "exec")

    old_state = snapshot()
    if any(value != "active" for _, value in old_state[0]):
        print("REFUSE_CORE_SERVICE_UNHEALTHY")
        return 2
    if not all("mihomo0" in route for route in old_state[3:5]):
        print("REFUSE_UNEXPECTED_GATEWAY_ROUTE")
        return 2

    if all(images[key] == originals[key] for key in images):
        print("CHECKLIST_INSTALL=ALREADY_INSTALLED")
        print("NETWORK_AND_NOTIFIER_UNCHANGED=YES")
        return 0
    BKP.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="telegram-checklist-", dir=str(BKP)))
    backup.chmod(0o700)
    for filename, data in originals.items():
        file = backup / filename
        file.write_bytes(data)
        file.chmod(0o600)

    try:
        for filename, data in images.items():
            atomic_write(BIN / filename, data)
        if any(sha(read_checked(BIN / key)[0]) != EXPECTED[key][1] for key in EXPECTED):
            raise RuntimeError("Destination hash mismatch")
        if snapshot() != old_state:
            raise RuntimeError("Service, route, timer or transport changed")
    except Exception:
        for filename, data in originals.items():
            atomic_write(BIN / filename, data)
        print("CHECKLIST_INSTALL=ROLLED_BACK")
        print("BACKUP=" + str(backup))
        raise

    print("CHECKLIST_INSTALL=PASS_TEST_PI_ONLY")
    print("TELEGRAM_EVENT_SWITCHES=6")
    print("MATRIX_AND_DESKTOP_COMMANDER=PRESERVED")
    print("NOTIFY_POLICY_FILE=UNMODIFIED")
    print("EXISTING_QUEUE_AND_BOT_SECRET=UNMODIFIED")
    print("NETWORK_AND_NOTIFIER_UNCHANGED=YES")
    print("BACKUP=" + str(backup))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired, UnicodeError) as exc:
        print("CHECKLIST_INSTALL=FAIL_SAFE: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
