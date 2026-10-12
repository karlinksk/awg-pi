#!/usr/bin/env python3
"""Bounded, service-first isolated candidate trial (STAGING ONLY).

This is NOT installed in production or in the awg-gpt sudo allowlist.
The future installer may expose a narrowly authorized, root-owned one-shot
invocation after audit. Never grant the assistant direct read access to the
protected Mihomo provider or add broad NOPASSWD sudo permissions.

Reads a root-protected provider transiently; does NOT print subscriptions,
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
from pathlib import Path
import sys
import time

MODULE_DIR = Path(__file__).resolve().parent
POOL = Path("/run/awg-pbr/mihomo-pool/live.json")
PROVIDER = Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
MAX_CANDIDATES = 3
TIME_LIMIT = 90


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
    for n in sorted(pool["nodes"],
                    key=lambda v: (v.get("delay_ms", 2**30), str(v.get("name","")))
                    if isinstance(v,dict) else (2**31,"")):
        if not isinstance(n,dict) or n.get("healthy") is not True:
            continue
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
        if (p.get("server") != n.get("server")
                or p.get("port") != n.get("port")
                or p.get("type") != n.get("type")):
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
    return {"mode":"SHADOW_ONLY","provider_fingerprint":provider_sha[:12],
            "candidates_tested":len(output),"duration_seconds":round(elapsed,1),
            "service_qualification":"SINGLE_SAMPLE_ONLY",
            "video_decoder_used":False,
            "production_modified":False,
            "results":output}


def run(*, limit:int=3, timeout:float=3.0) -> dict:
    if os.geteuid()!=0:
        raise PermissionError("protected provider must be read by authorized root service")
    if not 1<=limit<=MAX_CANDIDATES or not 1<=timeout<=5:
        raise ValueError("unsupported trial budget")
    standby=load("trial_standby","awg-mihomo-standby.py")
    smart=load("trial_smart","awg-mihomo-smart")
    if not smart.fresh_pool(json.loads(POOL.read_text("utf-8")), PROVIDER,
                            standby.MAX_POOL_AGE):
        raise RuntimeError("missing or stale protected pool")
    helper=smart.load_pool_code()
    service=smart.load_service_code()
    region, protocol=helper.read_policy_values()
    pool=json.loads(POOL.read_text("utf-8"))
    if region=="europe" and pool.get("geo_enriched") is not True:
        raise RuntimeError("Europe policy cannot use unverified geography")
    raw=helper.read_provider(PROVIDER)
    chosen=select(pool, raw, region=region, protocol=protocol, limit=limit)
    if not chosen:
        raise RuntimeError("no eligible isolated candidates")
    start=time.monotonic()
    boot_before=standby.boot_identity()
    gen_before=standby.current_generation()
    output=standby.probe_candidates(chosen,raw,helper,service,
                                    timeout=timeout,
                                    deadline=start+min(TIME_LIMIT,15+limit*25))
    # One successful pass is only a signal for a second trial, never a
    # ready/route-authorized node. If any network/provider context changed
    # over the probe, all observations must be downgraded.
    if (boot_before!=standby.boot_identity()
            or gen_before!=standby.current_generation()
            or not smart.fresh_pool(pool,PROVIDER,standby.MAX_POOL_AGE)):
        output={}
    return sanitized(output,chosen,provider_sha=pool["provider_sha256"],
                     elapsed=time.monotonic()-start)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit",type=int,default=3)
    parser.add_argument("--timeout",type=float,default=3.0)
    args=parser.parse_args()
    try:
        data=run(limit=args.limit,timeout=args.timeout)
    except (RuntimeError,PermissionError,OSError,ValueError,KeyError):
        data={"mode":"SHADOW_ONLY","candidates_tested":0,
              "status":"UNAVAILABLE","production_modified":False}
    print(json.dumps(data,sort_keys=True,separators=(",",":")))
    return 0 if data.get("candidates_tested",0)>0 else 1


if __name__=="__main__":
    raise SystemExit(main())
