#!/usr/bin/env python3
"""AWG Notify: independent, store-and-forward Telegram notifier.

Never changes a network route, VPN node, DNS, MikroTik or firewall.
Bot token is sent to curl on stdin as a config, never in argv or logs.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode

DB_PATH = Path("/var/lib/awg-pbr/notify/events.sqlite3")
SECRET_PATH = Path("/etc/awg-pbr/notify/telegram.json")
TRANSPORT_PATH = Path("/etc/awg-pbr/transport")
# Only an operator-verified fail-closed RouterOS SSTP policy permits eth0 fallback.
ROUTER_SSTP_APPROVED = Path("/etc/awg-pbr/notify/router-sstp-approved")
TOKEN_PATTERN = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{25,150}$")
KINDS = {"NODE_SWITCH", "TRANSPORT_SWITCH", "TRANSPORT_FAILOVER", "VPN_LOST", "VPN_RESTORED",
         "POOL_EMPTY", "POOL_RESTORED", "BOOT", "SYSTEM_WARNING",
         "SUBSCRIPTION_CHANGED", "DAILY_REPORT", "TEST"}
SEVERITIES = ("info", "warning", "critical")
# SSTP is an *external RouterOS forwarding decision*. eth0 does NOT prove SSTP.
ROUTES = ("mihomo0", "awg0", "eth0")
MAX_PENDING = 500
MAX_TEXT = 3000


def now():
    return int(time.time())


def check_root():
    if os.geteuid() != 0:
        raise SystemExit("Requires root; run with sudo.")


def open_db(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    db = sqlite3.connect(str(path), timeout=5)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY,
      created INTEGER NOT NULL,
      kind TEXT NOT NULL,
      severity TEXT NOT NULL,
      fingerprint TEXT NOT NULL,
      message TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      next_try INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS recent (
      fingerprint TEXT PRIMARY KEY,
      seen INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    """)
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    return db


def enqueue(db, kind, severity, message, key=None, timestamp=None):
    if kind not in KINDS or severity not in SEVERITIES:
        raise ValueError("Invalid event kind or severity")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_TEXT:
        raise ValueError("Invalid message length")
    t = now() if timestamp is None else timestamp
    # The explicit key lets producers deduplicate the same logical transition.
    signature = "|".join((kind, key or message))
    fingerprint = hashlib.sha256(signature.encode()).hexdigest()
    with db:
        seen = db.execute("SELECT seen FROM recent WHERE fingerprint=?",
                          (fingerprint,)).fetchone()
        if seen and t - seen[0] < 120:
            return False
        db.execute("INSERT OR REPLACE INTO recent VALUES (?, ?)", (fingerprint, t))
        db.execute("""INSERT INTO events
                      (created,kind,severity,fingerprint,message,next_try)
                      VALUES (?,?,?,?,?,?)""",
                   (t, kind, severity, fingerprint, message, t))
        db.execute("DELETE FROM recent WHERE seen < ?", (t - 86400,))
        # Keep the most recent urgent events; only prune if the hard cap is hit.
        count = db.execute("SELECT count(*) FROM events").fetchone()[0]
        if count > MAX_PENDING:
            db.execute("""DELETE FROM events WHERE id IN (
              SELECT id FROM events ORDER BY
              CASE severity WHEN 'info' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
              id ASC LIMIT ?)""", (count - MAX_PENDING,))
    return True


def load_secret(path=SECRET_PATH, owner_uid=0):
    path = Path(path)
    stat = path.stat()
    if stat.st_mode & 0o077 or stat.st_uid != owner_uid or not path.is_file():
        raise ValueError("Telegram secret file must be root-owned and mode 0600")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not TOKEN_PATTERN.fullmatch(str(obj.get("token", ""))):
        raise ValueError("Invalid Telegram token")
    chat = str(obj.get("chat_id", ""))
    if not re.fullmatch(r"-?[0-9]{1,20}", chat):
        raise ValueError("Invalid chat ID")
    return obj["token"], chat


def configure(path=SECRET_PATH):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    token = getpass.getpass("Telegram bot token (input hidden): ").strip()
    chat = input("Telegram numeric chat ID: ").strip()
    if not TOKEN_PATTERN.fullmatch(token) or not re.fullmatch(r"-?[0-9]{1,20}", chat):
        raise SystemExit("Invalid token or chat ID; nothing saved.")
    temp = path.with_name(path.name + ".new")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": token, "chat_id": chat}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    print("Telegram credentials saved (0600). No message sent yet.")


