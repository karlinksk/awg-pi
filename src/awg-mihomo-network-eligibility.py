#!/usr/bin/env python3
"""Medium-confidence NETWORK suitability for ChatGPT+YouTube Mihomo candidate.

No browser, cookies, account session, or full-chat claim.
Requires OpenAI API and an actual YouTube 24-frame decode; ChatGPT web
must return a real HTML page or known anti-bot challenge, not a timeout.
"""
from __future__ import annotations
import re
import sys

REQUIRED = (
    "SERVICE_ELIGIBILITY",
    "SERVICE_CHECK_OPENAI_API",
    "SERVICE_CHECK_CHATGPT_WEB",
    "SERVICE_CHECK_YOUTUBE_VIDEO",
    "SERVICE_REASON_CHATGPT_WEB",
)
ACCEPTED_WEB_CHALLENGE = frozenset((
    "chatgpt_web_antibot_challenge",
    "chatgpt_web_challenge",
    "chatgpt_web_login_only",
    # A generic HTTP 403 still proves HTTPS reached ChatGPT's endpoint.
    # It does NOT prove web app functionality; this is explicitly only
    # MEDIUM network confidence alongside OpenAI API + decoded video.
    "chatgpt_web_http_403",
))
SAFE_VALUE = re.compile(r"^[A-Za-z0-9_]+$")


def qualify(output: str) -> tuple[str, str]:
    if len(output) > 8192:
        return "UNKNOWN", "OVERSIZE_CHECK"
    fields = {}
    for line in output.splitlines():
        if "=" not in line:
            return "UNKNOWN", "BAD_CHECK_FORMAT"
        key, value = line.split("=", 1)
        if key not in REQUIRED and key not in ("SERVICE_EGRESS_IPV4",):
            return "UNKNOWN", "UNEXPECTED_CHECK_FIELD"
        if key in fields or not SAFE_VALUE.fullmatch(value or "invalid"):
            # Egress address is not needed for medium-confidence status;
            # service-scan can print IPv4 with dots.
            if not (key == "SERVICE_EGRESS_IPV4" and
                    key not in fields and re.fullmatch(r"[0-9.]{7,15}", value or "")):
                return "UNKNOWN", "BAD_OR_DUPLICATE_CHECK_FIELD"
        fields[key] = value
    if not all(key in fields for key in REQUIRED):
        return "UNKNOWN", "MISSING_CHECK_FIELD"
    if fields["SERVICE_CHECK_OPENAI_API"] != "PASS":
        return "UNKNOWN", "OPENAI_API_NOT_CONFIRMED"
    if fields["SERVICE_CHECK_YOUTUBE_VIDEO"] != "PASS":
        return "UNKNOWN", "YOUTUBE_VIDEO_NOT_DECODED"
    web = fields["SERVICE_CHECK_CHATGPT_WEB"]
    reason = fields["SERVICE_REASON_CHATGPT_WEB"]
    if web == "PASS" and reason == "chatgpt_web_http_200":
        pass
    elif web == "UNKNOWN" and reason in ACCEPTED_WEB_CHALLENGE:
        pass
    else:
        return "UNKNOWN", "CHATGPT_NETWORK_UNCONFIRMED"
    if fields["SERVICE_ELIGIBILITY"] not in ("PASS", "UNKNOWN"):
        return "UNKNOWN", "SERVICE_AGGREGATE_REJECTED"
    return "ELIGIBLE", "MEDIUM_NETWORK_CONFIDENCE"


def main() -> int:
    content = sys.stdin.read(8193)
    status, reason = qualify(content)
    print("NETWORK_ELIGIBILITY=" + status)
    print("NETWORK_REASON=" + reason)
    # For shell failover: exact positive only. Not equivalent to a logged-in chat.
    return 0 if status == "ELIGIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
