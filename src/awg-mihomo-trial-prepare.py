#!/usr/bin/env python3
"""Prepare ONE small systemd credential from protected provider, no networking.

Operator-launched as root in a supervised single-run installer, never a daemon.
Reads existing root-only provider and live pool, proves source fingerprint and
policy, selects at most three distinct candidates, atomically writes ONLY the
chosen proxy configuration to a private /run tmpfs directory. This credential
is delivered via LoadCredential to a DynamicUser nonroot service.

Do NOT print raw provider content, endpoints, keys or provider URLs.
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

ROOT = Path(__file__).resolve().parent
POOL = Path("/run/awg-pbr/mihomo-pool/live.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
OUT = Path("/run/awg-pbr/stage13-selection/selection.json")
LIMIT = 3
MAX_SIZE = 480_000
MIN_AGE_SECONDS = 0
MAX_AGE_SECONDS = 300


def load(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


def prepare_payload(pool: dict, raw: list[dict], *,
                    region: str, protocol: str, now: int,
                    boot: str, generation: int | None,
                    select_candidates) -> dict:
    if not isinstance(pool, dict) or not isinstance(raw, list):
        raise ValueError("bad protected pool")
    if region == "europe" and pool.get("geo_enriched") is not True:
        raise ValueError("Europe is not independently geo-enriched")
    selected = select_candidates(pool, raw, region=region,
                                 protocol=protocol, limit=LIMIT)
    if not selected:
        raise ValueError("no appropriate candidate")
    selected_names = {n["name"] for n in selected}
    matches = [n for n in raw if isinstance(n, dict)
               and n.get("name") in selected_names]
    if len(matches) != len(selected):
        raise ValueError("mismatched protected provider")
    provider_sha = pool.get("provider_sha256")
    if not isinstance(provider_sha, str) or len(provider_sha) != 64:
        raise ValueError("bad source hash")
    if not isinstance(boot, str) or not boot or len(boot) > 128:
        raise ValueError("boot identity unavailable")
    return {
        "version": 1,
        "prepared_at": now,
        "boot_id": boot,
        "route_generation": generation,
        "provider_sha256": provider_sha,
        "candidates": selected,
        "proxies": matches,
        "service_ready": False,
        "routing_verified": False,
        "mode": "SHADOW_ONLY",
    }


def atomic_selection(payload: dict, target: Path = OUT) -> int:
    # Never write to removable flash or allow the unprivileged user to replace
    # the root-produced credential before systemd reads it.
    if not str(target).startswith("/run/awg-pbr/stage13-selection/"):
        raise ValueError("selection must stay in RAM")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not 1 <= len(data) <= MAX_SIZE:
        raise ValueError("selected credential too large")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.exists() and target.is_symlink():
        raise ValueError("unsafe selection file path")
    os.chmod(target.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix=".selection-", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.write(b"\n")
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return len(data) + 1


def run(target: Path = OUT) -> dict:
    if os.geteuid() != 0:
        raise PermissionError("only the operator's privileged preparer may access provider")
    trial = load("stage13_prepare_selection", "awg-mihomo-service-trial.py")
    pool_helper = load("stage13_prepare_pool", "awg-mihomo-pool.py")
    smart = load("stage13_prepare_smart", "awg-mihomo-smart")
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not smart.fresh_pool(pool, PROVIDER, 3600):
        raise ValueError("protected pool/provider mismatch or stale scan")
    raw = pool_helper.read_provider(PROVIDER)
    region, protocol = pool_helper.read_policy_values()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    payload = prepare_payload(
        pool, raw, region=region, protocol=protocol,
        now=int(time.time()), boot=boot,
        generation=trial.load("stage13_prepare_standby",
                              "awg-mihomo-standby.py").current_generation(),
        select_candidates=trial.select)
    size = atomic_selection(payload, target=target)
    return {"mode":"SHADOW_ONLY", "status":"PREPARED",
            "candidate_count":len(payload["candidates"]),
            "credential_bytes":size,"production_modified":False}


def main() -> int:
    try:
        output = run()
        print(json.dumps(output, separators=(",", ":")))
        return 0
    except (OSError, ValueError, PermissionError, TypeError, KeyError,
            RuntimeError, SystemExit):
        print(json.dumps({"mode":"SHADOW_ONLY","status":"PREPARE_FAILED",
                          "production_modified":False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
