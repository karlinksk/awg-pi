#!/usr/bin/env python3
"""Service-FIRST candidate qualification; pure state reducer, SHADOW_ONLY.

A fast handshake or a low ping is NOT real application availability.
Two distinct independent service probe samples, from the SAME candidate
and runtime context, are needed before a candidate becomes SERVICE_READY.
A candidate may be SERVICE_READY but ROUTE_PENDING until the separate,
on-demand, exact-endpoint underlay proof is independently verified.

No imports of route writers, SSH clients, systemd services or user secrets.
"""
from __future__ import annotations

import re
from typing import Any

REQUIRED = ("openai_api", "chatgpt_web", "youtube_video")
STATES = ("PASS", "FAIL", "UNKNOWN")
CONFIRMATIONS = 2
MAX_AGE = 180
REASON = re.compile(r"^[a-zA-Z0-9_-]{1,96}$")
SAMPLE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")


def normalized(outcome: object, name: str) -> dict:
    unknown = {"status": "UNKNOWN", "sample_id": "", "checks": {},
               "reason": "invalid_or_missing_service_evidence"}
    if not isinstance(outcome, dict) or outcome.get("transport") != "mihomo":
        return unknown
    if not isinstance(name, str) or not name or outcome.get("identity") != name:
        return unknown
    checks = outcome.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REQUIRED):
        return unknown
    clean = {}
    for key in REQUIRED:
        item = checks[key]
        if not isinstance(item, dict) or item.get("state") not in STATES:
            return unknown
        reason = item.get("reason")
        clean[key] = {"state": item["state"],
                      "reason": reason if isinstance(reason, str) and
                      REASON.fullmatch(reason) else "not_verified"}
    states = [clean[k]["state"] for k in REQUIRED]
    summary = ("PASS" if all(s == "PASS" for s in states)
               else "FAIL" if "FAIL" in states else "UNKNOWN")
    sample = outcome.get("sample_id")
    if not isinstance(sample, str) or not SAMPLE.fullmatch(sample):
        return unknown
    if outcome.get("status") != summary:
        return unknown
    return {"status": summary, "sample_id": sample, "checks": clean,
            "reason": "all_required_services_passed" if summary == "PASS"
                      else "service_failed" if summary == "FAIL"
                      else "service_inconclusive"}


def advance(previous: dict | None, outcome: object, *,
            identity: str, fingerprint: str, boot_id: str,
            policy_generation: int | None, checked_at: int,
            ttl: int = MAX_AGE) -> dict:
    """Pure per-node update. Stored output is evidence, NEVER switch permission."""
    if (not isinstance(fingerprint, str) or not re.fullmatch("[a-f0-9]{64}", fingerprint)
            or not isinstance(boot_id, str) or not boot_id or len(boot_id) > 128
            or not isinstance(checked_at, int) or isinstance(checked_at, bool)
            or not isinstance(ttl, int) or not 1 <= ttl <= 600):
        raise ValueError("invalid immutable qualification context")
    proof = normalized(outcome, identity)
    old = previous if isinstance(previous, dict) else {}
    if not isinstance(policy_generation, int) or isinstance(policy_generation, bool):
        generation = -1
    else:
        generation = policy_generation
    coherent = (
        proof["status"] == "PASS"
        and old.get("service_status") == "PASS"
        and old.get("identity") == identity
        and old.get("fingerprint") == fingerprint
        and old.get("boot_id") == boot_id
        and old.get("policy_generation") == generation
        and isinstance(old.get("service_checked_at"), int)
        and 0 <= checked_at - old["service_checked_at"] <= ttl
        and isinstance(old.get("service_sample_id"), str)
        and bool(old["service_sample_id"])
        and old["service_sample_id"] != proof["sample_id"]
    )
    count = (min(CONFIRMATIONS, int(old.get("service_confirmations", 0)) + 1)
             if coherent else 1 if proof["status"] == "PASS" else 0)
    # Missing local-event generation allows service telemetry only, not
    # an automated claim that this is a reliable retained warm spare.
    ready = (count >= CONFIRMATIONS and generation >= 0)
    status = ("SERVICE_READY" if ready else
              "SERVICE_PENDING_CONFIRMATION" if count else
              "SERVICE_FAILED" if proof["status"] == "FAIL" else
              "SERVICE_UNKNOWN")
    return {"service_status": proof["status"],
            "service_qualification": status,
            "service_confirmations": count,
            "service_checked_at": checked_at,
            "service_sample_id": proof["sample_id"],
            "service_checks": proof["checks"],
            "service_reason": proof["reason"],
            "identity": identity,
            "fingerprint": fingerprint,
            "boot_id": boot_id,
            "policy_generation": generation,
            "service_qualified": ready}


def ready_entry(entry: dict, *, now: int, ttl: int = MAX_AGE) -> bool:
    return (isinstance(entry, dict)
            and entry.get("service_qualified") is True
            and entry.get("service_status") == "PASS"
            and entry.get("service_qualification") == "SERVICE_READY"
            and entry.get("service_confirmations") == CONFIRMATIONS
            and isinstance(entry.get("policy_generation"), int)
            and entry["policy_generation"] >= 0
            and isinstance(entry.get("service_checked_at"), int)
            and 0 <= now - entry["service_checked_at"] <= ttl
            and all(isinstance(entry.get("service_checks", {}).get(k), dict) and
                    entry["service_checks"][k].get("state") == "PASS" for k in REQUIRED))


def summary(entries: dict, nodes: list[dict], *, now: int,
            ttl: int = MAX_AGE, limit: int = 2) -> list[str]:
    """Service-ready candidates; route attestation remains a SEPARATE gate."""
    counts = {}
    for n in nodes:
        counts[n["name"]] = counts.get(n["name"], 0) + 1
    eligible = [n for n in nodes if counts[n["name"]] == 1
                and n["name"] in entries
                and entries[n["name"]].get("fingerprint") == n.get("fingerprint")
                and ready_entry(entries[n["name"]], now=now, ttl=ttl)]
    eligible.sort(key=lambda n: (n.get("delay_ms") or 999999, n["name"]))
    selected, endpoints = [], set()
    for n in eligible:
        endpoint = (n.get("server"), n.get("port"))
        if endpoint in endpoints:
            continue
        selected.append(n["name"])
        endpoints.add(endpoint)
        if len(selected) >= limit:
            break
    return selected
