#!/usr/bin/env python3
"""Safe, read-only AWG Notify Telegram pairing diagnostics.

Reads existing root-only bot credentials; never prints token, chat id, private
messages, usernames, webhook URL, or raw Bot API responses. Makes no route,
DNS, VPN, firewall, webhook, update-offset, or credential changes.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys

SOURCE = "/usr/local/sbin/awg-notify"
MAX_RESPONSE = 262144


def load_notify():
    loader = importlib.machinery.SourceFileLoader("awg_notify_installed", SOURCE)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def call_api(token, route, method):
    if route not in ("mihomo0", "awg0", "eth0"):
        raise ValueError("unsupported route")
    if method not in ("getMe", "getWebhookInfo", "getUpdates"):
        raise ValueError("unsupported API method")
    url = "https://api.telegram.org/bot" + token + "/" + method
    config = 'url = "' + url + '"\n'
    if method == "getUpdates":
        # Offset omitted: no confirmation/consumption of existing updates.
        config += 'data = "timeout=0&limit=100"\n'
    argv = ["curl", "-q", "--config", "-", "--ipv4", "--proto", "=https",
            "--noproxy", "*", "--interface", "if!" + route,
            "--connect-timeout", "4", "--max-time", "10",
            "--silent", "--write-out", "\n%{http_code}"]
    try:
        reply = subprocess.run(argv, input=config, text=True,
                               capture_output=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"result": "NO_CONNECTION"}
    if reply.returncode:
        return {"result": "NO_CONNECTION"}
    if len(reply.stdout) > MAX_RESPONSE:
        return {"result": "RESPONSE_TOO_LARGE"}
    body, sep, status = reply.stdout.rpartition("\n")
    if not sep or not status.isdigit():
        return {"result": "MALFORMED_RESPONSE"}
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return {"result": "NON_JSON", "http": int(status)}
    if not isinstance(data, dict):
        return {"result": "NON_OBJECT", "http": int(status)}
    answer = {"result": "OK" if status == "200" and data.get("ok") is True
              else "API_REJECTED", "http": int(status)}
    if answer["result"] != "OK":
        # Error code alone is sufficient; raw response description can
        # contain URLs, credentials and user information.
        answer["error_code"] = data.get("error_code") if type(data.get("error_code")) is int else 0
        return answer
    result = data.get("result")
    if method == "getUpdates":
        if not isinstance(result, list):
            answer["result"] = "INVALID_UPDATES"
            return answer
        answer["updates"] = len(result)
        messages = [x["message"] for x in result
                    if isinstance(x, dict) and isinstance(x.get("message"), dict)]
        answer["messages"] = len(messages)
        answer["private_messages"] = sum(
            1 for x in messages
            if isinstance(x.get("chat"), dict) and x["chat"].get("type") == "private")
        answer["private_pair_commands"] = sum(
            1 for x in messages if isinstance(x.get("chat"), dict)
            and x["chat"].get("type") == "private"
            and isinstance(x.get("text"), str)
            and x["text"].startswith("/pair "))
        answer["over_original_limit"] = len(reply.stdout) > 65536
    if method == "getWebhookInfo":
        answer["webhook_configured"] = bool(
            isinstance(result, dict) and result.get("url"))
    return answer


def main():
    if os.geteuid() != 0:
        print("ROOT_REQUIRED")
        return 2
    notify = load_notify()
    try:
        token, chat = notify.load_secret()
    except (OSError, ValueError, json.JSONDecodeError):
        print("SAVED_CREDENTIALS=UNAVAILABLE_OR_INVALID")
        return 1
    print("SAVED_CREDENTIALS=VALID_FORMAT_AND_PERMISSIONS")
    print("STORED_CHAT_ID_PLACEHOLDER=" + ("YES" if chat == "1" else "NO"))
    routes = notify.route_order()
    print("ALLOWED_PATHS=" + ",".join(routes))
    for route in routes:
        for method in ("getMe", "getWebhookInfo", "getUpdates"):
            response = call_api(token, route, method)
            labels = [f"{key}:{value}" for key, value in response.items()]
            print(f"{route} {method} " + " ".join(labels))
            if method == "getMe" and response.get("result") == "API_REJECTED" and response.get("http") == 401:
                print("CONCLUSION=TOKEN_REJECTED_BY_TELEGRAM")
                return 0
            if method == "getWebhookInfo" and response.get("webhook_configured") is True:
                print("CONCLUSION=WEBHOOK_CONFIGURED_GETUPDATES_WILL_NOT_WORK")
                return 0
    print("CONCLUSION=REVIEW_SANITIZED_STATUSES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
