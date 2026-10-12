#!/usr/bin/env python3
"""Lightweight active Mihomo region-failure sensor. Advisory only.

This deliberately checks just one small OpenAI API response through the
production loopback Mihomo proxy. PASS means *API region accessible*, NOT
ChatGPT web and YouTube usable. A confirmed region rejection can trigger
an immediate full service recheck, but NEVER a route switch by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

SERVICE = Path(__file__).with_name("awg-mihomo-service-check.py")
NODE_FILE = Path("/etc/awg-pbr/transports/mihomo/node-name")
TRANSPORT_FILE = Path("/etc/awg-pbr/transport")
ROOT = Path("/run/awg-pbr/service-fast")
STATE = ROOT / "active.json"
PROXY_PORT = 7890


def service_code():
    loader = importlib.machinery.SourceFileLoader("awg_fast_service", str(SERVICE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


def read_identity(node_file=NODE_FILE, transport_file=TRANSPORT_FILE) -> str:
    """Fail closed on unreadable or changing selected-node identity."""
    if transport_file.read_text("utf-8").strip() != "mihomo":
        return ""
    if node_file.stat().st_size > 512:
        return ""
    node = node_file.read_text("utf-8").strip()
    if not node or "\n" in node or "\r" in node or len(node) > 256:
        return ""
    return node


def quick_probe(*, port=PROXY_PORT, timeout=3.0, request=None) -> dict:
    gate = service_code()
    if request is None:
        request = lambda url, **kwargs: gate.fetch(
            port, url, timeout=timeout, max_bytes=min(kwargs.get("max_bytes", 8192), 8192))
    result = gate.openai_probe(request)
    region = {
        ("PASS", "openai_api_auth_required"): "API_REGION_OK",
        ("FAIL", "openai_unsupported_region"): "REGION_BLOCKED",
    }.get((result.state, result.reason), "UNKNOWN")
    return {"region": region, "reason": result.reason,
            "sample_id": uuid.uuid4().hex, "checked_at": int(time.time()),
            "monotonic_ms": int(time.monotonic() * 1000)}


def update(current: dict, previous: dict | None, identity: str, *,
           blocked_confirmations: int = 2) -> dict:
    if blocked_confirmations < 2:
        raise ValueError("at least two confirmed regional blocks are required")
    prev = previous if isinstance(previous, dict) else {}
    same_node = prev.get("identity") == identity
    same_boot = prev.get("boot_id") == boot_id()
    distinct = prev.get("sample_id") != current.get("sample_id")
    old_counter = int(prev.get("consecutive_blocks", 0)) if same_node and same_boot else 0
    if current["region"] == "REGION_BLOCKED" and distinct:
        streak = min(blocked_confirmations, old_counter + 1)
    else:
        streak = 0
    result = {**current, "identity": identity, "transport": "mihomo",
              "boot_id": boot_id(), "consecutive_blocks": streak,
              "urgent_service_confirmation": streak >= blocked_confirmations,
              "mode": "ADVISORY_ONLY"}
    return result


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text("utf-8").strip()
    except OSError:
        return "boot_unknown"


def load(path: Path, identity: str) -> dict:
    try:
        if path.stat().st_size > 8192:
            return {}
        raw = json.loads(path.read_text("utf-8"))
        if (not isinstance(raw, dict) or raw.get("identity") != identity or
                raw.get("boot_id") != boot_id()):
            return {}
        return raw
    except (OSError, ValueError, TypeError):
        return {}


def atomic(path: Path, value: dict) -> None:
    if not str(path).startswith("/run/awg-pbr/service-fast/"):
        raise ValueError("only RAM service-fast directory is writable")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, filename = tempfile.mkstemp(dir=path.parent, prefix=".fast-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True, separators=(",", ":"))
            f.write("\n")
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def scan(*, port=PROXY_PORT, timeout=3.0, read_node=read_identity,
         probe=quick_probe, path=STATE) -> dict:
    try:
        first = read_node()
    except (OSError, ValueError):
        first = ""
    if not first:
        return {"mode": "ADVISORY_ONLY", "region": "UNKNOWN",
                "reason": "no_active_mihomo", "urgent_service_confirmation": False}
    current = probe(port=port, timeout=timeout)
    try:
        second = read_node()
    except (OSError, ValueError):
        second = ""
    if first != second:
        return {"mode": "ADVISORY_ONLY", "region": "UNKNOWN",
                "reason": "node_changed_during_probe", "urgent_service_confirmation": False}
    value = update(current, load(path, first), first)
    atomic(path, value)
    return value


def interval(status: str, failures: int = 0) -> int:
    # No heavy video stream or benchmark. Error storms do not flood endpoints.
    if status == "REGION_BLOCKED":
        return 10
    if status == "API_REGION_OK":
        return 20
    return min(120, 20 * (2 ** min(max(failures, 0), 3)))


def view(value: dict) -> dict:
    return {k: value.get(k) for k in
            ("mode", "region", "reason", "checked_at", "consecutive_blocks",
             "urgent_service_confirmation")}


def watch(*, poll=scan, sleeper=time.sleep, cycles=None) -> None:
    attempts = 0
    error_streak = 0
    while cycles is None or attempts < cycles:
        try:
            value = poll()
            error_streak = 0 if value.get("region") != "UNKNOWN" else error_streak + 1
        except (OSError, ValueError, RuntimeError):
            value = {"mode": "ADVISORY_ONLY", "region": "UNKNOWN",
                     "reason": "probe_error", "urgent_service_confirmation": False}
            error_streak += 1
        print(json.dumps(view(value), sort_keys=True), flush=True)
        attempts += 1
        if cycles is not None and attempts >= cycles:
            break
        sleeper(interval(value["region"], error_streak))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "watch", "show"))
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    if not (1 <= args.timeout <= 5):
        parser.error("timeout must be 1..5 seconds")
    if args.command == "show":
        try:
            payload = json.loads(STATE.read_text("utf-8"))
        except (OSError, ValueError):
            payload = {"mode": "ADVISORY_ONLY", "region": "UNKNOWN"}
        print(json.dumps(view(payload), sort_keys=True))
        return 0
    if args.command == "watch":
        watch(poll=lambda: scan(timeout=args.timeout))
        return 0
    value = scan(timeout=args.timeout)
    print(json.dumps(view(value), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
