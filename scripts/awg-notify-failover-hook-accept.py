#!/usr/bin/env python3
"""Test-Pi only: safe Telegram hook installation and isolated Bot API acceptance.

Never switches VPN, edits live Telegram preferences/secret/queue, or touches
DNS/PBR/MikroTik. A bounded restart of selection-monitor activates the hook.
All six synthetic messages carry an explicit non-real-event label.
"""
import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from unittest import mock

STAGE = Path("/home/karlinks/awg-notify-fixture/src")
DEST = Path("/usr/local/sbin")
ROOT_BACKUP = Path("/var/backups/awg-gateway")
ORIGINAL = {
    "awg-transport": "d5eb763902bfeebf3170e5d4e70a35ab2b8e2dabf35ad57f8f1ce25b9eae68dd",
    "awg-selection-monitor": "e98b697daddc4b6510310182c3eabe4d45ba9bde394e7b655bdb9989e610d0ef",
}
UPDATED = {
    "awg-transport": "00207041308e591040a4b45e7e9efbb8820161e3127f905107bdecaba7ecf110",
    "awg-selection-monitor": "569e6ac66561fc04ccf98f34378e96a6e03bc46daf5e61e5b6e8dc75a8d06b99",
}
NOTIFIER_HASH = "6eab64b8ea3dab459130c32516b693c049f17d1d0e631c1d17a76157ac0139a3"
CORE = ("ssh.service", "dnsmasq.service", "awg-pbr-health.service",
        "awg-selection-monitor.service", "awg-quick@awg0.service")
TIMERS = ("awg-notify-flush.timer", "awg-notify-watch.timer",
          "awg-notify-daily.timer", "awg-notify-boot.service")
CATEGORIES = ("VPN_LOST", "VPN_RESTORED", "BOOT", "DAILY_REPORT",
              "NODE_SWITCH", "TRANSPORT_SWITCH")
HISTORY = []


def command(*args, timeout=18):
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("Check failed: " + str(args[0]) + " " + str(args[1:3]))
    return result.stdout.strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise RuntimeError("Unsafe input type")
    return path.read_bytes(), info


