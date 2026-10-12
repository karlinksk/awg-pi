#!/usr/bin/env python3
"""Router-agnostic, event-driven underlay policy (STAGING / SHADOW ONLY).

Collects local Pi routing snapshots without network packets or MikroTik SSH.
Decides whether a specific proposed switch needs ONE fresh router audit.
Does NOT authorize or perform a production route/transport/node change.

Cached JSON is telemetry, NOT a cryptographically trusted switch permit.
A future single-owner selector must independently revalidate when committing.
"""
from __future__ import annotations

import argparse
import fcntl
from dataclasses import dataclass, asdict
import hashlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Callable

DEFAULT_STATE = Path("/run/awg-pbr/router-events/state.json")
PROVENANCE_FILE = Path(__file__).with_name("awg-endpoint-provenance.py")
EVENT_KEYS = ("boot", "lan", "main_route", "ip_rules", "link_addr", "provider")
MODES = ("event_driven", "strict", "unmanaged")
MAX_LOCAL_BYTES = 65536
MAX_PROOF_AGE = 30


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    audit_needed: bool = False
    router_verified: bool = False
    advisory_only: bool = True


def provenance():
    loader = importlib.machinery.SourceFileLoader("awg_router_event_provenance",
                                                 str(PROVENANCE_FILE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_snapshot(state: object) -> bool:
    if not isinstance(state, dict) or state.get("version") != 1:
        return False
    keys = state.get("parts")
    return (isinstance(keys, dict) and
            all(isinstance(keys.get(k), str) and
                re.fullmatch("[0-9a-f]{64}", keys[k]) for k in EVENT_KEYS))


def build_snapshot(*, boot: str, interface: str, router: str, pi_ip: str,
                   main_routes: str, ip_rules: str, addresses: str,
                   provider_sha: str = "") -> dict:
    """Hash only *routing-relevant* information, never credentials."""
    if (not boot or not interface or not router or not pi_ip
            or len(main_routes) > MAX_LOCAL_BYTES
            or len(ip_rules) > MAX_LOCAL_BYTES
            or len(addresses) > MAX_LOCAL_BYTES):
        raise ValueError("invalid local router snapshot")
    ipaddress.IPv4Address(router)
    ipaddress.IPv4Address(pi_ip)
    if not re.fullmatch("[a-zA-Z][a-zA-Z0-9_.-]{0,14}", interface):
        raise ValueError("invalid LAN interface")
    if provider_sha and not re.fullmatch("[0-9a-f]{64}", provider_sha):
        raise ValueError("invalid provider fingerprint")
    parts = {
        "boot": digest(boot),
        "lan": digest("|".join((interface, router, pi_ip))),
        "main_route": digest(main_routes),
        "ip_rules": digest(ip_rules),
        "link_addr": digest(addresses),
        "provider": digest(provider_sha),
    }
    return {"version": 1, "parts": parts, "fingerprint": digest(
        json.dumps(parts, sort_keys=True, separators=(",", ":"))),
        "checked_at": int(time.time())}


def detect_events(old: dict | None, new: dict) -> tuple[str, ...]:
    if not validate_snapshot(new):
        raise ValueError("invalid current snapshot")
    if not validate_snapshot(old):
        return ("INIT_OR_UNKNOWN",)
    return tuple(key.upper() + "_CHANGED" for key in EVENT_KEYS
                 if old["parts"][key] != new["parts"][key])


def invalidate_endpoint_proofs(events: tuple[str, ...]) -> bool:
    return bool(events)


def advance_generation(previous: dict | None, current: dict, *,
                       now: int | None = None) -> tuple[dict, tuple[str, ...]]:
    """Change the router-policy epoch on any relevant local network event.

    The epoch is only a cache-invalidation marker, NOT a signed route permit.
    """
    events = detect_events(previous, current)
    old_epoch = (previous.get("generation", 0)
                 if validate_snapshot(previous) and
                 isinstance(previous.get("generation", 0), int) and
                 not isinstance(previous.get("generation", 0), bool) else 0)
    if old_epoch < 0 or old_epoch >= 2**63-1:
        old_epoch = 0
        events = ("INIT_OR_UNKNOWN",)
    next_state = dict(current)
    next_state["generation"] = old_epoch + int(bool(events))
    next_state["invalidated_at"] = (
        int(time.time()) if now is None else now) if events else previous.get(
            "invalidated_at", 0)
    return next_state, events


def safe_runner(command: list[str], *, runner=subprocess.run) -> str:
    """Only local /usr/sbin/ip reads; neither SSH nor ip route changes."""
    if not command or command[:1] != ["/usr/sbin/ip"]:
        raise ValueError("command not allowlisted")
    permitted = (
        ["/usr/sbin/ip", "-4", "route", "show", "table", "main"],
        ["/usr/sbin/ip", "-4", "rule", "show"],
    )
    if command not in permitted and not (
        len(command) == 7 and command[:6] ==
        ["/usr/sbin/ip", "-4", "-o", "addr", "show", "dev"] and
        re.fullmatch("[a-zA-Z][a-zA-Z0-9_.-]{0,14}", command[6])):
        raise ValueError("local route command not allowlisted")
    completed = runner(command, capture_output=True, text=True,
                       timeout=2, check=False)
    if completed.returncode != 0 or len(completed.stdout) > MAX_LOCAL_BYTES:
        raise ValueError("local route snapshot unavailable")
    return completed.stdout


def read_local_snapshot(*, provider_sha: str = "", runner=subprocess.run,
                        env_path: Path = Path("/etc/awg-pbr/env"),
                        boot_path: Path = Path("/proc/sys/kernel/random/boot_id")) -> dict:
    route_module = provenance()
    interface, router = route_module.configured_lan(env_path)
    addr = safe_runner(
        ["/usr/sbin/ip", "-4", "-o", "addr", "show", "dev", interface], runner=runner)
    seen = re.findall(r"\binet\s+((?:\d{1,3}\.){3}\d{1,3})/\d+", addr)
    # Multiple or no addresses require an operator decision; no guessing.
    if len(seen) != 1:
        raise ValueError("ambiguous LAN address")
    pi_ip = str(ipaddress.IPv4Address(seen[0]))
    main = safe_runner(["/usr/sbin/ip", "-4", "route", "show",
                        "table", "main"], runner=runner)
    rules = safe_runner(["/usr/sbin/ip", "-4", "rule", "show"], runner=runner)
    boot = boot_path.read_text(encoding="utf-8").strip()
    return build_snapshot(boot=boot, interface=interface, router=router,
                          pi_ip=pi_ip, main_routes=main,
                          ip_rules=rules, addresses=addr,
                          provider_sha=provider_sha)


def exact_binding(endpoint: dict, source_ip: str, router_ip: str) -> str:
    try:
        ip = str(ipaddress.IPv4Address(endpoint["ip"]))
        local = ipaddress.IPv4Address(source_ip)
        gateway = ipaddress.IPv4Address(router_ip)
        if (not ipaddress.IPv4Address(ip).is_global or not local.is_private
                or not gateway.is_private):
            raise ValueError("unexpected router or source")
        port, protocol = endpoint["port"], endpoint["protocol"]
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("invalid endpoint port")
        if protocol not in ("tcp", "udp"):
            raise ValueError("invalid endpoint transport protocol")
        return digest(f"{ip}|{port}|{protocol}|{source_ip}|{router_ip}")
    except (KeyError, TypeError, ValueError):
        return ""


def currently_verified(proof: object, endpoint: dict, source_ip: str,
                       router_ip: str, *, now: int,
                       in_process: bool, changed: bool) -> bool:
    # A persisted/unsigned JSON "router_verified" is never sufficient.
    if changed or not in_process or not isinstance(proof, dict):
        return False
    checked = proof.get("checked_at")
    ttl = proof.get("valid_for_seconds")
    return (proof.get("mode") == "DIRECT" and
            proof.get("scope") == "END_TO_END" and
            proof.get("router_verified") is True and
            proof.get("reason") == "router_underlay_verified" and
            isinstance(checked, int) and not isinstance(checked, bool) and
            isinstance(ttl, int) and not isinstance(ttl, bool) and
            0 <= now - checked <= min(ttl, MAX_PROOF_AGE) and
            proof.get("endpoint_binding_sha256") ==
            exact_binding(endpoint, source_ip, router_ip) != "")


def plan(*, policy: str, requested_switch: bool, adapter_available: bool,
         evidence: object = None, endpoint: dict | None = None,
         source_ip: str = "", router_ip: str = "",
         events: tuple[str, ...] = (), now: int | None = None,
         in_process: bool = False, admin_trust: bool = False) -> Decision:
    """No side effects. Even DIRECT proof is *advisory*, not switch authority."""
    if policy not in MODES:
        return Decision("BLOCKED", "invalid_router_policy")
    if not requested_switch:
        return Decision("IDLE", "no_router_query_at_idle")
    if policy == "unmanaged":
        if admin_trust:
            return Decision("UNVERIFIED", "admin_trusted_local_only")
        return Decision("BLOCKED", "generic_router_requires_explicit_trust")
    if endpoint is None or not exact_binding(endpoint, source_ip, router_ip):
        return Decision("BLOCKED", "actual_endpoint_unknown")
    if policy == "event_driven" and currently_verified(
            evidence, endpoint, source_ip, router_ip, now=int(time.time()) if now is None else now,
            in_process=in_process, changed=invalidate_endpoint_proofs(events)):
        return Decision("READY_TO_PREFLIGHT", "fresh_in_process_router_proof",
                        router_verified=True)
    if not adapter_available:
        return Decision("BLOCKED", "router_adapter_unavailable")
    return Decision("AUDIT_ON_DEMAND", "exact_endpoint_route_recheck_required",
                    audit_needed=True)


def on_demand(*, policy: str, endpoint: dict, source_ip: str, router_ip: str,
              interface: str, verifier: Callable | None,
              events: tuple[str, ...] = (),
              now: int | None = None, admin_trust: bool = False) -> Decision:
    """One opt-in in-process attestation, never a traffic-switch command."""
    intention = plan(policy=policy, requested_switch=True,
                     adapter_available=verifier is not None,
                     endpoint=endpoint, source_ip=source_ip,
                     router_ip=router_ip, events=events,
                     now=now, admin_trust=admin_trust)
    if not intention.audit_needed:
        return intention
    try:
        result = verifier(endpoint["ip"], endpoint["port"], endpoint["protocol"],
                          source_ip, interface, router_ip)
        if currently_verified(result, endpoint, source_ip, router_ip,
                              now=int(time.time()) if now is None else now,
                              in_process=True, changed=False):
            return Decision("READY_TO_PREFLIGHT", "fresh_router_audit_passed",
                            router_verified=True)
    except (OSError, RuntimeError, ValueError, TimeoutError,
            subprocess.TimeoutExpired):
        pass
    return Decision("BLOCKED", "router_route_not_verified")


def read_state(path: Path) -> dict | None:
    try:
        if path.stat().st_size > 4096:
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if validate_snapshot(record):
            return record
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_state(path: Path, record: dict) -> None:
    # State is *telemetry* only; it cannot authorize a switch.
    if not (path.is_relative_to(DEFAULT_STATE.parent)
            and path.resolve().is_relative_to(DEFAULT_STATE.parent.resolve())):
        raise ValueError("router event state must remain in RAM")
    if not validate_snapshot(record):
        raise ValueError("invalid state")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".route-event-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(record, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def observe_once(*, path: Path = DEFAULT_STATE,
                 sampler=read_local_snapshot,
                 provider_sha: str = "") -> tuple[dict, tuple[str, ...]]:
    """Serialize concurrent systemd.path and local-netlink event handlers."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.parent / ".observer.lock"
    # OS kernel lock (RAM-backed, not the transport maintenance lock).
    with lock.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        previous = read_state(path)
        current = sampler(provider_sha=provider_sha)
        state, events = advance_generation(previous, current)
        if events:
            write_state(path, state)
        return state, events


def handle_netlink_events(lines, *, callback, sleeper=time.sleep,
                          clock=time.monotonic, debounce: float = 2.0) -> int:
    """Event-driven local scans: no periodic SSH or timeout polling."""
    completed = 0
    last_processed = None
    for line in lines:
        if not isinstance(line, str) or not line.strip():
            continue
        point = clock()
        if last_processed is not None and point - last_processed < debounce:
            sleeper(debounce - (point - last_processed))
        try:
            callback()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            # An unavailable local route must NEVER authorize a router path.
            pass
        last_processed = clock()
        completed += 1
    return completed


def watch_local_netlink() -> int:
    """Never opens RouterOS/SSH. Reacts only to Linux netlink route events."""
    process = subprocess.Popen(
        ["/usr/sbin/ip", "-4", "monitor", "route", "rule", "address", "link"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        if process.stdout is None:
            raise OSError("no netlink monitor output")
        handle_netlink_events(process.stdout, callback=observe_once)
        return 0 if process.wait(timeout=2) == 0 else 1
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("observe", "status", "watch"))
    parser.add_argument("--provider-sha", default="")
    args = parser.parse_args()
    if args.command == "status":
        previous = read_state(DEFAULT_STATE)
        print(json.dumps({"mode": "SHADOW_ONLY",
                          "cached": previous is not None,
                          "router_ssh_calls": 0,
                          "router_verification_mode": "event_driven"},
                         sort_keys=True))
        return 0
    if args.command == "watch":
        return watch_local_netlink()
    try:
        state, changes = observe_once(provider_sha=args.provider_sha)
        print(json.dumps({"mode": "SHADOW_ONLY",
                          "router_ssh_calls": 0,
                          "policy_generation": state["generation"],
                          "policy_baseline_audit_due": bool(changes),
                          "invalidate_endpoint_proofs": bool(changes),
                          "events": changes}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({"mode": "SHADOW_ONLY", "router_ssh_calls": 0,
                          "events": ["LOCAL_AUDIT_UNAVAILABLE"],
                          "invalidate_endpoint_proofs": True,
                          "policy_baseline_audit_due": True}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
