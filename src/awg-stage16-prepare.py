#!/usr/bin/env python3
"""Stage16: fail-closed root-side source validation and ephemeral proxy configs.

Only read protected provider and the fresh live pool. Never configure routes,
change selected node, expose raw subscription, or open a network socket.
"""
from __future__ import annotations
import collections
import hashlib
import importlib.util
import importlib.machinery
import ipaddress
import json
import os
from pathlib import Path
import sys
import time
import yaml

ROOT=Path(__file__).resolve().parent
PROVIDER=Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
POOL=Path("/run/awg-pbr/mihomo-pool/live.json")
DEST=Path("/run/awg-pbr/stage16-media")
TARGETS=(("shadowsocks-27307",17891),("shadowsocks-415241978",17892))
MAX_AGE=3600
MAX_CONFIG=65536

class Denied(Exception): pass

def load(name,filename):
    loader=importlib.machinery.SourceFileLoader(name,str(ROOT/filename))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    loader.exec_module(mod)
    return mod

def node_config(raw:dict, port:int) -> dict:
    """Deliberately exclude provider metadata, chaining, hooks and plugins."""
    if (not isinstance(raw,dict) or raw.get("type")!="ss"
            or not isinstance(raw.get("name"),str)):
        raise Denied("NOT_BASIC_SHADOWSOCKS")
    prohibited={"plugin","plugin-opts","dialer-proxy","detour",
                "interface-name","routing-mark","override-destination",
                "ip-version","smux"}
    if any(key in raw for key in prohibited):
        raise Denied("NONSTANDARD_NODE_REFUSED")
    host=raw.get("server")
    try:
        address=ipaddress.IPv4Address(host)
    except (ValueError,TypeError):
        raise Denied("NODE_IPV4_REQUIRED") from None
    if not address.is_global:
        raise Denied("NODE_PUBLIC_ENDPOINT_REQUIRED")
    srcport=raw.get("port")
    if isinstance(srcport,str) and srcport.isdecimal():
        srcport=int(srcport)
    if type(srcport) is not int or not 1 <= srcport <= 65535:
        raise Denied("NODE_PORT_INVALID")
    cipher=raw.get("cipher")
    secret=raw.get("password")
    if (not isinstance(cipher,str) or not 2 <= len(cipher) <= 120
            or not isinstance(secret,str) or not 1 <= len(secret) <= 4096):
        raise Denied("NODE_CIPHER_UNSUPPORTED")
    proxy={"name":"AWG-STAGE16-ONLY","type":"ss","server":str(address),
           "port":srcport,"cipher":cipher,"password":secret,"udp":False}
    return {"mixed-port":port,"allow-lan":False,"bind-address":"127.0.0.1",
            "mode":"rule","log-level":"silent","ipv6":False,
            "profile":{"store-selected":False,"store-fake-ip":False},
            "proxies":[proxy],
            "proxy-groups":[{"name":"AWG-STAGE16-ONLY-GROUP","type":"select",
                             "proxies":["AWG-STAGE16-ONLY"]}],
            "rules":["MATCH,AWG-STAGE16-ONLY-GROUP"]}

def prepare(*, pool:dict, raw:list, policy:tuple, trial, provenance,
            expected_names=TARGETS) -> list[dict]:
    if not isinstance(pool,dict) or not isinstance(raw,list):
        raise Denied("POOL_INVALID")
    region,protocol=policy
    if region=="europe" and pool.get("geo_enriched") is not True:
        raise Denied("GEO_POLICY_UNPROVEN")
    if protocol not in ("all","ss"):
        raise Denied("PROTOCOL_POLICY_EXCLUDES_TARGETS")
    candidates=[]
    used=set()
    names=collections.Counter(v.get("name") for v in raw if isinstance(v,dict))
    for name, port in expected_names:
        if names[name]!=1:
            raise Denied("PROVIDER_IDENTITY_NOT_UNIQUE")
        rows=[n for n in pool.get("nodes",[])
              if isinstance(n,dict) and n.get("name")==name]
        if len(rows)!=1 or rows[0].get("healthy") is not True:
            raise Denied("TARGET_NOT_HEALTHY_IN_POOL")
        row=rows[0]
        if type(row.get("delay_ms")) is not int or row["delay_ms"]<=0:
            raise Denied("TARGET_NO_VALID_LATENCY")
        if region=="europe" and row.get("europe") is not True:
            raise Denied("TARGET_GEO_POLICY_EXCLUDES")
        selected=trial.select({"nodes":[row]},raw,region=region,protocol=protocol,limit=1)
        if len(selected)!=1 or selected[0]["name"]!=name:
            raise Denied("PROVIDER_AND_POOL_MISMATCH")
        source=next(n for n in raw if isinstance(n,dict) and n.get("name")==name)
        config=node_config(source,port)
        endpoint=(config["proxies"][0]["server"],config["proxies"][0]["port"])
        if endpoint in used:
            raise Denied("DUPLICATE_ENDPOINT")
        used.add(endpoint)
        path=provenance.classify(source)
        if path.get("mode")!="DIRECT_LOCAL_UNVERIFIED":
            raise Denied("ENDPOINT_PI_DIRECT_NOT_CONFIRMED")
        # This is ONLY Pi-local evidence; MikroTik policy is NOT verified.
        candidates.append({"name":name,"port":port,
            "candidate_id":hashlib.sha256(name.encode()).hexdigest()[:12],
            "underlay":"PI_DIRECT_LOCAL_UNVERIFIED","config":config})
    return candidates