def router_sstp_approved(path=ROUTER_SSTP_APPROVED, owner_uid=0):
    try:
        stat = Path(path).stat()
        return (stat.st_uid == owner_uid and not (stat.st_mode & 0o077)
                and Path(path).is_file()
                and Path(path).read_text(encoding="ascii").strip()
                == "SSTP_VERIFIED_FAIL_CLOSED=1")
    except (OSError, UnicodeError):
        return False


def route_order(active="", router_approved=None):
    if active not in ("awg", "mihomo"):
        try:
            active = TRANSPORT_PATH.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, PermissionError):
            active = ""
    preferred = {"mihomo": "mihomo0", "awg": "awg0"}.get(active)
    # eth0 may be DIRECT when SSTP drops: never use it without a reviewed
    # RouterOS fail-closed policy that was tested with the SSTP tunnel down.
    candidates = ["mihomo0", "awg0"]
    if router_approved is None:
        router_approved = router_sstp_approved()
    if router_approved:
        candidates.append("eth0")
    return ([preferred] if preferred else []) + [x for x in candidates if x != preferred]


def curl_api(token, payload, route, method="sendMessage", timeout=8):
    """Use curl config on stdin to hide the bot token from process arguments.

    Binding eth0 sends traffic to MikroTik; it is SSTP only when RouterOS
    independently routes it through its SSTP tunnel. No implicit DIRECT
    exception or RouterOS change is made by this module.
    """
    if route not in ROUTES or method not in ("sendMessage", "getUpdates"):
        raise ValueError("Unsupported route/API method")
    url = "https://api.telegram.org/bot" + token + "/" + method
    encoded = urlencode(payload)
    config = 'url = "' + url + '"\n' + 'data = "' + encoded + '"\n'
    argv = ["curl", "-q", "--config", "-", "--ipv4", "--proto", "=https",
            "--noproxy", "*", "--interface", "if!" + route,
            "--connect-timeout", "4", "--max-time", str(timeout),
            "--silent", "--show-error", "--write-out", "\n%{http_code}"]
    try:
        reply = subprocess.run(argv, input=config, text=True, capture_output=True,
                               timeout=timeout + 2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, 0, 0
    if reply.returncode or len(reply.stdout) > 65536:
        return False, 0, 0
    body, _, status = reply.stdout.rpartition("\n")
    try:
        code = int(status)
        data = json.loads(body)
    except (ValueError, TypeError):
        return False, 0, 0
    if code == 200 and data.get("ok") is True:
        return True, 200, 0
    retry = data.get("parameters", {}).get("retry_after", 0)
    return False, code, min(3600, max(0, int(retry))) if str(retry).isdigit() else 0


def flush(db, sender=curl_api, secret_path=SECRET_PATH, active="", limit=2, secret_uid=0):
    # No credentials = intentionally unconfigured; do not delete queued events.
    try:
        token, chat = load_secret(secret_path, secret_uid)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"sent": 0, "pending": db.execute("SELECT count(*) FROM events").fetchone()[0],
                "reason": "not_configured"}
    sent = 0
    verdict = "idle"
    for row in db.execute("""SELECT id,created,kind,severity,message,attempts
                             FROM events WHERE next_try <= ?
                             ORDER BY id LIMIT ?""", (now(), limit)).fetchall():
        ident, created, kind, severity, message, attempts = row
        text = "[AWG Pi] " + kind + " / " + severity.upper() + "\n" + message
        for route in route_order(active):
            ok, code, retry = sender(token, {"chat_id": chat, "text": text,
                                              "disable_web_page_preview": "true"}, route)
            if ok:
                with db:
                    db.execute("DELETE FROM events WHERE id=?", (ident,))
                    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                               ("last_success_route", route))
                    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                               ("last_success_time", str(now())))
                sent += 1
                verdict = "sent"
                break
            # 401/403 means invalid token, access or permissions: do not try
            # the same rejected request through every interface.
            if code in (400, 401, 403, 429):
                verdict = "telegram_rejected_" + str(code)
                break
        else:
            verdict = "network_unavailable"
        if verdict != "sent":
            # Backoff is capped, never prevents VPN recovery/control.
            pause = retry if "retry" in locals() and retry else min(1800, 30 * (2 ** min(attempts, 6)))
            with db:
                db.execute("UPDATE events SET attempts=attempts+1,next_try=? WHERE id=?",
                           (now() + pause, ident))
            break
    return {"sent": sent, "pending": db.execute("SELECT count(*) FROM events").fetchone()[0],
            "reason": verdict}


