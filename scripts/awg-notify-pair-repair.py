#!/usr/bin/env python3
"""Repair an incorrect Telegram chat ID using the already stored root-only bot token.

Read-only Bot API getMe/getUpdates; no messages sent, no update offset, webhook
or route mutation. Rewrites only the Telegram chat ID after a private challenge.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import urlencode

BIN = Path("/usr/local/sbin/awg-notify")
SECRET = Path("/etc/awg-pbr/notify/telegram.json")
BOT_USERNAME = re.compile(r"^[A-Za-z0-9_]{5,32}$")
MAX_WAIT_SECONDS = 120


def load_notify():
    loader = importlib.machinery.SourceFileLoader("awg_notify_installed", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def telegram_request(token, route, method):
    if route not in ("awg0", "mihomo0", "eth0") or method not in ("getMe", "getUpdates"):
        raise ValueError("Invalid bot API request")
    cfg = 'url = "https://api.telegram.org/bot' + token + "/" + method + '"\n'
    if method == "getUpdates":
        # Omitting offset means nothing is marked read/confirmed. The command
        # deliberately preserves all updates, for other authorized consumers.
        cfg += 'data = "' + urlencode({"timeout": 0, "limit": 100}) + '"\n'
    argv = ["curl", "-q", "--config", "-", "--ipv4", "--proto", "=https",
            "--noproxy", "*", "--interface", "if!" + route,
            "--connect-timeout", "4", "--max-time", "9", "--silent",
            "--write-out", "\n%{http_code}"]
    try:
        reply = subprocess.run(argv, input=cfg, text=True, capture_output=True,
                               timeout=11, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, 0
    if reply.returncode or len(reply.stdout) > 131072:
        return None, 0
    body, sep, status = reply.stdout.rpartition("\n")
    if not sep or not status.isdigit():
        return None, 0
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None, int(status)
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None, int(status)
    return data.get("result"), int(status)


def find_private_challenge(items, challenge):
    if not isinstance(items, list):
        return None
    matched = set()
    for update in items:
        if not isinstance(update, dict):
            continue
        msg = update.get("message")
        if not isinstance(msg, dict) or msg.get("text") != "/pair " + challenge:
            continue
        chat, author = msg.get("chat"), msg.get("from")
        if not isinstance(chat, dict) or not isinstance(author, dict):
            continue
        cid, uid = chat.get("id"), author.get("id")
        if chat.get("type") == "private" and type(cid) is int and cid == uid:
            matched.add(cid)
    if len(matched) > 1:
        raise ValueError("Pairing challenge was matched by multiple users")
    return next(iter(matched)) if matched else None


def save_verified_chat(token, old_chat, new_chat, path=SECRET, owner_uid=0):
    """Atomic replacement; refuses concurrent credential changes and unsafe files."""
    path = Path(path)
    old_stat = path.lstat()
    if not path.is_file() or path.is_symlink() or old_stat.st_uid != owner_uid:
        raise ValueError("Unsafe Telegram secret ownership or type")
    if old_stat.st_mode & 0o077:
        raise ValueError("Unsafe Telegram secret permissions")
    with path.open(encoding="utf-8") as handle:
        current = json.load(handle)
    if current.get("token") != token or str(current.get("chat_id")) != old_chat:
        raise ValueError("Telegram credentials changed during pairing")
    if type(new_chat) is not int or new_chat <= 0:
        raise ValueError("Only positive private Telegram chat IDs are accepted")
    temp = path.with_name(path.name + ".pair-new")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": token, "chat_id": str(new_chat)}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dirfd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if temp.exists():
            temp.unlink()


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    notify = load_notify()
    try:
        token, old_chat = notify.load_secret()
    except (OSError, ValueError, json.JSONDecodeError):
        print("CREDENTIALS_UNAVAILABLE_OR_UNSAFE")
        return 2
    if old_chat != "1":
        print("REFUSE: chat ID no longer equals the known incorrect placeholder 1.")
        return 2
    routes = notify.route_order()
    good_routes = []
    username = None
    for route in routes:
        result, status = telegram_request(token, route, "getMe")
        if status == 401:
            print("TELEGRAM_TOKEN_REJECTED")
            return 2
        if status == 200 and isinstance(result, dict):
            identity = result.get("username")
            if not isinstance(identity, str) or not BOT_USERNAME.fullmatch(identity):
                print("BOT_USERNAME_INVALID")
                return 2
            if username and username.lower() != identity.lower():
                print("BOT_IDENTITY_CONFLICT")
                return 2
            username = identity
            good_routes.append(route)
    if not good_routes:
        print("NO_WORKING_BOT_API_ROUTE")
        return 1
    print("CONFIRMED_BOT=https://t.me/" + username, flush=True)
    print("Open that exact private bot chat. Press Start or send /start.", flush=True)
    challenge = secrets.token_hex(8)
    print("Then send exactly: /pair " + challenge, flush=True)
    print("PAIR_POLLING=ACTIVE (up to 120 seconds; no Enter needed)", flush=True)
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        for route in good_routes:
            items, status = telegram_request(token, route, "getUpdates")
            if status == 409:
                print("PAIR_FAILED=TELEGRAM_POLLING_CONFLICT_OR_WEBHOOK")
                return 1
            if status != 200 or not isinstance(items, list):
                continue
            if len(items) == 100:
                print("PAIR_FAILED=FIRST_100_UPDATES_FULL; refusing to discard messages")
                return 1
            try:
                chat = find_private_challenge(items, challenge)
            except ValueError:
                print("PAIR_FAILED=MULTIPLE_USERS")
                return 1
            if chat is not None:
                try:
                    save_verified_chat(token, old_chat, chat)
                except (OSError, ValueError, json.JSONDecodeError):
                    print("PAIR_FAILED=SECURE_SAVE")
                    return 1
                print("PAIR_VERIFIED=YES")
                print("CHAT_ID_REPLACED=YES")
                print("NO_MESSAGE_SENT=YES")
                return 0
        time.sleep(2)
    print("PAIR_FAILED=TIMEOUT; credentials unchanged")
    return 1


if __name__ == "__main__":
    sys.exit(main())
