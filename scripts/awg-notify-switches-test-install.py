#!/usr/bin/env python3
"""Test Pi only. Install pinned Telegram event preferences and UI; no VPN changes.

Requires explicit sudo from operator. Does not open/edit Telegram token, queue
or any gateway policy. Backs up only two executables, restores on failure.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

SRC = Path("/home/karlinks/awg-notify-fixture/src")
DST = Path("/usr/local/sbin")
EXPECTED_CURRENT = {
    "awg-menu": "fd991094b055a8e6d4177c7c1e4c4df805c95f194adf036aaca3b96a966a6959",
    "awg-notify": "e475f8af8ba4cec8886fe70e2ad9c84a0c2b7f444594bb2966c21f9fe52b3d94",
}
EXPECTED_NEW = {
    "awg-menu": "03fa77837a1c8c624562ec2722b06a42836c30b4c232440a3faf93d7dfeb5b85",
    "awg-notify": "937e4f21f8fa8b40d8cabd9352f605feb553070327140c56f6cd72d0e576db44",
}
CORE = ("ssh.service", "dnsmasq.service", "awg-pbr-health.service",
        "awg-selection-monitor.service", "awg-mihomo.service")
NOTIFY = ("awg-notify-flush.timer", "awg-notify-watch.timer",
          "awg-notify-daily.timer", "awg-notify-boot.service")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=18,
                          check=False)
    if proc.returncode:
        raise RuntimeError("preflight command failed: " + args[0])
    return proc.stdout.strip()


def state():
    return (
        tuple((unit, subprocess.run(("systemctl", "is-enabled", unit),
                                   capture_output=True, text=True,
                                   timeout=8).stdout.strip())
              for unit in NOTIFY),
        tuple((unit, run("systemctl", "is-active", unit)) for unit in CORE),
        run("/usr/local/sbin/awg-transport", "get"),
        run("ip", "-4", "rule", "show"),
        run("ip", "-4", "route", "show", "table", "100"),
        run("ip", "-4", "route", "show", "table", "101")
    )


def checked_file(path, owner=None):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or path.is_symlink():
        raise RuntimeError("refuse nonregular input")
    if owner is not None and meta.st_uid != owner:
        raise RuntimeError("refuse unexpected installed file owner")
    return path.read_bytes()


def atomic_install(data, target):
    fd, temporary = tempfile.mkstemp(prefix=".awg-notify-ui-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o755)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    sources, originals = {}, {}
    for name, expected in EXPECTED_NEW.items():
        sources[name] = checked_file(SRC / ("awg-notify.py" if name == "awg-notify" else name))
        originals[name] = checked_file(DST / name, owner=0)
        if sha(sources[name]) != expected or sha(originals[name]) != EXPECTED_CURRENT[name]:
            print("REFUSE_UNREVIEWED_BINARY=" + name)
            return 2
    run("bash", "-n", str(SRC / "awg-menu"))
    compile(sources["awg-notify"], str(SRC / "awg-notify.py"), "exec")
    for name in ("notify_types_menu(){", "--separate-output --checklist",
                 '9 "Типы уведомлений [галочки]"', "appearance_menu(){",
                 "first_transport_setup(){", "secondary_transport_setup(){"):
        if name not in sources["awg-menu"].decode("utf-8"):
            print("REFUSE_MENU_CONTRACT")
            return 2

    before = state()
    if not all(status == "active" for _, status in before[1]):
        print("REFUSE_CORE_SERVICES_NOT_ACTIVE")
        return 2
    if before[2] != "mihomo" or any("mihomo0" not in route for route in before[4:]):
        print("REFUSE_UNEXPECTED_ACTIVE_TRANSPORT")
        return 2
    bdir = Path(tempfile.mkdtemp(prefix="notify-switches-",
               dir="/var/backups/awg-gateway"))
    bdir.chmod(0o700)
    for name, data in originals.items():
        backup = bdir / (name + ".old")
        backup.write_bytes(data)
        backup.chmod(0o600)

    try:
        for name in ("awg-notify", "awg-menu"):
            atomic_install(sources[name], DST / name)
        if any(sha(checked_file(DST / name, owner=0)) != EXPECTED_NEW[name]
               for name in EXPECTED_NEW):
            raise RuntimeError("installation hash mismatch")
        if state() != before:
            raise RuntimeError("gateway state mismatch")
    except Exception:
        for name in ("awg-notify", "awg-menu"):
            atomic_install(originals[name], DST / name)
        print("NOTIFY_SWITCHES_INSTALL=ROLLED_BACK")
        print("BACKUP=" + str(bdir))
        raise
    print("NOTIFY_SWITCHES_INSTALL=PASS_TEST_PI_ONLY")
    print("TELEGRAM_SWITCHES=6")
    print("CONFIGURATION_AND_QUEUE=PRESERVED")
    print("SSH_DNS_PBR_SELECTED_TRANSPORT=UNCHANGED")
    print("TIMER_ENABLEMENT=UNCHANGED")
    print("BACKUP=" + str(bdir))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print("NOTIFY_SWITCHES_INSTALL=FAIL_SAFE " + type(exc).__name__,
              file=sys.stderr)
        sys.exit(1)
