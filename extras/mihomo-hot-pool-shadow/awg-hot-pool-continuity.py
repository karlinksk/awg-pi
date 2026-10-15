#!/usr/bin/env python3
"""Shadow-only, secret-safe retained Hot Pool provider union (experimental).

Prepares a merged candidate pool from qualified archived profiles, the live
provider, and scanned staged candidates. Does not modify production config.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import time
import yaml

NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
PROTOCOLS = {"ss", "vless", "trojan", "hysteria2", "vmess"}
MAX_ARCHIVED = 16
MAX_EACH_SOURCE = 192  # bounded pool of network-healthy profiles in RAM
MAX_PENDING = 24       # persistent candidate queue remains small
MAX_ARCHIVE_AGE = 86400
MAX_POOL_AGE = 7200
MAX_PROOF_AGE = 3600


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(profile):
    """Cryptographically bind full transport credentials, ignoring display name."""
    obj = {k: v for k, v in profile.items() if k != "name"}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def identity(name, protocol, server, port):
    return hashlib.sha256(json.dumps([name, protocol, server, port],
                         ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def valid_profile(item):
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        return False
    if not NAME.fullmatch(item["name"]) or item.get("type") not in PROTOCOLS:
        return False
    try:
        ip = ipaddress.ip_address(item.get("server"))
        return ip.version == 4 and ip.is_global and type(item.get("port")) is int and 0 < item["port"] < 65536
    except (TypeError, ValueError):
        return False


def profiles(path):
    obj = yaml.safe_load(Path(path).read_text())
    if not isinstance(obj, dict) or not isinstance(obj.get("proxies"), list):
        raise ValueError("INVALID_PROVIDER")
    return [p for p in obj["proxies"] if valid_profile(p)]


def scan_health(path, provider, now):
    if path is None or provider is None or not Path(path).is_file():
        return []
    try:
        obj = json.loads(Path(path).read_text())
        if (obj.get("provider_sha256") != sha(provider)
                or not 0 <= now - obj.get("scanned_at", -1) <= MAX_POOL_AGE):
            return []
        return [r for r in obj.get("nodes", []) if isinstance(r, dict)
                and r.get("healthy") and isinstance(r.get("delay_ms"), int)
                and 0 < r["delay_ms"] <= 120000]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def health_matches(items, health):
    by_key = {(p["name"], p["type"], p["server"], p["port"]): p for p in items}
    chosen = []
    for row in sorted(health, key=lambda n: n["delay_ms"]):
        key = tuple(row.get(k) for k in ("name", "type", "server", "port"))
        if key in by_key and by_key[key] not in chosen:
            chosen.append((by_key[key], row["delay_ms"]))
        if len(chosen) >= MAX_EACH_SOURCE:
            break
    return chosen


def usable_proof(proof, now):
    stamps = proof.get("passes", []) if isinstance(proof, dict) else []
    return (proof.get("last_result") == "PASS" and len(stamps) >= 2
            and all(type(t) is int and 0 <= now - t <= MAX_PROOF_AGE for t in stamps[-2:])
            and stamps[-1] - stamps[-2] >= 600)


def snapshot_vault(current, state, vault, now):
    """Archive only profiles with two fresh service PASSes from matching provider."""
    entries = {fingerprint(r["profile"]): r for r in vault.get("entries", [])
               if isinstance(r, dict) and valid_profile(r.get("profile"))
               and type(r.get("saved_at")) is int
               and 0 <= now - r["saved_at"] <= MAX_ARCHIVE_AGE}
    if state.get("provider_sha256") == sha(current):
        checks = state.get("checks", {})
        for p in profiles(current):
            key = identity(p["name"], p["type"], p["server"], p["port"])
            if usable_proof(checks.get(key, {}), now):
                sig = fingerprint(p)
                old = entries.get(sig)
                if old is None or now - old["saved_at"] >= 21600:
                    entries[sig] = {"profile": p, "saved_at": now,
                                    "fingerprint": sig, "last_delay_ms": 4000}
    return {"version": 1, "entries": sorted(entries.values(),
                        key=lambda x: -x["saved_at"])[:MAX_ARCHIVED]}


def build_union(vault, live_profiles, live_health, candidate_profiles,
                candidate_health, current_name=""):
    """Retain exact-profile proofs; never classify active node as its own reserve."""
    source = []
    active = [p for p in live_profiles if p["name"] == current_name]
    if len(active) == 1:
        source.append((active[0], 4000, "active"))
    for row in vault.get("entries", []):
        p = row["profile"]
        if valid_profile(p):
            source.append((p, row.get("last_delay_ms", 4000), "archive"))
    for entry in vault.get("pending", []):
        if valid_profile(entry.get("profile")):
            source.append((entry["profile"], entry.get("delay_ms", 4000), "pending"))
    source.extend((p, delay, "live") for p, delay in
                  health_matches(live_profiles, live_health))
    source.extend((p, delay, "candidate") for p, delay in
                  health_matches(candidate_profiles, candidate_health))
    used_names = set()
    seen_sigs = set()
    nodes = []
    output = []
    for p, delay, origin in source:
        sig = fingerprint(p)
        if sig in seen_sigs:
            continue
        alias = p["name"]
        if alias in used_names:
            alias = "hot-" + sig[:20]
        if alias in used_names:
            continue
        used_names.add(alias)
        seen_sigs.add(sig)
        item = dict(p)
        item["name"] = alias
        output.append(item)
        nodes.append({"name": alias, "type": item["type"], "server": item["server"],
                      "port": item["port"], "delay_ms": delay,
                      "healthy": True, "index": len(nodes), "origin": origin})
    return output, nodes


def retain_pending(vault, candidate_profiles, candidate_health, union,
                   now):
    """Save bounded new candidates for later qualification after staging TTL.

    Only a candidate with a recent successful transport-health scan may enter
    this protected queue. It does NOT inherit READY or trigger live switching.
    """
    ready_sigs = {fingerprint(r["profile"]) for r in vault.get("entries", [])}
    pending = {}
    for item in vault.get("pending", []):
        if (isinstance(item, dict)
                and valid_profile(item.get("profile"))
                and type(item.get("saved_at")) is int
                and 0 <= now - item["saved_at"] <= MAX_ARCHIVE_AGE):
            signature = fingerprint(item["profile"])
            if signature not in ready_sigs:
                pending[signature] = item
    aliases = {fingerprint(item): item["name"] for item in union}
    for p, delay in health_matches(candidate_profiles, candidate_health):
        sig = fingerprint(p)
        if sig in ready_sigs or sig in pending or sig not in aliases:
            continue
        renamed = dict(p, name=aliases[sig])
        pending[sig] = {"profile": renamed, "saved_at": now,
                        "delay_ms": delay}
    vault["pending"] = sorted(pending.values(), key=lambda x: -x["saved_at"])[:MAX_PENDING]
    return vault


def rebind_state(state, old_provider_digest, old_profiles, previous_vault,
                 new_profiles, new_digest, now):
    """Keep proofs ONLY where old and new complete transport profiles match.

    The old provider digest is trusted only if it exactly matches the current
    shadow-state digest. Subsequent unions use the private vault fingerprint map.
    Never infer identity from node name, endpoint or latency alone.
    """
    old_digest = state.get("provider_sha256")
    if old_digest == old_provider_digest:
        previous = {identity(p["name"], p["type"], p["server"], p["port"]):
                    fingerprint(p) for p in old_profiles}
    elif old_digest == previous_vault.get("last_union_digest"):
        # Legacy compatibility only; current runs trust actual previous bytes.
        previous = previous_vault.get("bindings", {})
    else:
        previous = {}
    new_bindings = {identity(p["name"], p["type"], p["server"], p["port"]):
                    fingerprint(p) for p in new_profiles}
    raw_checks = state.get("checks", {})
    if not isinstance(raw_checks, dict):
        raw_checks = {}
    fresh = {}
    for key, old in raw_checks.items():
        if (previous.get(key) == new_bindings.get(key)
                and isinstance(old, dict)
                and type(old.get("last_checked")) is int
                and 0 <= now - old["last_checked"] <= MAX_PROOF_AGE):
            fresh[key] = old
    updated = dict(state)
    updated.update({"version": 1, "provider_sha256": new_digest,
                    "checks": fresh})
    return updated, new_bindings


def atomic_private(path, contents):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("UNSAFE_DIRECTORY")
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".continuity-", delete=False) as f:
        temp = Path(f.name)
        os.fchmod(f.fileno(), 0o600)
        f.write(contents)
    os.replace(temp, path)


def run(args):
    now = args.now or int(time.time())
    state = json.loads(Path(args.state).read_text()) if args.state.exists() else {}
    previous_vault = json.loads(args.vault.read_text()) if args.vault.exists() else {}
    vault = dict(previous_vault)
    if vault and vault.get("version") != 1:
        raise ValueError("UNSUPPORTED_VAULT_VERSION")
    current = profiles(args.live_provider)
    live_health = scan_health(args.live_pool, args.live_provider, now)
    candidate = profiles(args.candidate_provider) if args.candidate_provider and args.candidate_provider.is_file() else []
    cand_health = scan_health(args.candidate_pool, args.candidate_provider, now)
    # Carry newly qualified shadow candidates into the protected archive.
    # Trust the previous union only when BOTH its vault digest and the state
    # digest match the actual profile bytes; otherwise use the live provider.
    previous_source = args.live_provider
    if args.output_provider.exists():
        last_digest = sha(args.output_provider)
        if state.get("provider_sha256") == last_digest:
            previous_source = args.output_provider
    previous_profiles = profiles(previous_source)
    vault = snapshot_vault(previous_source, state, vault, now)
    vault["pending"] = previous_vault.get("pending", [])
    vault["pending"] = [p for p in vault["pending"]
                        if isinstance(p, dict) and valid_profile(p.get("profile"))
                        and type(p.get("saved_at")) is int
                        and 0 <= now - p["saved_at"] <= MAX_ARCHIVE_AGE]
    current_name = ""
    if args.current_file is not None:
        try:
            current_name = args.current_file.read_text().strip()
        except OSError:
            pass
    union, nodes = build_union(vault, current, live_health,
                              candidate, cand_health, current_name)
    vault = retain_pending(vault, candidate, cand_health, union, now)
    if not nodes:
        raise ValueError("NO_ELIGIBLE_PROFILES")
    # Output files are always protected, including credentials in provider.
    yaml_text = yaml.safe_dump({"proxies": union}, sort_keys=False, allow_unicode=True)
    digest = hashlib.sha256(yaml_text.encode()).hexdigest()
    updated_state, _bindings = rebind_state(
        state, sha(previous_source), previous_profiles, previous_vault,
        union, digest, now)
    payload = {"provider_sha256": digest, "scanned_at": now,
               "geo_enriched": False, "nodes": nodes}
    # Credentials are persisted only when profiles are added or refreshed.
    # The full binding map is derived from RAM union files each cycle.
    atomic_private(args.output_provider, yaml_text)
    atomic_private(args.output_pool, json.dumps(payload, separators=(",", ":")) + "\n")
    # The original state is kept in RAM; no microSD write per probe.
    atomic_private(args.output_state, json.dumps(updated_state,
                                                separators=(",", ":")) + "\n")
    new_vault = json.dumps(vault, ensure_ascii=False, separators=(",", ":")) + "\n"
    if not args.vault.exists() or args.vault.read_text() != new_vault:
        atomic_private(args.vault, new_vault)
    print("CONTINUITY_SHADOW_ONLY=YES")
    print("CONTINUITY_ARCHIVED=" + str(len(vault["entries"])))
    print("CONTINUITY_CANDIDATES=" + str(sum(n["origin"] == "candidate" for n in nodes)))
    print("CONTINUITY_UNION_PROFILES=" + str(len(nodes)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live-provider", type=Path, required=True)
    p.add_argument("--current-file", type=Path)
    p.add_argument("--live-pool", type=Path, required=True)
    p.add_argument("--candidate-provider", type=Path)
    p.add_argument("--candidate-pool", type=Path)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--vault", type=Path, required=True)
    p.add_argument("--output-provider", type=Path, required=True)
    p.add_argument("--output-pool", type=Path, required=True)
    p.add_argument("--output-state", type=Path, required=True,
                   help="Isolated shadow state, never the live Hot Pool state")
    p.add_argument("--now", type=int, default=0)
    args = p.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, json.JSONDecodeError) as e:
        # Never print raw exceptions, provider contents or paths.
        print("CONTINUITY_SHADOW_ERROR=" + type(e).__name__)
        raise SystemExit(2)


if __name__ == "__main__":
    main()