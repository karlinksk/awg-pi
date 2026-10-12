#!/usr/bin/env python3
"""Dry-run service-aware selector adapter. Never writes production routes.

Input is evidence from independent checker workers. The legacy
awg-selection-monitor remains the SOLE owner of transport switching.
"""
from __future__ import annotations
from dataclasses import asdict
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

POLICY_PY = Path(__file__).with_name("awg-failover-policy.py")
DEFAULT_TTL = 120


def load_policy():
    loader = importlib.machinery.SourceFileLoader("awg_dry_run_policy", str(POLICY_PY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def checked_status(entry: object, *, now: int, transport: str,
                   ttl: int = DEFAULT_TTL, identity: str = "") -> tuple[str, str]:
    """Never trust stale, misattributed or malformed probe evidence."""
    if not isinstance(entry, dict):
        return "UNKNOWN", ""
    if entry.get("transport") != transport:
        return "UNKNOWN", ""
    if identity and entry.get("identity") != identity:
        return "UNKNOWN", ""
    checked = entry.get("checked_at")
    if not isinstance(checked, int) or isinstance(checked, bool):
        return "UNKNOWN", ""
    if checked > now or now - checked > ttl:
        return "UNKNOWN", ""
    status = entry.get("status")
    if status not in ("PASS", "FAIL", "UNKNOWN"):
        return "UNKNOWN", ""
    # Avoid mistaking a repeatedly read cached value for new evidence.
    sample = entry.get("sample_id")
    if not isinstance(sample, str) or not 1 <= len(sample) <= 96:
        return "UNKNOWN", ""
    if not all(c.isalnum() or c in "-_:." for c in sample):
        return "UNKNOWN", ""
    # Only exact, independently verified service results are trustworthy.
    checks = entry.get("checks")
    if not isinstance(checks, dict):
        return "UNKNOWN", ""
    for key in ("openai_api", "chatgpt_web", "youtube_video"):
        if key not in checks or not isinstance(checks[key], dict):
            return "UNKNOWN", ""
        if checks[key].get("state") not in ("PASS", "FAIL", "UNKNOWN"):
            return "UNKNOWN", ""
    independent = [checks[key]["state"] for key in
                   ("openai_api", "chatgpt_web", "youtube_video")]
    expected = ("PASS" if all(x == "PASS" for x in independent)
                else "FAIL" if any(x == "FAIL" for x in independent)
                else "UNKNOWN")
    if status != expected:
        return "UNKNOWN", ""
    return status, sample


def standby_ready(node_state: object, *, now: int, ttl: int = DEFAULT_TTL,
                  provider_sha: str = "") -> tuple[str, ...]:
    if not isinstance(node_state, dict) or node_state.get("mode") != "SHADOW_ONLY":
        return ()
    if not provider_sha or node_state.get("provider_sha256") != provider_sha:
        return ()
    generated = node_state.get("generated_at")
    if not isinstance(generated, int) or generated > now or now - generated > ttl:
        return ()
    warm = node_state.get("warm")
    entries = node_state.get("entries")
    if not isinstance(warm, list) or not isinstance(entries, dict):
        return ()
    accepted = []
    for name in warm[:2]:
        if not isinstance(name, str) or not name or name in accepted:
            continue
        row = entries.get(name)
        if not isinstance(row, dict) or row.get("status") != "PASS":
            continue
        checked = row.get("checked_at")
        if not isinstance(checked, int) or checked > now or now - checked > ttl:
            continue
        fingerprint = row.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            continue
        # The node must have three checks attributed to this precise warm
        # candidate. A legacy cache flag alone is not authorization.
        checked, sample = checked_status(row, now=now, transport="mihomo",
                                         ttl=ttl, identity=name)
        if checked != "PASS" or not sample:
            continue
        accepted.append(name)
    return tuple(accepted)


def build_observation(input_doc: dict, *, now: int, monotonic: int, ttl: int):
    policy = load_policy()
    main = input_doc.get("main", {})
    active = main.get("transport", "unconfigured")
    if active not in ("mihomo", "awg", "unconfigured"):
        raise ValueError("unknown active transport")
    node = main.get("node", "")
    proof = input_doc.get("service", {})
    mihomo_status, mid = checked_status(proof.get("mihomo"),
                                        now=now, transport="mihomo", ttl=ttl,
                                        identity=node if active == "mihomo" else "")
    awg_status, aid = checked_status(proof.get("awg"),
                                     now=now, transport="awg", ttl=ttl,
                                     identity="awg0")
    standby_state = input_doc.get("standby")
    standby = standby_ready(standby_state, now=now, ttl=ttl,
                            provider_sha=input_doc.get("provider_sha256", ""))
    if active == "awg":
        # The production Mihomo service is stopped while AWG serves users.
        # Independent Hot Standby evidence (NOT an old active-node sample)
        # therefore supplies the prospective Mihomo health for failback.
        mihomo_status, mid = "UNKNOWN", ""
        if standby:
            prospective = standby_state["entries"][standby[0]]
            mihomo_status, mid = checked_status(
                prospective, now=now, transport="mihomo", ttl=ttl,
                identity=standby[0])
    modes = input_doc.get("selection", {})
    node_policy = input_doc.get("node_policy", {})
    order = tuple(modes.get("priority", ["mihomo", "awg"]))
    config = policy.Policy(priority=order,
                           auto_failback=modes.get("auto_failback", False))
    obs = policy.Observation(
        now=monotonic, active_transport=active, active_node=node,
        selection_mode=modes.get("mode", "manual"),
        node_policy=node_policy.get("mode", "manual"),
        mihomo_status=mihomo_status, awg_status=awg_status,
        mihomo_sample=mid, awg_sample=aid, warm_nodes=standby,
        allowed_nodes=tuple(node_policy.get("allowed", [])))
    return obs, config


def evaluate_document(input_doc: dict, previous: dict | None = None, *,
                      now: int | None = None, mono: int | None = None,
                      ttl: int = DEFAULT_TTL) -> tuple[dict, dict]:
    if not isinstance(input_doc, dict):
        raise ValueError("invalid document")
    now = int(time.time()) if now is None else now
    mono = int(time.monotonic()) if mono is None else mono
    module = load_policy()
    obs, settings = build_observation(input_doc, now=now, monotonic=mono, ttl=ttl)
    mem = module.Memory(**(previous or {}))
    decision, updated = module.evaluate(obs, mem, settings)
    output = {"mode": "DRY_RUN_ONLY",
              "action": decision.action, "target": decision.target,
              "status": decision.status, "reason": decision.reason,
              "mihomo_service": obs.mihomo_status,
              "awg_service": obs.awg_status,
              "warm_count": len(obs.warm_nodes),
              "recovery_confirmed": decision.confirmed_failure,
              "detection_seconds": updated.last_detection_seconds,
              "time_to_recover_measured": False}
    return output, asdict(updated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True,
                        help="JSON fixture containing independent service evidence")
    parser.add_argument("--memory", help="Optional prior decision counters JSON")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    args = parser.parse_args()
    if not 15 <= args.ttl <= 600:
        parser.error("TTL must be 15..600s")
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    previous = (json.loads(Path(args.memory).read_text(encoding="utf-8"))
                if args.memory else {})
    result, updated = evaluate_document(snapshot, previous, ttl=args.ttl)
    print(json.dumps({"decision": result, "next_memory": updated}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError) as err:
        print("OBSERVER_ERROR=" + type(err).__name__, file=sys.stderr)
        raise SystemExit(2)