def atomic_install(path, data):
    fd, temp = tempfile.mkstemp(prefix=".awg-hook-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o755)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def snapshot():
    active = tuple((s, subprocess.run(["systemctl", "is-active", s],
                    capture_output=True, text=True, timeout=6).stdout.strip())
                   for s in CORE)
    selected = Path("/etc/awg-pbr/transport").read_text().strip()
    tables = (command("ip", "-4", "route", "show", "table", "100"),
              command("ip", "-4", "route", "show", "table", "101"))
    rules = command("ip", "-4", "rule", "show")
    unit_switches = tuple((u, subprocess.run(["systemctl", "is-enabled", u],
                          capture_output=True, text=True, timeout=6).stdout.strip())
                          for u in TIMERS)
    return active, selected, tables, rules, unit_switches


def load_notifier():
    spec = importlib.util.spec_from_file_location("awg_notify_acceptance", DEST / "awg-notify")
    module = importlib.util.module_from_spec(spec) if spec else None
    if module is None or spec.loader is None:
        # Python source in /usr/local/sbin/awg-notify has no .py extension.
        from importlib.machinery import SourceFileLoader
        loader = SourceFileLoader("awg_notify_acceptance", str(DEST / "awg-notify"))
        import types
        module = types.ModuleType("awg_notify_acceptance")
        loader.exec_module(module)
        return module
    spec.loader.exec_module(module)
    return module


def test_matrix_and_send():
    mod = load_notifier()
    live_prefs = mod.load_preferences()
    for category in CATEGORIES:
        print("LIVE_PREF_" + category + "=" + ("on" if live_prefs[category] else "off"))

    # Isolated preferences AND isolated DB; no live policy, queue or boot unit changes.
    with tempfile.TemporaryDirectory(prefix="awg-telegram-accept-", dir="/run") as root:
        base = Path(root)
        pref = base / "events-policy.json"
        temp_db = base / "matrix" / "events.sqlite3"
        opened = []
        real_open = mod.open_db
        with mock.patch.object(mod, "PREFERENCES_PATH", pref), \
             mock.patch.object(mod, "open_db",
                               side_effect=lambda: opened.append(real_open(temp_db)) or opened[-1]):
            for category in CATEGORIES:
                actual = "TRANSPORT_FAILOVER" if category == "TRANSPORT_SWITCH" else category
                mod.save_preferences(set())
                if mod.event_enabled(actual):
                    raise RuntimeError("Check-box OFF did not suppress " + category)
                old_count = count_temp(real_open, temp_db)
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    if mod.main(["emit", "--kind", actual, "--text",
                                 "[ТЕСТ] suppressed " + category]):
                        raise RuntimeError("emit OFF returned error")
                if "NOTIFY_QUEUED=disabled" not in buf.getvalue():
                    raise RuntimeError("emit OFF produced unexpected result")
                if count_temp(real_open, temp_db) != old_count:
                    raise RuntimeError("Off-category added to queue")
                mod.save_preferences({category})
                if not mod.event_enabled(actual):
                    raise RuntimeError("Check-box ON did not enable " + category)
                for other in CATEGORIES:
                    if other != category and mod.event_enabled(other):
                        raise RuntimeError("Unselected category enabled: " + other)
                sev = "critical" if category == "VPN_LOST" else (
                      "warning" if category == "TRANSPORT_SWITCH" else "info")
                # Explicitly labeled artificial event, never a real outage/reboot.
                label = "[ТЕСТ — имитация, не реальное событие]\n"
                label += "Переключатель: " + category + "\n"
                label += "Шлюз AWG не переключался, маршруты не менялись."
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    if mod.main(["emit", "--kind", actual, "--severity", sev,
                                 "--text", label]):
                        raise RuntimeError("emit ON returned error")
                if "NOTIFY_QUEUED=yes" not in buf.getvalue():
                    raise RuntimeError("Enabled category did not enter test queue")
        for connection in opened:
            connection.close()
        with real_open(temp_db) as db:
            kinds = [v[0] for v in db.execute("SELECT kind FROM events ORDER BY id")]
            expected = list(CATEGORIES)
            expected[-1] = "TRANSPORT_FAILOVER"
            if kinds != expected:
                raise RuntimeError("Test events order/type mismatch")
        print("ALL_SIX_CHECKBOX_GATES=PASS")
        print("LIVE_POLICY_AND_QUEUE=UNMODIFIED")

        # Watch's independent production callbacks are simulated against
        # another isolated SQLite DB; no real health probing / VPN stop.
        watch_db = base / "watch" / "events.sqlite3"
        fake_secret = base / "watch" / "fake-telegram.json"
        fake_secret.parent.mkdir(mode=0o700)
        fake_secret.write_text("placeholder")
        with mock.patch.object(mod, "PREFERENCES_PATH", pref), \
             mock.patch.object(mod, "SECRET_PATH", fake_secret):
            mod.save_preferences({"VPN_LOST", "VPN_RESTORED"})
            with real_open(watch_db) as db:
                if [mod.observe_transport(db, "awg", lambda _: False) for _ in range(2)] != ["suspect", "down"]:
                    raise RuntimeError("Watch double-failure gate mismatch")
                if mod.observe_transport(db, "awg", lambda _: True) != "up":
                    raise RuntimeError("Watch recovery mismatch")
                found = [v[0] for v in db.execute("SELECT kind FROM events ORDER BY id")]
                if found != ["VPN_LOST", "VPN_RESTORED"]:
                    raise RuntimeError("Watch callback type mismatch")
        print("WATCH_FAILURE_AND_RECOVERY_GATES=PASS")

        # The six TEST-labeled events are sent via the real Telegram Bot API
        # ONLY on awg0. No SSTP/eth0/DIRECT fallback and no production DB use.
        if command("systemctl", "is-active", "awg-quick@awg0.service") != "active":
            raise RuntimeError("AWG became inactive, refusing send")
        total = 0
        with mock.patch.object(mod, "route_order", return_value=["awg0"]):
            with real_open(temp_db) as db:
                for i in range(3):
                    r = mod.flush(db, active="awg", limit=2)
                    print("TEST_BOT_BATCH_" + str(i+1) + "_SENT=" + str(r["sent"]))
                    print("TEST_BOT_BATCH_" + str(i+1) + "_PENDING=" + str(r["pending"]))
                    total += r["sent"]
                    if r["sent"] != 2:
                        print("TEST_BOT_ERROR=" + str(r["reason"]))
                        break
                pending = db.execute("SELECT count(*) FROM events").fetchone()[0]
                if total != 6 or pending:
                    print("TEST_BOT_DELIVERY=UNCONFIRMED")
                    return False
                route = db.execute("SELECT value FROM meta WHERE key='last_success_route'").fetchone()
                if not route or route[0] != "awg0":
                    raise RuntimeError("Unexpected Telegram test route")
        print("TEST_BOT_DELIVERY=6_OF_6_API_OK_VIA_AWG0")
        print("TELEGRAM_RECEIPT_ON_PHONE=NOT_INDEPENDENTLY_VERIFIED")
        return True


def count_temp(opener, path):
    with opener(path) as db:
        return db.execute("SELECT count(*) FROM events").fetchone()[0]


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    data = {}
    old = {}
    for name in ORIGINAL:
        src, src_info = read_regular(STAGE / name)
        before, old_info = read_regular(DEST / name)
        if sha(src) != UPDATED[name] or sha(before) not in (ORIGINAL[name], UPDATED[name]):
            raise RuntimeError("Pinned hash mismatch: " + name)
        if old_info.st_uid != 0 or stat.S_IMODE(old_info.st_mode) != 0o755:
            raise RuntimeError("Unexpected deployed script owner/mode")
        command("bash", "-n", str(STAGE / name))
        data[name], old[name] = src, before
    module_data, module_info = read_regular(DEST / "awg-notify")
    if sha(module_data) != NOTIFIER_HASH or module_info.st_uid != 0:
        raise RuntimeError("Notifier binary does not match tested version")
    if not Path("/etc/awg-pbr/notify/telegram.json").is_file():
        raise RuntimeError("Telegram bot not configured; refusing real send")
    before = snapshot()
    if any(value != "active" for _, value in before[0]):
        raise RuntimeError("Core service not active before installation")
    if before[1] != "awg" or any("awg0" not in x for x in before[2]):
        raise RuntimeError("Refusing hook install outside stable AWG fallback")
    if any(v != "enabled" for u, v in before[4] if u in ("awg-notify-watch.timer",
                                                          "awg-notify-flush.timer")):
        raise RuntimeError("Telegram watch/delivery disabled")

    ROOT_BACKUP.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="notify-failover-hooks-", dir=ROOT_BACKUP))
    backup.chmod(0o700)
    for name in ORIGINAL:
        (backup / name).write_bytes(old[name])
        (backup / name).chmod(0o600)
    print("BACKUP=" + str(backup), flush=True)

    try:
        for name in ORIGINAL:
            if old[name] != data[name]:
                atomic_install(DEST / name, data[name])
        # A running Bash selection-monitor has already loaded the old code.
        # Restart only the controller, not AWG, health monitor or routing.
        if old["awg-selection-monitor"] != data["awg-selection-monitor"]:
            command("systemctl", "restart", "awg-selection-monitor.service", timeout=20)
        after = snapshot()
        if after != before:
            raise RuntimeError("Protected service/routing/transport status changed")
        if any(sha(read_regular(DEST / name)[0]) != UPDATED[name] for name in ORIGINAL):
            raise RuntimeError("Installed files do not match pinned sources")
    except Exception:
        for name in ORIGINAL:
            atomic_install(DEST / name, old[name])
        command("systemctl", "restart", "awg-selection-monitor.service", timeout=20)
        print("HOOK_INSTALL=ROLLED_BACK")
        raise
    print("HOOK_INSTALL=PASS_TEST_PI_ONLY", flush=True)
    print("ACTIVE_TRANSPORT=AWG_UNCHANGED")
    print("SERVICES_DNS_PBR_TIMERS=UNCHANGED")
    print("NODE_HOOK=INSTALLED")
    print("FAILOVER_HOOK=INSTALLED")
    print("LIVE_QUEUE_SECRET_PREFERENCES=UNMODIFIED")

    try:
        success = test_matrix_and_send()
    except Exception as exc:
        # Do not restore old uninstrumented hooks after a purely Telegram
        # notification test error: router and healthy AWG must remain stable.
        print("EVENT_TEST=FAIL_" + type(exc).__name__)
        success = False
    final = snapshot()
    if final != before:
        print("POST_TEST_SNAPSHOT=CHANGED_REQUIRES_REVIEW")
        return 1
    print("POST_TEST_GATEWAY=UNCHANGED")
    if success:
        return 0
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print("HOOK_ACCEPTANCE=FAIL_SAFE_" + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
