#!/usr/bin/env python3
"""Bounded, service-first isolated candidate trial (STAGING ONLY).

This is NOT installed in production or in the awg-gpt sudo allowlist.
Run ONLY as a systemd DynamicUser one-shot with a private, read-only copy
of the <=480kB root-selected three-node credential via LoadCredential=. Never grant broad sudo.
No root execution, no production routing changes.

Reads only the tiny systemd-provided selected-node credential; does NOT print subscriptions,
passwords, UUIDs, TLS names, proxy raw config, request bodies, or signed URLs.
Uses a second ephemeral Mihomo proxy entirely on 127.0.0.1 in RAM.
Never selects a node in the live Mihomo, reconfigures a tunnel, touches
MikroTik/SSTP, or authorizes a transport switch.

This lightweight phase checks service requests; a proper *decoded* YouTube
frame must be provided separately before marking SERVICE_READY.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import os
import re
import stat
from pathlib import Path
import sys
import time

MODULE_DIR = Path(__file__).resolve().parent
POOL = Path("/run/awg-pbr/mihomo-pool/live.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
MAX_CANDIDATES = 3
TIME_LIMIT = 90
CREDENTIAL_NAMES = ("selection",)


def credential_paths(*, env=None, uid=None) -> dict:
    """Only an unprivileged service supplied with systemd credentials may run.

    No root-running parser, broad sudo grant or chmod of the protected files.
    A CLI-only spoofed CREDENTIALS_DIRECTORY contains no source secrets.
    """
    e = os.environ if env is None else env
    effective = os.geteuid() if uid is None else uid
    if effective == 0:
        raise PermissionError("trial must run as nonroot DynamicUser")
    raw = e.get("CREDENTIALS_DIRECTORY", "")
    if not raw or not raw.startswith("/run/credentials/"):
        raise PermissionError("systemd credentials required")
    base = Path(raw)
    if not base.is_dir() or base.is_symlink():
        raise PermissionError("credential directory unavailable")
    result = {}
    for name in CREDENTIAL_NAMES:
        item = base / name
        if (not item.is_file() or item.is_symlink()
                or not 1 <= item.stat().st_size <= 480_000):
            raise PermissionError("missing or invalid service credential")
        result[name] = item
    return result



def load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(MODULE_DIR / filename))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def select(pool: dict, raw: list[dict], *, region: str = "all",
           protocol: str = "all", limit: int = MAX_CANDIDATES) -> list[dict]:
    """The trusted current pool picks up to 3 unique live provider nodes.

    Do not use a node name provided by an external JSON as an authorization
    token; re-match endpoint name, host, type and port to protected provider.
    """
    if not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("candidate cap exceeded")
    if not isinstance(pool, dict) or not isinstance(pool.get("nodes"), list):
        raise ValueError("invalid pool")
    if not isinstance(raw, list):
        raise ValueError("invalid provider")
    raw_names = collections.Counter(x.get("name") for x in raw
                         if isinstance(x, dict) and isinstance(x.get("name"), str))
    result = []
    seen = set()
    pool_names = collections.Counter(n.get("name") for n in pool["nodes"]
                                    if isinstance(n, dict))
    # The production pool intentionally contains unhealthy/invalid rows with
    # delay_ms=null. Filtering must precede sorting: sorting int and None
    # raises TypeError and previously aborted all candidate preparation.
    healthy = [
        n for n in pool["nodes"]
        if isinstance(n, dict)
        and n.get("healthy") is True
        and type(n.get("delay_ms")) is int
        and n["delay_ms"] > 0
    ]
    for n in sorted(healthy, key=lambda v: (v["delay_ms"], str(v.get("name", "")))):
        name=n.get("name")
        if not isinstance(name,str) or raw_names[name] != 1 or pool_names[name] != 1:
            continue
        if region == "europe" and n.get("europe") is not True:
            continue
        if protocol != "all" and n.get("type") != protocol:
            continue
        matches=[x for x in raw if isinstance(x,dict) and x.get("name")==name]
        if len(matches)!=1:
            continue
        p=matches[0]
        # The original Mihomo pool normalizes numeric YAML port strings in
        # clean_node(); compare against that canonical form, not raw YAML.
        raw_port = p.get("port")
        if isinstance(raw_port, str) and raw_port.isdecimal():
            raw_port = int(raw_port)
        if (p.get("server") != n.get("server")
                or type(raw_port) is not int
                or raw_port != n.get("port")
                or p.get("type") != n.get("type")):
            continue
        # If the scan provides its original one-based index, also require
        # that this name uniquely came from the exact provider record.
        index = n.get("index")
        if index is not None and (
                type(index) is not int or index < 1
                or index > len(raw) or raw[index-1] is not p):
            continue
        # Different nodes on the exact same endpoint are not independent spares.
        endpoint=(n["server"],n["port"])
        if endpoint in seen:
            continue
        if (not isinstance(n.get("delay_ms"),int) or n["delay_ms"] <= 0
                or not isinstance(n.get("server"),str)
                or not isinstance(n.get("port"),int)):
            continue
        seen.add(endpoint)
        result.append({k:n[k] for k in
                       ("name","type","server","port","delay_ms")})
        if len(result)>=limit:
            break
    return result


def sanitized(raw_result: dict, chosen: list[dict], *,
              provider_sha: str, elapsed: float) -> dict:
    """Emit only per-service result states and a hashed ephemeral node id."""
    output = []
    for node in chosen:
        r = raw_result.get(node["name"], {})
        checks = r.get("checks", {}) if isinstance(r,dict) else {}
        clean = {}
        for label in ("openai_api","chatgpt_web","youtube_video"):
            record = checks.get(label, {}) if isinstance(checks,dict) else {}
            status = record.get("state") if isinstance(record,dict) else "UNKNOWN"
            clean[label] = status if status in ("PASS","FAIL","UNKNOWN") else "UNKNOWN"
        # The identity is derived from the provider-verified name, no credentials.
        identity = hashlib.sha256(node["name"].encode("utf-8")).hexdigest()[:12]
        nominal = ("PASS" if all(v=="PASS" for v in clean.values())
                   else "FAIL" if "FAIL" in clean.values() else "UNKNOWN")
        actual = (isinstance(r,dict) and
                  r.get("transport")=="mihomo" and
                  r.get("identity")==node["name"] and
                  isinstance(r.get("sample_id"),str) and
                  re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}",r["sample_id"]) and
                  r.get("status")==nominal)
        if not actual:
            nominal = "UNKNOWN"
            clean={name:"UNKNOWN" for name in clean}
        output.append({"candidate_id":identity,
                       "protocol":node["type"],
                       "checks":clean,
                       "service_single_sample":nominal,
                       "service_ready":False,
                       "routing_qualified":False})
    measured = sum(1 for n in chosen
                   if isinstance(raw_result.get(n["name"]), dict)
                   and bool(raw_result[n["name"]].get("sample_id")))
    return {"mode":"SHADOW_ONLY","provider_fingerprint":provider_sha[:12],
            "candidates_selected":len(output),"candidates_tested":measured,
            "duration_seconds":round(elapsed,1),
            "service_qualification":"SINGLE_SAMPLE_ONLY",
            "video_decoder_used":False,
            "production_modified":False,
            "results":output}


def run(*, limit:int=3, timeout:float=3.0) -> dict:
    if not 1<=limit<=MAX_CANDIDATES or not 1<=timeout<=5:
        raise ValueError("unsupported trial budget")
    files = credential_paths()
    envelope = json.loads(files["selection"].read_text("utf-8"))
    if not isinstance(envelope, dict) or envelope.get("version") != 1:
        raise ValueError("unverified selected credential")
    created = envelope.get("prepared_at")
    now = int(time.time())
    if (not isinstance(created,int) or isinstance(created,bool) or
            not 0 <= now-created <= 300 or
            envelope.get("mode") != "SHADOW_ONLY" or
            envelope.get("service_ready") is not False or
            envelope.get("routing_verified") is not False):
        raise ValueError("expired or invalid selected credential")
    chosen, raw = envelope.get("candidates"), envelope.get("proxies")
    provider_hash = envelope.get("provider_sha256")
    if (not isinstance(chosen,list) or not isinstance(raw,list)
            or not 1 <= len(chosen) <= limit or len(raw) != len(chosen)
            or not isinstance(provider_hash,str)
            or not re.fullmatch(r"[0-9a-f]{64}",provider_hash)):
        raise ValueError("invalid selected nodes")
    # Match every item to its original root-prepared endpoint again, even
    # though systemd's credential copy is already private and read-only.
    safe_pool={"nodes":[dict(item,healthy=True) for item in chosen]}
    if select(safe_pool,raw,limit=len(chosen)) != chosen:
        raise ValueError("credential/node binding changed")
    standby=load("trial_standby","awg-mihomo-standby.py")
    smart=load("trial_smart","awg-mihomo-smart")
    smart.POOL_PY = MODULE_DIR / "awg-mihomo-pool.py"
    helper=smart.load_pool_code()
    service=smart.load_service_code()
    boot_before=standby.boot_identity()
    gen_before=standby.current_generation()
    if (boot_before != envelope.get("boot_id")
            or gen_before != envelope.get("route_generation")):
        raise ValueError("runtime changed after credential preparation")
    start=time.monotonic()
    output=standby.probe_candidates(chosen,raw,helper,service,
                                    timeout=timeout,
                                    deadline=start+min(TIME_LIMIT,15+limit*25))
    # This is a ONE-SAMPLE shadow report, never candidate admission. A boot
    # or local router generation change cancels every observed service result.
    if (boot_before!=standby.boot_identity()
            or gen_before!=standby.current_generation()
            or int(time.time()) - created > 300):
        output={}
    return sanitized(output,chosen,provider_sha=provider_hash,
                     elapsed=time.monotonic()-start)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit",type=int,default=3)
    parser.add_argument("--timeout",type=float,default=3.0)
    args=parser.parse_args()
    try:
        data=run(limit=args.limit,timeout=args.timeout)
    except (RuntimeError,PermissionError,OSError,ValueError,KeyError,TypeError):
        data={"mode":"SHADOW_ONLY","candidates_tested":0,
              "status":"UNAVAILABLE","production_modified":False}
    print(json.dumps(data,sort_keys=True,separators=(",",":")))
    return 0 if data.get("candidates_tested",0)>0 else 1


if __name__=="__main__":
    raise SystemExit(main())
