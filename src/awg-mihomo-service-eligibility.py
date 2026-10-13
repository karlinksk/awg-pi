#!/usr/bin/env python3
"""Fresh per-node YouTube + ChatGPT eligibility from AUTO SMART SHADOW_ONLY.

This validator is READ ONLY. It never changes selection or routes.
PASS requires both services confirmed for the same exact subscribed node in
a current root-owned report tied to the current provider digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

REPORT = Path("/run/awg-pbr/mihomo-smart/last.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
TTL_SECONDS = 1800
REQUIRED_CHECKS = ("openai_api", "chatgpt_web", "youtube_video")

class Rejected(Exception):
    pass

def private_file(path: Path, owner: int | None, *, max_size=2_000_000):
    if path.is_symlink():
        raise Rejected("SYMLINK_FILE")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_size:
        raise Rejected("INVALID_FILE")
    if owner is not None and (info.st_uid != owner or stat.S_IMODE(info.st_mode) & 0o077):
        raise Rejected("UNTRUSTED_OWNER_OR_PERMISSIONS")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        current = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise Rejected("FILE_REPLACED")
        with os.fdopen(fd, "rb") as reader:
            fd = -1
            result = reader.read(max_size + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(result) > max_size:
        raise Rejected("OVERSIZE_FILE")
    return result

def private_directory(path: Path, owner: int):
    st = path.lstat()
    if (path.is_symlink() or not stat.S_ISDIR(st.st_mode)
            or st.st_uid != owner or stat.S_IMODE(st.st_mode) != 0o700):
        raise Rejected("UNTRUSTED_REPORT_DIRECTORY")

def node_state(report: dict, *, name: str, source_sha256: str, now: int, max_age: int = TTL_SECONDS):
    if not isinstance(report, dict) or report.get("version") != 2 or report.get("mode") != "shadow":
        return "UNKNOWN", "UNSUPPORTED_REPORT"
    if report.get("production_modified") is not False or report.get("switches_made") != 0:
        return "UNKNOWN", "MUTATING_REPORT_UNTRUSTED"
    if report.get("source_sha256") != source_sha256:
        return "UNKNOWN", "PROVIDER_CHANGED"
    timestamp = report.get("timestamp")
    if type(timestamp) is not int or timestamp > now + 15 or now - timestamp > max_age:
        return "UNKNOWN", "STALE_OR_FUTURE_REPORT"
    rows = report.get("results")
    if not isinstance(rows, list) or len(rows) > 15:
        return "UNKNOWN", "BAD_RESULTS"
    matches = [r for r in rows if isinstance(r, dict) and r.get("name") == name]
    if len(matches) != 1:
        return "UNKNOWN", "MISSING_OR_AMBIGUOUS_NODE"
    row = matches[0]
    if row.get("service_state") == "FAIL":
        return "FAIL", "SERVICE_REJECTED"
    if row.get("service_state") != "PASS" or row.get("service_ok") is not True:
        return "UNKNOWN", "SERVICES_UNVERIFIED"
    checks = row.get("service_checks")
    if not isinstance(checks, dict) or any(
            not isinstance(checks.get(k), dict) or checks[k].get("state") != "PASS"
            for k in REQUIRED_CHECKS):
        return "UNKNOWN", "INCOMPLETE_SERVICES"
    if not all(row.get(k) is True for k in
               ("warmup_ok", "ok", "sustained_verified", "confirmed")):
        return "UNKNOWN", "PERFORMANCE_UNCONFIRMED"
    return "PASS", "FRESH_BOTH_SERVICES_CONFIRMED"

def fixture_root(path: str):
    candidate = Path(path).absolute()
    actual = candidate.resolve(strict=True)
    if (actual != candidate or actual.parent != Path("/tmp").resolve()
            or not actual.name.startswith("awg-eligibility-")):
        raise Rejected("UNSAFE_FIXTURE_ROOT")
    private_directory(actual, os.geteuid())
    # In tests, the report and fake provider are strictly fixture-local.
    return actual

def assess(name: str, report_path: Path, provider_path: Path, *, owner: int | None, now: int, max_age: int):
    if not name or len(name) > 300 or any(x in name for x in ("\n", "\r", "\x00")):
        return "UNKNOWN", "INVALID_NODE_NAME"
    if owner is not None:
        private_directory(report_path.parent, owner)
    data = private_file(report_path, owner)
    digest = hashlib.sha256(private_file(provider_path, owner=None)).hexdigest()
    try:
        report = json.loads(data)
    except (ValueError, UnicodeError):
        return "UNKNOWN", "INVALID_REPORT_JSON"
    return node_state(report, name=name, source_sha256=digest, now=now, max_age=max_age)

def main():
    p=argparse.ArgumentParser(description="read-only strict per-node service gate")
    p.add_argument("--node", required=True)
    p.add_argument("--fixture-root", default="")
    p.add_argument("--max-age", type=int, default=TTL_SECONDS)
    args=p.parse_args()
    if not 60 <= args.max_age <= 3600:
        p.error("max-age must be 60..3600 seconds")
    try:
        if args.fixture_root:
            root=fixture_root(args.fixture_root)
            report, provider, owner=root/"last.json", root/"subscription.yaml", os.geteuid()
        else:
            if os.geteuid() != 0:
                raise Rejected("LIVE_GATE_REQUIRES_ROOT")
            report,provider,owner=REPORT,PROVIDER,0
        state,reason=assess(args.node,report,provider,owner=owner,
                            now=int(time.time()),max_age=args.max_age)
    except (Rejected,OSError,ValueError) as exc:
        state,reason="UNKNOWN",str(exc) if isinstance(exc,Rejected) else type(exc).__name__
    print("SERVICE_ELIGIBILITY="+state)
    print("SERVICE_REASON="+reason)
    return 0 if state=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