def write_config(*, item:dict, dirpath:Path=DEST):
    if not str(dirpath).startswith("/run/awg-pbr/stage16-media"):
        raise Denied("RAM_LOCATION_REQUIRED")
    if dirpath.exists() or dirpath.is_symlink():
        raise Denied("STAGING_ALREADY_PRESENT")
    # Only root-owned directories/files. Protected node keys copied solely
    # through systemd LoadCredential into the unrelated proxy DynamicUser.
    dirpath.mkdir(mode=0o700,parents=True,exist_ok=False)
    os.chmod(dirpath,0o700)
    port=item["port"]
    text=yaml.safe_dump(item["config"],sort_keys=False,allow_unicode=True)
    data=text.encode("utf-8")
    if not 1<=len(data)<=MAX_CONFIG:
        raise Denied("CONFIG_TOO_LARGE")
    dest=dirpath/f"proxy-{port}.yaml"
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    fd=os.open(dest,flags,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
    finally:
        if dest.is_file():
            os.chmod(dest,0o600)

def main():
    try:
        if os.geteuid()!=0: raise Denied("ROOT_PREPARATION_REQUIRED")
        if DEST.exists():raise Denied("STAGING_ALREADY_PRESENT")
        helper=load("stage16_pool","awg-mihomo-pool.py")
        trial=load("stage16_select","awg-mihomo-service-trial.py")
        smart=load("stage16_smart","awg-mihomo-smart")
        provenance=load("stage16_route","awg-endpoint-provenance.py")
        pool=json.loads(POOL.read_text("utf-8"))
        age=int(time.time())-int(pool.get("scanned_at") or 0)
        if age<0 or age>MAX_AGE:raise Denied("POOL_EXPIRED")
        if not smart.fresh_pool(pool,PROVIDER,MAX_AGE):
            raise Denied("PROVIDER_FINGERPRINT_MISMATCH")
        raw=helper.read_provider(PROVIDER)
        policy=helper.read_policy_values()
        candidates=prepare(pool=pool,raw=raw,policy=policy,
                           trial=trial,provenance=provenance)
        if len(candidates)!=2:raise Denied("EXACTLY_TWO_REQUIRED")
        for i,item in enumerate(candidates):
            # Atomic stage root-only directory on first write; rest reuse it.
            if i==0:
                write_config(item=item)
            else:
                dest=DEST/f"proxy-{item['port']}.yaml"
                data=yaml.safe_dump(item["config"],sort_keys=False,allow_unicode=True).encode()
                if not 1<=len(data)<=MAX_CONFIG:raise Denied("CONFIG_TOO_LARGE")
                with dest.open("xb") as f:f.write(data)
                os.chmod(dest,0o600)
        print(json.dumps({"mode":"SHADOW_ONLY","status":"PREPARED",
                          "candidate_count":len(candidates),
                          "candidates":[{"id":x["candidate_id"],
                                         "port":x["port"],
                                         "underlay":x["underlay"]}
                                        for x in candidates],
                          "router_verified":False,"service_ready":False,
                          "production_modified":False},sort_keys=True))
        return 0
    except (Denied,OSError,ValueError,KeyError,TypeError,RuntimeError,SystemExit) as ex:
        code=str(ex) if isinstance(ex,Denied) else "PREPARE_RUNTIME_UNAVAILABLE"
        print(json.dumps({"mode":"SHADOW_ONLY","status":"PREPARE_FAILED",
                          "reason":code,"production_modified":False}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
