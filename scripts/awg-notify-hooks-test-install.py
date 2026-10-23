#!/usr/bin/env python3
"""Test-Pi only: pin-checked notify-only selector/transport update with rollback.

Installs two additive alert hooks into the tested live scripts; restarts ONLY
the selector daemon to load its Bash source. No VPN, DNS, route, SSH/SSTP,
MikroTik, node/subscription or Telegram preferences changes. Then executes a
separate isolated six-switch matrix + one AWG-bound real TEST notification.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

HOME = Path("/home/karlinks/awg-notify-fixture")
BACKUPS = Path("/var/backups/awg-gateway")
APP = Path("/usr/local/sbin")
SELECTOR = "awg-selection-monitor.service"
FILES = {
    "awg-transport": (
        "d5eb763902bfeebf3170e5d4e70a35ab2b8e2dabf35ad57f8f1ce25b9eae68dd",
        "00207041308e591040a4b45e7e9efbb8820161e3127f905107bdecaba7ecf110"),
    "awg-selection-monitor": (
        "e98b697daddc4b6510310182c3eabe4d45ba9bde394e7b655bdb9989e610d0ef",
        "569e6ac66561fc04ccf98f34378e96a6e03bc46daf5e61e5b6e8dc75a8d06b99")
}
MATRIX_SHA = "e676af1923e8df5ca5197b1b03a1d7c971e1ef1f740f9511225c7b9dc95877bb"
NOTIFIER_SHA = "6eab64b8ea3dab459130c32516b693c049f17d1d0e631c1d17a76157ac0139a3"
CORE = ("ssh.service", "dnsmasq.service", "awg-pbr-health.service",
        "awg-quick@awg0.service", SELECTOR)
TIMERS = ("awg-notify-flush.timer", "awg-notify-watch.timer",
          "awg-notify-daily.timer", "awg-notify-boot.service")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(*args, timeout=15, checked=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            check=False)
    if checked and result.returncode:
        raise RuntimeError("preflight command failed: " + args[0])
    return result.stdout.strip()


def binary(path, expect_owner=False):
    meta = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(meta.st_mode):
        raise RuntimeError("Refused symlink/nonregular: " + path.name)
    if expect_owner and (meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o755):
        raise RuntimeError("Refused executable owner/mode: " + path.name)
    return path.read_bytes()


def state():
    return {
        "selected": command("/usr/local/sbin/awg-selection", "status"),
        "services": tuple((unit, command("systemctl", "is-active", unit))
                          for unit in CORE),
        "timers": tuple((unit,
                         command("systemctl", "is-enabled", unit, checked=False),
                         command("systemctl", "is-active", unit, checked=False))
                        for unit in TIMERS),
        "rules": command("ip", "-4", "rule", "show"),
        "table100": command("ip", "-4", "route", "show", "table", "100"),
        "table101": command("ip", "-4", "route", "show", "table", "101")
    }


def write_atomic(path, content):
    fd, name = tempfile.mkstemp(prefix=".awg-notify-hook-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(name, 0, 0)
        os.chmod(name, 0o755)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    if command("hostname") != "awg-upgrade":
        print("REFUSED_NOT_TEST_PI")
        return 2
    images, previous = {}, {}
    for name, (oldhash, newhash) in FILES.items():
        source = HOME / "src" / name
        dest = APP / name
        new = binary(source)
        old = binary(dest, expect_owner=True)
        if digest(new) != newhash or digest(old) not in (oldhash, newhash):
            print("REFUSED_SCRIPT_HASH_MISMATCH=" + name)
            return 2
        command("bash", "-n", str(source))
        images[name] = new
        previous[name] = old

    matrix = HOME / "scripts/awg-notify-event-matrix-test.py"
    if digest(binary(matrix)) != MATRIX_SHA:
        print("REFUSED_TEST_MATRIX_CHANGED")
        return 2
    if digest(binary(APP / "awg-notify", expect_owner=True)) != NOTIFIER_SHA:
        print("REFUSED_NOTIFY_BINARY_CHANGED")
        return 2
    command(sys.executable, "-m", "py_compile", str(matrix))

    # Guard the network invariant before touching executables.
    before = state()
    if "Current transport: awg" not in before["selected"]:
        print("REFUSED_ACTIVE_TRANSPORT_NOT_AWG")
        return 2
    if any(status != "active" for _, status in before["services"]):
        print("REFUSED_CORE_HEALTH_NOT_ACTIVE")
        return 2
    if not all("awg0" in before[key] for key in ("table100", "table101")):
        print("REFUSED_AWG_ROUTES_NOT_ACTIVE")
        return 2
    if command("/usr/local/sbin/awg-transport", "check", "awg") != "healthy":
        print("REFUSED_AWG_TRANSPORT_NOT_HEALTHY")
        return 2

    # All switch tests are performed in /run, with no bot secret and no network.
    command(sys.executable, str(matrix), "--offline", timeout=35)
    print("ISOLATED_PREDEPLOY_MATRIX=PASS")

    if all(previous[k] == images[k] for k in FILES):
        print("HOOK_INSTALL=ALREADY_INSTALLED_TEST_PI_ONLY")
    else:
        BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="telegram-hooks-", dir=str(BACKUPS)))
        folder.chmod(0o700)
        for name, old in previous.items():
            backup = folder / (name + ".previous")
            backup.write_bytes(old)
            backup.chmod(0o600)
        try:
            for name, new in images.items():
                write_atomic(APP / name, new)
            # A running Bash selector retains its old source without restart.
            # Restart selector ONLY; never restart AWG or Mihomo transport.
            command("systemctl", "restart", SELECTOR, timeout=18)
            for name, (_, newhash) in FILES.items():
                if digest(binary(APP / name, expect_owner=True)) != newhash:
                    raise RuntimeError("installed executable hash mismatch")
            if state() != before:
                raise RuntimeError("gateway/service/timer/route invariant changed")
        except Exception:
            for name, old in previous.items():
                write_atomic(APP / name, old)
            subprocess.run(["systemctl", "restart", SELECTOR], capture_output=True,
                           text=True, timeout=18, check=False)
            print("HOOK_INSTALL=ROLLED_BACK")
            print("BACKUP=" + str(folder))
            raise
        print("HOOK_INSTALL=PASS_TEST_PI_ONLY")
        print("SELECTOR_RESTART_ONLY=YES")
        print("AWG_DNS_SSH_TIMERS_ROUTES=UNCHANGED")
        print("BACKUP=" + str(folder))

    # No configuration or queue mutates; only one explicitly labeled TEST
    # is sent through AWG (never a fabricated VPN_LOST/TRANSPORT_FAILOVER).
    live = subprocess.run([sys.executable, str(matrix)], capture_output=True,
                          text=True, timeout=75, check=False)
    for line in live.stdout.splitlines():
        if line.startswith(("SWITCH_", "TRANSPORT_FAILOVER_ALIAS=",
                            "TEST_EVENT_", "PREFERENCES_ATOMIC_",
                            "ISOLATED_MATRIX=", "PRODUCTION_",
                            "CURRENT_PREF_", "LIVE_ROUTE=", "LIVE_SEND=",
                            "LIVE_SEND_STATUS=")):
            print(line)
    if live.returncode:
        print("LIVE_TELEGRAM_TEST=FAILED_OR_UNCONFIRMED")
    else:
        print("LIVE_TELEGRAM_TEST=PASS_AWG_BOUND")

    if state() != before:
        print("POSTTEST_GATEWAY_STATE=CHANGED_NEEDS_DIAGNOSIS")
        return 5
    print("POSTTEST_GATEWAY_STATE=PRESERVED")
    return 0 if live.returncode == 0 else 4


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired,
            UnicodeError, ValueError) as err:
        # Never print exception text containing secrets.
        print("HOOK_INSTALL=FAIL_SAFE:" + type(err).__name__, file=sys.stderr)
        sys.exit(1)
