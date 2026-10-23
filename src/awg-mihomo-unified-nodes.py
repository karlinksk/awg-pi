#!/usr/bin/env python3
"""Read-only unified Mihomo/Xray node inventory and isolated BASIC network probes.

No Hot Pool / READY, no live TUN, no active node changes and no systemd writes.
Results are basic HTTPS reachability only; they are not app/YouTube readiness.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

PROVIDER=Path(os.environ.get("AWG_UNIFIED_PROVIDER","/var/lib/awg-pbr/mihomo/providers/subscription.yaml"))
MIHOMO_POOL=Path(os.environ.get("AWG_UNIFIED_POOL","/run/awg-pbr/mihomo-pool/live.json"))
CACHE=Path(os.environ.get("AWG_UNIFIED_CACHE","/var/lib/awg-pbr/xray-vless/network-health.json"))
XRAY=Path(os.environ.get("AWG_UNIFIED_CORE","/usr/local/bin/awg-xray-vless-core"))
ADAPTER=Path(os.environ.get("AWG_UNIFIED_ADAPTER","/usr/local/sbin/awg-xray-vless"))
# Five-minute requalification, keep the last proof separately from its freshness.
TTL=86400
PROBE_INTERVAL=300
MAX_PROBE=10
XRAY_WORKERS=2
PROBE_URL="https://api.openai.com/v1/models"

def die(s):
    print("UNIFIED_ERROR="+s,file=sys.stderr)
    raise SystemExit(2)

def load_adapter():
    if not ADAPTER.is_file():die("XRAY_ADAPTER_NOT_INSTALLED")
    spec=importlib.util.spec_from_loader("awg_xray_adapter",SourceFileLoader("awg_xray_adapter",str(ADAPTER)))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROVIDER=PROVIDER
    return module

def read_json(path):
    try:
        # Both pool and health cache are trusted local state, not remote web.
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,UnicodeError):
        return {}

def snapshots(adapter):
    raw=adapter.secure_read(PROVIDER)
    nodes=adapter.read_provider()
    if not 1<=len(nodes)<=10000:die("INVALID_PROVIDER_COUNT")
    sha=hashlib.sha256(raw).hexdigest()
    pool=read_json(MIHOMO_POOL)
    # Last known good stays available for recovery; UI should show the latest
    # actual scan even if every node failed and the LKG was intentionally kept.
    lastscan=read_json(MIHOMO_POOL.with_name("live-lastscan.json"))
    if (lastscan.get("provider_sha256")==sha and lastscan.get("target")=="live"
        and isinstance(lastscan.get("scanned_at"),(int,float))
        and 0<=time.time()-lastscan["scanned_at"]<=3600
        and lastscan["scanned_at"]>=pool.get("scanned_at",0)):
        pool=lastscan
    if pool.get("provider_sha256")!=sha or pool.get("target")!="live" or time.time()-pool.get("scanned_at",0)>3600:
        pool={}
    # Cache is separate from Hot Pool; it is never authoritative for ready.
    cache=read_json(CACHE)
    # URL and subscription order/count can change. Keep a still-fresh proof
    # ONLY for an identical transport fingerprint, not a name or list index.
    # Filter against current profiles to purge removed/re-keyed credentials.
    valid=set(adapter.sha_profile(p) for p in nodes if isinstance(p,dict) and transport(p)=="XRAY")
    previous=cache.get("results",{}) if cache.get("version")==1 else {}
    if not isinstance(previous,dict):previous={}
    now=time.time()
    previous={k:v for k,v in previous.items()
              if k in valid and isinstance(v,dict)
              and isinstance(v.get("verified_at",v.get("at")),(int,float))
              and 0<=now-v.get("verified_at",v["at"])<=TTL
              and isinstance(v.get("at"),(int,float))
              and v.get("status") in ("NETWORK_OK","NETWORK_FAIL","UNKNOWN_HTTP","UNKNOWN_ERROR","UNAVAILABLE")}
    cache={"version":1,"provider_sha256":sha,"results":previous}
    return nodes,sha,pool,cache

def transport(node):
    if not isinstance(node,dict):return "UNSUPPORTED"
    if node.get("type")=="vless" and node.get("tls") is True and node.get("network") in ("xhttp","grpc"):
        if isinstance(node.get("reality-opts"),dict):return "XRAY"
        # Plain verified TLS/gRPC works via the same passive Xray sidecar.
        # Malformed REALITY hints and insecure TLS must not be promoted.
        if (node.get("network")=="grpc" and "reality-opts" not in node
            and node.get("skip-cert-verify") is not True):
            return "XRAY"
        return "UNSUPPORTED"
    if node.get("type") in ("hysteria2","ss","trojan","vmess","vless"):
        return "MIHOMO"
    return "UNSUPPORTED"

def inventory(nodes,pool,cache,adapter):
    names={}
    for node in nodes:
        if isinstance(node,dict):
            name=node.get("name")
            if isinstance(name,str):names[name]=names.get(name,0)+1
    status_map={(p.get("index"),p.get("name")):p for p in pool.get("nodes",[]) if isinstance(p,dict)}
    record=cache.get("results",{}) if isinstance(cache.get("results"),dict) else {}
    rows=[]
    for ix,node in enumerate(nodes,1):
        name=node.get("name","") if isinstance(node,dict) else ""
        engine=transport(node)
        health="UNTESTED"
        if not name or names.get(name)!=1:
            health="UNUSABLE_DUPLICATE_OR_MISSING_NAME"
        elif engine=="UNSUPPORTED":
            health="UNSUPPORTED"
        elif engine=="MIHOMO":
            entry=status_map.get((ix,name))
            if entry is not None:
                health="NETWORK_OK" if entry.get("healthy") is True else "NETWORK_FAIL"
        elif engine=="XRAY":
            ident=adapter.sha_profile(node)
            cached=record.get(ident,{})
            if (isinstance(cached,dict) and time.time()-cached.get("at",0)<=TTL):
                health=cached.get("status","UNTESTED")
        rows.append(dict(index=ix,name=name,engine=engine,
                         protocol=node.get("type","") if isinstance(node,dict) else "",
                         transport=node.get("network","") if isinstance(node,dict) else "",
                         basic_network=health))
    return rows

def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def build_xray(adapter,node,port):
    node_id,stream=adapter.validate(node)
    stream["sockopt"]={"interface":adapter.interface(),"domainStrategy":"UseIPv4"}
    return {
      "log":{"loglevel":"error"},
      "inbounds":[{"listen":"127.0.0.1","port":port,
                   "protocol":"socks","settings":{"auth":"noauth","udp":False}}],
      "outbounds":[{"protocol":"vless","settings":{"vnext":[{
        "address":node["server"],"port":node["port"],
        "users":[{"id":node_id,"encryption":"none",
                  **({"flow":node["flow"]} if node.get("flow") else {})}]}]},
        "streamSettings":stream}],
    }

def isolated_probe(adapter,node):
    if not XRAY.is_file() or not os.access(XRAY,os.X_OK):return "UNAVAILABLE"
    with tempfile.TemporaryDirectory(prefix="awg-unified-xray-",dir="/dev/shm") as d:
        root=Path(d);root.chmod(0o700)
        port=free_port()
        cfg=root/"xray.json"
        adapter.atomic_json(cfg,build_xray(adapter,node,port))
        verify=subprocess.run([str(XRAY),"run","-test","-c",str(cfg)],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
        if verify.returncode:return "NETWORK_FAIL"
        with (root/"xray.log").open("wb") as log:
            process=subprocess.Popen([str(XRAY),"run","-c",str(cfg)],
                stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            try:
                for _ in range(35):
                    if process.poll() is not None:return "NETWORK_FAIL"
                    try:
                        with socket.create_connection(("127.0.0.1",port),timeout=.15):break
                    except OSError:time.sleep(.12)
                else:return "NETWORK_FAIL"
                probe=subprocess.run(["curl","-q","-4","-sS","--socks5-hostname",
                    f"127.0.0.1:{port}","--noproxy","","--connect-timeout","7",
                    "--max-time","21","-o","/dev/null","-w","%{http_code}",
                    PROBE_URL],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=24)
                if probe.returncode==0 and probe.stdout=="401":
                    return "NETWORK_OK"
                if probe.returncode==0 and re.fullmatch(r"4[0-9]{2}|5[0-9]{2}",probe.stdout or ""):
                    return "UNKNOWN_HTTP"
                return "NETWORK_FAIL"
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        # TempDirectory removes Reality credentials and daemon logs.

def confirmed_probe(adapter,node,previous):
    """Two attempts on failure, isolated by profile fingerprint."""
    previous=previous if isinstance(previous,dict) else {}
    try:result=isolated_probe(adapter,node)
    except (OSError,ValueError,subprocess.TimeoutExpired,SystemExit):
        result="UNKNOWN_ERROR"
    if result=="NETWORK_FAIL":
        time.sleep(15)
        try:second=isolated_probe(adapter,node)
        except (OSError,ValueError,subprocess.TimeoutExpired,SystemExit):
            second="UNKNOWN_ERROR"
        result=second
    if result=="NETWORK_OK":
        status="NETWORK_OK"
    elif result=="NETWORK_FAIL":
        status="NETWORK_FAIL"
    else:
        # A 403 or probe-infrastructure error is NOT a proven server failure.
        # Retain a previous good last-proven result, not a prior negative one.
        status=("NETWORK_OK" if previous.get("status")=="NETWORK_OK"
                else "UNKNOWN_HTTP" if result=="UNKNOWN_HTTP" else "UNKNOWN_ERROR")
    verified_at=(time.time() if result in ("NETWORK_OK","NETWORK_FAIL")
                 else previous.get("verified_at",previous.get("at",0)))
    return {"at":time.time(),"verified_at":verified_at,
            "status":status,"last_probe":result}


def persist_cache(adapter,provider_sha,results):
    # Reconcile against the *current* provider identity set; never preserve
    # orphan records when server/port/UUID/Reality or node count changes.
    nodes=adapter.read_provider()
    allowed={adapter.sha_profile(n) for n in nodes if isinstance(n,dict) and transport(n)=="XRAY"}
    current=read_json(CACHE)
    previous=current.get("results",{}) if isinstance(current.get("results"),dict) else {}
    merged={k:v for k,v in {**previous,**results}.items()
            if k in allowed and isinstance(v,dict) and
            isinstance(v.get("at"),(int,float)) and
            0<=time.time()-v.get("verified_at",v["at"])<=TTL}
    adapter.atomic_json(CACHE,{"version":1,"provider_sha256":provider_sha,"results":merged})

def command():
    a=argparse.ArgumentParser(description="One provider / per-node engine inventory; no READY")
    sub=a.add_subparsers(dest="cmd",required=True)
    sub.add_parser("list")
    test=sub.add_parser("probe");test.add_argument("indices",nargs="+",type=int)
    sub.add_parser("probe-vless-all")
    resolve=sub.add_parser("resolve")
    resolve.add_argument("name")
    best=sub.add_parser("best")
    best.add_argument("--exclude",action="append",default=[])
    best.add_argument("--engine",choices=("ANY","MIHOMO","XRAY"),default="ANY")
    best.add_argument("--rotate",action="store_true",
                      help="rotate through current provider candidates by time bucket")
    x=a.parse_args()
    if os.geteuid()!=0:die("ROOT_REQUIRED")
    adapter=load_adapter()
    nodes,sha,pool,cache=snapshots(adapter)
    if x.cmd in ("probe","probe-vless-all"):
        if x.cmd=="probe":
            indices=x.indices
            if not indices or len(indices)>MAX_PROBE or len(set(indices))!=len(indices):
                die("BAD_PROBE_COUNT")
        else:
            # Unlimited changing subscription size, bounded work per run.
            # Scan only untested/stale exact nodes; never loop over 1500
            # profiles or spin on already checked failures.
            row_list=inventory(nodes,pool,cache,adapter)
            history=cache.get("results",{})
            now=time.time()
            due=[]
            for row in row_list:
                if row["engine"]!="XRAY":continue
                node=nodes[row["index"]-1]
                fingerprint=adapter.sha_profile(node)
                previous=history.get(fingerprint,{})
                at=previous.get("at",0) if isinstance(previous,dict) else 0
                if now-at>=PROBE_INTERVAL:
                    due.append((at,row["index"]))
            # Oldest proof first: a changing 2000-node subscription cannot
            # starve later profiles behind the first MAX_PROBE entries.
            due.sort()
            eligible=[index for _,index in due]
            print("UNIFIED_XRAY_SCAN_ELIGIBLE="+str(len(eligible)),flush=True)
            indices=eligible[:MAX_PROBE]
            print("UNIFIED_XRAY_SCAN_BATCH="+str(len(indices)),flush=True)
            print("UNIFIED_XRAY_SCAN_REMAINING="+str(max(0,len(eligible)-len(indices))),flush=True)
            if not indices:return
        updated={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=XRAY_WORKERS) as executor:
            futures={}
            for i in indices:
                if not 1<=i<=len(nodes):die("INDEX_OUT_OF_RANGE")
                node=nodes[i-1]
                if transport(node)!="XRAY":die("XRAY_ONLY_PROBE")
                ident=adapter.sha_profile(node)
                previous=cache.get("results",{}).get(ident,{})
                future=executor.submit(confirmed_probe,adapter,node,previous)
                futures[future]=(i,ident)
            for future in concurrent.futures.as_completed(futures):
                i,ident=futures[future]
                updated[ident]=future.result()
                print(f"UNIFIED_PROBE_INDEX={i} ENGINE=XRAY BASIC_NETWORK={updated[ident]['status']}",flush=True)
        # Subscription may change while probing; do not persist stale identity.
        if hashlib.sha256(adapter.secure_read(PROVIDER)).hexdigest()!=sha:
            die("PROVIDER_CHANGED_DURING_PROBE")
        persist_cache(adapter,sha,updated)
        return
    rows=inventory(nodes,pool,cache,adapter)
    if x.cmd=="resolve":
        matches=[r for r in rows if r["name"]==x.name]
        if len(matches)!=1 or matches[0]["engine"]=="UNSUPPORTED" or matches[0]["basic_network"]=="UNUSABLE_DUPLICATE_OR_MISSING_NAME":
            die("NODE_AMBIGUOUS_OR_UNSUPPORTED")
        row=matches[0]
        print("NODE_ENGINE="+row["engine"])
        print("NODE_INDEX="+str(row["index"]))
        print("NODE_BASIC_NETWORK="+row["basic_network"])
        print("NODE_PROVIDER_SHA256="+sha)
        # Resolving an engine is never permission to activate it.  In
        # particular the manual canary rollback targets a healthy old node,
        # which is NOT a valid recovery target after automatic failover.
        print("NODE_ACTIVATED=NO")
        print("NODE_LIVE_FAILOVER_CERTIFIED=NO")
        return
    if x.cmd=="best":
        # Read-only candidate suggestion, NOT an activation command.
        options=[row for row in rows if row["basic_network"]=="NETWORK_OK" and
                 row["name"] not in x.exclude and
                 (x.engine=="ANY" or row["engine"]==x.engine)]
        if not options:raise SystemExit(1)
        # Keep manual/default deterministic. AUTO may rotate its start across
        # 5-minute periods so bounded recovery attempts can eventually
        # consider every compatible current profile, not the same first two.
        offset=(int(time.time()//300)%len(options)) if x.rotate else 0
        print(options[offset]["name"])
        return
    print("UNIFIED_READY_GATE=OFF")
    print("UNIFIED_PROVIDER_COUNT="+str(len(rows)))
    print("UNIFIED_POOL_CACHE="+("CURRENT" if pool else "STALE_OR_ABSENT"))
    # A cache file with zero valid proofs must not be displayed as healthy.
    print("UNIFIED_XRAY_CACHE="+("HAS_FRESH_RESULTS" if cache.get("results") else "NO_FRESH_RESULTS"))
    for row in rows:
        # Avoid printing endpoint, UUID, subscription URLs, credentials.
        safe_name=json.dumps(row["name"][:160],ensure_ascii=False)
        print("NODE={index} ENGINE={engine} PROTOCOL={protocol} TRANSPORT={transport} BASIC_NETWORK={basic_network} NAME={name}".format(**{**row,"name":safe_name}))

if __name__=="__main__":
    command()
