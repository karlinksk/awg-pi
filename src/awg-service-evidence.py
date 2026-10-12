#!/usr/bin/env python3
"""Publish read-only, conservatively attributed service evidence to RAM.

Never switches or restarts a transport. The legacy selection monitor's
optional advisory observer may consume the resulting snapshot but is never
allowed to execute the proposed action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
AWG_PROBE = ROOT / "awg-service-probe.py"
MIHOMO_PROBE = ROOT / "awg-mihomo-service-check.py"
OUTPUT = Path("/run/awg-pbr/service-evidence/snapshot.json")
SELECTION = Path("/etc/awg-pbr/selection.env")
ACTIVE_TRANSPORT = Path("/etc/awg-pbr/transport")
ACTIVE_NODE = Path("/etc/awg-pbr/transports/mihomo/node-name")
NODE_POLICY = Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
FIXED_NODES = Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
STANDBY = Path("/run/awg-pbr/mihomo-standby/state.json")
POOL = Path("/run/awg-pbr/mihomo-pool/live.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
DEFAULT_PORT = 7890
CHECK_NAMES = ("openai_api", "chatgpt_web", "youtube_video")


def read_text(path: Path, max_bytes: int = 8192) -> str:
    if path.stat().st_size > max_bytes:
        raise ValueError("source file too large")
    return path.read_text(encoding="utf-8").strip()


def atomic_json(path: Path, payload: dict) -> None:
    if not str(path).startswith("/run/awg-pbr/service-evidence/"):
        raise ValueError("evidence must remain in its designated RAM directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".service-evidence-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def parse_policy_env(contents: str) -> dict:
    """Only explicit, simple, safe configuration keys are accepted."""
    result = {"mode": "manual", "priority": ["mihomo", "awg"],
              "auto_failback": False}
    pairs = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z_]+)=([A-Za-z0-9_,'\" -]*)", line)
        if not match:
            return result
        pairs[match.group(1)] = match.group(2).strip("'\"")
    mode = pairs.get("SELECTION_MODE", "manual")
    if mode not in ("auto", "manual", "fixed"):
        return result
    result["mode"] = mode
    primary = pairs.get("SELECTION_PRIMARY", "").strip()
    order = [n.strip() for n in pairs.get("SELECTION_ORDER", "").split(",") if n.strip()]
    if primary and primary not in order:
        order = [primary] + order
    if len(order) == 2 and set(order) == {"mihomo", "awg"}:
        result["priority"] = order
    # This new setting is opt-in and not yet managed by the old selection CLI.
    result["auto_failback"] = pairs.get("SELECTION_AUTO_FAILBACK") == "1"
    return result


def conservative_unknown(transport: str, identity: str, reason: str) -> dict:
    return {"transport": transport, "identity": identity,
            "checked_at": int(time.time()), "sample_id": uuid.uuid4().hex,
            "status": "UNKNOWN",
            "checks": {n: {"state": "UNKNOWN", "reason": reason} for n in CHECK_NAMES}}


def sanitize_probe(raw: object, transport: str, identity: str) -> dict:
    if not isinstance(raw, dict) or raw.get("transport") != transport:
        return conservative_unknown(transport, identity, "invalid_transport_evidence")
    if raw.get("identity") != identity:
        return conservative_unknown(transport, identity, "incorrect_node_identity")
    checks = raw.get("checks")
    if not isinstance(checks, dict):
        return conservative_unknown(transport, identity, "no_service_evidence")
    clean = {}
    for name in CHECK_NAMES:
        data = checks.get(name)
        if not isinstance(data, dict) or data.get("state") not in ("PASS", "FAIL", "UNKNOWN"):
            return conservative_unknown(transport, identity, "malformed_service_evidence")
        reason = data.get("reason")
        if not isinstance(reason, str) or not re.fullmatch(r"[a-zA-Z0-9_\-]{1,90}", reason):
            reason = "unspecified"
        clean[name] = {"state": data["state"], "reason": reason}
    states = [clean[key]["state"] for key in CHECK_NAMES]
    status = ("PASS" if all(s == "PASS" for s in states) else
              "FAIL" if "FAIL" in states else "UNKNOWN")
    claimed = raw.get("status")
    if claimed != status:
        return conservative_unknown(transport, identity, "inconsistent_status_evidence")
    sample = raw.get("sample_id")
    if not isinstance(sample, str) or not re.fullmatch(r"[A-Za-z0-9_:\-.]{1,96}", sample):
        return conservative_unknown(transport, identity, "invalid_sample_id")
    # Do not accept old results even if produced by an authentic local module.
    checked = raw.get("checked_at")
    now = int(time.time())
    if not isinstance(checked, int) or checked > now + 1 or now - checked > 120:
        return conservative_unknown(transport, identity, "stale_probe_evidence")
    return {"transport": transport, "identity": identity,
            "checked_at": checked, "sample_id": sample,
            "status": status, "checks": clean}


def run_probe(path: Path, params: list[str], *, transport: str, identity: str,
              duration: int = 26, runner=subprocess.run) -> dict:
    try:
        result = runner([sys.executable, str(path), *params], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, check=False, timeout=duration)
        if len(result.stdout) > 16_384:
            raise ValueError("oversized probe output")
        if result.returncode not in (0, 1):
            raise RuntimeError("probe_execution_failure")
        return sanitize_probe(json.loads(result.stdout), transport, identity)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return conservative_unknown(transport, identity, "probe_unavailable")


def read_standby(path: Path) -> dict:
    try:
        if path.stat().st_size > 524288:
            raise ValueError("standby cache too large")
        obj = json.loads(path.read_text("utf-8"))
        if isinstance(obj, dict) and obj.get("mode") == "SHADOW_ONLY":
            return obj
    except (OSError, ValueError, TypeError):
        pass
    return {}


def source_sha(pool_path: Path, provider_path: Path) -> str:
    """Refuse to forward standby confidence after a provider refresh."""
    try:
        if pool_path.stat().st_size > 2_500_000:
            return ""
        pool = json.loads(pool_path.read_text("utf-8"))
        expected = pool.get("provider_sha256")
        if not isinstance(expected, str) or not re.fullmatch("[a-f0-9]{64}", expected):
            return ""
        digest = hashlib.sha256()
        with provider_path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            return ""
        return expected
    except (OSError, ValueError, TypeError):
        return ""


def collect(*, now: int | None = None, runner=subprocess.run,
            config: dict | None = None) -> dict:
    """Read all policy inputs conservatively; no write except final snapshot."""
    now = int(time.time()) if now is None else now
    if config is None:
        try:
            selection = parse_policy_env(read_text(SELECTION))
        except (OSError, ValueError):
            selection = parse_policy_env("")
        try:
            active = read_text(ACTIVE_TRANSPORT)
        except (OSError, ValueError):
            active = "unconfigured"
        if active not in ("awg", "mihomo", "unconfigured"):
            active = "unconfigured"
        try:
            node = read_text(ACTIVE_NODE)
        except (OSError, ValueError):
            node = ""
        try:
            mode = read_text(NODE_POLICY)
        except (OSError, ValueError):
            mode = "manual"
        if mode not in ("manual", "auto", "fixed"):
            mode = "manual"
        try:
            allowed = [x for x in read_text(FIXED_NODES, 16384).splitlines() if x]
        except (OSError, ValueError):
            allowed = []
        provider_sha = source_sha(POOL, PROVIDER)
        standby = read_standby(STANDBY)
    else:
        selection = config["selection"]
        active, node = config["active"], config.get("node", "")
        mode = config.get("node_policy", "manual")
        allowed = config.get("allowed", [])
        provider_sha = config.get("provider_sha256", "")
        standby = config.get("standby", {})
    if active not in ("awg", "mihomo", "unconfigured"):
        active = "unconfigured"
    if not isinstance(node, str) or len(node) > 256:
        node = ""
    mihomo = conservative_unknown("mihomo", node, "mihomo_not_active")
    awg = conservative_unknown("awg", "awg0", "awg_not_configured")
    # Never query the stopped production Mihomo proxy while AWG is selected.
    if active == "mihomo" and node:
        mihomo = run_probe(
            MIHOMO_PROBE, ["--proxy-port", str(DEFAULT_PORT),
                          "--timeout", "3", "--identity", node],
            transport="mihomo", identity=node, runner=runner)
    # AWG may be up as standby independently of Mihomo and can be probed
    # without selecting it as active transport.
    if "awg0" in [name for _,name in socket.if_nameindex()]:
        awg = run_probe(AWG_PROBE, ["--interface", "awg0", "--timeout", "3"],
                        transport="awg", identity="awg0", runner=runner)
    # The reader independently confirms pool/source fingerprints and TTL.
    return {"version": 1, "generated_at": now,
            "main": {"transport": active, "node": node},
            "selection": selection,
            "node_policy": {"mode": mode, "allowed": allowed if mode == "fixed" else []},
            "provider_sha256": provider_sha,
            "standby": standby,
            "service": {"mihomo": mihomo, "awg": awg}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "show"))
    args = parser.parse_args()
    if args.command == "show":
        try:
            doc = json.loads(read_text(OUTPUT, 524288))
            data = {"active": doc.get("main", {}).get("transport"),
                    "mihomo": doc.get("service", {}).get("mihomo", {}).get("status"),
                    "awg": doc.get("service", {}).get("awg", {}).get("status"),
                    "checked_at": doc.get("generated_at")}
        except (OSError, ValueError, TypeError):
            data = {"status": "MISSING"}
        print(json.dumps(data, sort_keys=True))
        return 0
    if os.geteuid() != 0:
        raise SystemExit("collector requires root to read protected runtime state")
    document = collect()
    atomic_json(OUTPUT, document)
    # Console output never includes subscription, node names or credentials.
    print(json.dumps({"mode": "READ_ONLY", "generated_at": document["generated_at"],
                      "mihomo": document["service"]["mihomo"]["status"],
                      "awg": document["service"]["awg"]["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
