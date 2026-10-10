#!/usr/bin/env python3
"""Offline, read-only summary of an AWG Pi Gateway Mihomo health-pool snapshot.

No networking, no provider credentials, no endpoint/name disclosure, no writes.
A failed health probe is NOT proof of DPI interference.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


def failure_reason(node: dict) -> str:
    if node.get("healthy") is True:
        return "healthy"
    error = str(node.get("error") or "").strip()
    if node.get("duplicate_name") or error == "duplicate-name":
        return "duplicate_name"
    if error in {"not-a-mapping", "invalid-metadata", "invalid-port"}:
        return "invalid_definition"
    if error == "proxy-not-loaded":
        return "proxy_not_loaded"
    if error.startswith("http-") and error[5:].isdigit():
        # Response from local Mihomo controller, NOT necessarily remote server.
        return "mihomo_api_http_error"
    if error == "no-delay":
        return "no_positive_delay"
    if error in {
        "TimeoutError", "URLError", "ConnectionError", "ConnectionRefusedError",
        "ConnectionResetError", "RemoteDisconnected", "BrokenPipeError",
        "OSError", "SSLError", "IncompleteRead",
    }:
        # Controller exceptions do not identify failing DNS/TCP/TLS stage.
        return "undifferentiated_probe_exception"
    return "unclassified"


def summarize(payload: dict, *, now: int | None = None) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise ValueError("expected Mihomo pool JSON object with a nodes list")
    nodes = payload["nodes"]
    by_type = defaultdict(lambda: {"healthy": 0, "failed": 0, "endpoints": set()})
    reasons = Counter()
    endpoint_states: dict[tuple[str, int], list[bool]] = defaultdict(list)
    healthy = 0
    valid_endpoints = 0
    for node in nodes:
        if not isinstance(node, dict):
            reasons["invalid_definition"] += 1
            continue
        ptype = str(node.get("type") or "unknown").lower()
        item = by_type[ptype]
        ok = node.get("healthy") is True
        item["healthy" if ok else "failed"] += 1
        healthy += int(ok)
        reasons[failure_reason(node)] += 1

        address = node.get("server")
        port = node.get("port")
        if isinstance(address, str) and address and isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            endpoint = (address, port)
            item["endpoints"].add(endpoint)
            endpoint_states[endpoint].append(ok)
            valid_endpoints += 1

    endpoints = list(endpoint_states.values())
    by_protocol = {}
    for ptype, item in sorted(by_type.items()):
        by_protocol[ptype] = {
            "healthy_profiles": item["healthy"],
            "failed_profiles": item["failed"],
            "distinct_host_ports": len(item["endpoints"]),
        }
    scanned_at = payload.get("scanned_at")
    current = int(time.time()) if now is None else now
    age = max(0, current - scanned_at) if isinstance(scanned_at, int) and scanned_at > 0 else None
    return {
        "audit_type": "passive_snapshot",
        "network_probes": 0,
        "dpi_confirmed": 0,
        "dpi_assessment": "not_possible_from_saved_health_scan",
        "snapshot_timestamp_utc": (
            datetime.fromtimestamp(scanned_at, tz=timezone.utc).isoformat()
            if isinstance(scanned_at, int) and 0 < scanned_at < 4102444800 else None
        ),
        "snapshot_age_seconds": age,
        "source_total": payload.get("source_total"),
        "scanned_profiles": len(nodes),
        "healthy_profiles": healthy,
        "failed_profiles": len(nodes) - healthy,
        "failure_categories": {k: v for k, v in sorted(reasons.items()) if k != "healthy"},
        "unique_host_ports": len(endpoint_states),
        "valid_endpoint_profiles": valid_endpoints,
        "endpoints_all_failed": sum(1 for flags in endpoints if not any(flags)),
        "endpoints_all_healthy": sum(1 for flags in endpoints if all(flags)),
        "endpoints_mixed": sum(1 for flags in endpoints if any(flags) and not all(flags)),
        "by_protocol": by_protocol,
        "note": (
            "Health errors reflect a single HTTPS-through-proxy probe, not a "
            "diagnosis of DNS, TCP, TLS, authorization, routing or DPI. "
            "Different host:port entries may share one IP/provider."
        ),
    }


def show(report: dict) -> None:
    print("MIHOMO DPI AUDIT - PASSIVE / NO NETWORK")
    print("Snapshot UTC:", report["snapshot_timestamp_utc"] or "unknown")
    print("Age (seconds):", report["snapshot_age_seconds"])
    print("Scanned:", report["scanned_profiles"], "Healthy:", report["healthy_profiles"],
          "Failed:", report["failed_profiles"])
    print("Endpoint pairs (host:port):", report["unique_host_ports"])
    print("Endpoint health: all_failed={endpoints_all_failed} all_healthy={endpoints_all_healthy} mixed={endpoints_mixed}".format(**report))
    print("Failure categories (profile counts):")
    for reason, count in report["failure_categories"].items():
        print(" ", reason, "=", count)
    print("By protocol (healthy / failed / unique_host_ports):")
    for proto, data in report["by_protocol"].items():
        print(" ", proto, "=", data["healthy_profiles"], "/", data["failed_profiles"],
              "/", data["distinct_host_ports"])
    print("DPI confirmed: NOT MEASURABLE with this snapshot")
    print("No secrets, node names or endpoints are printed.")


def self_test() -> None:
    sample = {
        "scanned_at": 100,
        "source_total": 5,
        "nodes": [
            {"type": "vless", "server": "a.example", "port": 443, "healthy": True, "error": ""},
            {"type": "vless", "server": "a.example", "port": 443, "healthy": False, "error": "TimeoutError"},
            {"type": "trojan", "server": "b.example", "port": 443, "healthy": False, "error": "no-delay"},
            {"type": "ss", "server": "c.example", "port": 9999, "healthy": False, "error": "invalid-port"},
            {"type": "ss", "server": "c.example", "port": 9999, "healthy": True, "error": ""},
        ],
    }
    result = summarize(sample, now=150)
    assert result["healthy_profiles"] == 2
    assert result["failed_profiles"] == 3
    assert result["unique_host_ports"] == 3
    assert result["endpoints_mixed"] == 2
    assert result["endpoints_all_failed"] == 1
    assert result["failure_categories"]["undifferentiated_probe_exception"] == 1
    assert result["snapshot_age_seconds"] == 50
    assert result["dpi_assessment"] == "not_possible_from_saved_health_scan"
    print("SELFTEST=PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("/run/awg-pbr/mihomo-pool/live.json"))
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        with args.input.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        result = summarize(payload)
    except (OSError, ValueError, json.JSONDecodeError, TypeError, OverflowError) as exc:
        # Do not reveal file contents or paths in exceptions.
        print("AUDIT_ERROR: unavailable or invalid health-pool snapshot (" +
              type(exc).__name__ + ")", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        show(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