def _read_first(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return default


def _service_active(unit):
    try:
        result = subprocess.run(["systemctl", "is-active", "--quiet", unit],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                check=False, timeout=3)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def daily_snapshot():
    """Read-only local telemetry; no VPN restart, DNS probe or route mutation."""
    total = available = 0
    for line in _read_first("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) // 1024
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) // 1024
    try:
        disk = shutil.disk_usage("/")
        used_disk = round((disk.total - disk.free) * 100 / disk.total)
    except (OSError, ZeroDivisionError):
        used_disk = -1
    temp = _read_first("/sys/class/thermal/thermal_zone0/temp")
    try:
        temp_label = f"{int(temp) / 1000:.1f} °C"
    except ValueError:
        temp_label = "неизвестно"
    try:
        uptime = int(float(_read_first("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        uptime = 0
    transport = _read_first(TRANSPORT_PATH, "не настроен")
    if transport not in ("awg", "mihomo", "unconfigured"):
        transport = "неизвестно"
    mode = _read_first("/etc/awg-pbr/mode", "неизвестно")
    if mode not in ("selective", "transit"):
        mode = "неизвестно"
    service_names = ("awg-selection-monitor.service", "awg-pbr-health.service",
                     "dnsmasq.service", "ssh.service")
    health = [unit.removesuffix(".service") + "=" +
              ("активна" if _service_active(unit) else "неактивна")
              for unit in service_names]
    return "\n".join([
        "Ежедневная сводка AWG Pi Gateway",
        "Режим: " + mode,
        "Транспорт (выбранный, не подтверждение HTTPS): " + transport,
        "Температура CPU: " + temp_label,
        "RAM: " + str(total - available) + " / " + str(total) + " MiB",
        "Диск: " + (str(used_disk) + "%" if used_disk >= 0 else "неизвестно"),
        "Uptime: " + str(uptime // 3600) + " ч",
        "Службы: " + ", ".join(health),
    ])


def enqueue_daily(db):
    """One daily report per local calendar day even if invoked twice."""
    if not SECRET_PATH.exists():
        return False
    stamp = time.strftime("%Y-%m-%d", time.localtime())
    with db:
        seen = db.execute("SELECT value FROM meta WHERE key='daily_date'").fetchone()
        if seen and seen[0] == stamp:
            return False
        queued = enqueue(db, "DAILY_REPORT", "info", daily_snapshot(),
                         "daily:" + stamp)
        if queued:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('daily_date', ?)", (stamp,))
        return queued


def show_status(db, secret_path=SECRET_PATH):
    try:
        load_secret(secret_path)
        configured = True
    except (OSError, ValueError, json.JSONDecodeError):
        configured = False
    pending = db.execute("SELECT count(*) FROM events").fetchone()[0]
    last = db.execute("SELECT value FROM meta WHERE key='last_success_route'").fetchone()
    print("NOTIFY_CONFIGURED=" + ("yes" if configured else "no"))
    print("NOTIFY_PENDING=" + str(pending))
    print("NOTIFY_LAST_ROUTE=" + (last[0] if last else "none"))
    print("NOTIFY_ROUTE_ETH0=" + ("approved_router_policy" if router_sstp_approved()
                                   else "disabled_pending_sstp_fail_closed_proof"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="AWG Pi Gateway Telegram notifications")
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--kind", choices=sorted(KINDS), required=True)
    emit.add_argument("--severity", choices=SEVERITIES, default="info")
    emit.add_argument("--key", default=None)
    emit.add_argument("--text", default=None,
                      help="Safe non-secret text; if omitted read message from stdin")
    sub.add_parser("configure")
    sub.add_parser("flush")
    sub.add_parser("status")
    sub.add_parser("test")
    sub.add_parser("daily")
    args = parser.parse_args(argv)
    check_root()
    os.umask(0o077)
    if args.command == "configure":
        configure()
        return 0
    with open_db() as db:
        if args.command == "emit":
            message = args.text if args.text is not None else sys.stdin.read(MAX_TEXT + 1)
            created = enqueue(db, args.kind, args.severity, message, args.key)
            print("NOTIFY_QUEUED=" + ("yes" if created else "deduplicated"))
        elif args.command == "daily":
            print("NOTIFY_DAILY_QUEUED=" + ("yes" if enqueue_daily(db) else "no"))
        elif args.command == "test":
            enqueue(db, "TEST", "info", "Test notification from Raspberry Pi", str(now()))
            print(json.dumps(flush(db), sort_keys=True))
        elif args.command == "flush":
            print(json.dumps(flush(db), sort_keys=True))
        elif args.command == "status":
            show_status(db)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, sqlite3.Error) as exc:
        # Never echo secret content or raw API response.
        print("AWG Notify error: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
