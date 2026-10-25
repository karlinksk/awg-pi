#!/usr/bin/env python3
"""Bounded isolated Xray VLESS discovery on the authorized test Pi.

The only persistent write is the *existing* root-owned network-health cache
made by awg-mihomo-unified-nodes probe. Does NOT touch services, the active
transport, FIXED policy, nftables, routing, DNS or subscription.
Never prints node names, endpoint details, subscription URLs or credentials.
"""
import argparse
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

LIVE=Path("/usr/local/sbin/awg-mihomo-unified-nodes")
EXPECTED_HOST="awg-upgrade"
MODE=Path("/etc/awg-pbr/mode")
BRIDGE=Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
ACTIVE_SERVICE="awg-mihomo.service"
SIDECAR_SERVICE="awg-xray-vless.service"
PROBE_TIMEOUT_PER_NODE=40

def verdict(key,value):
    print("XRAY_DISCOVERY_"+key+"="+str(value),flush=True)

def run(args,timeout=12):
    try:
        return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        return None

def valid_roots():
    if os.geteuid()!=0 or socket.gethostname()!=EXPECTED_HOST:
        return False,"ROOT_TEST_PI_REQUIRED"
    if MODE.read_text().strip()!="transit":
        return False,"TRANSIT_REQUIRED"
    a=run(["systemctl","is-active",ACTIVE_SERVICE],timeout=5)
    b=run(["systemctl","is-active",SIDECAR_SERVICE],timeout=5)
    if not a or a.stdout.strip()!="active" or not b or b.stdout.strip()=="active":
        return False,"ACTIVE_SERVICES_NOT_SAFE"
    if BRIDGE.exists() or SELECTED.exists():
        return False,"CROSS_CORE_ALREADY_STAGED"
    en=run(["systemctl","is-enabled",SIDECAR_SERVICE],timeout=5)
    if not en or en.stdout.strip() not in ("disabled","static"):
        return False,"XRAY_AUTO_START_UNEXPECTED"
    for table in ("100","101"):
        r=run(["ip","route","show","table",table],timeout=5)
        if not r or r.returncode or not re.search(
            r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",r.stdout):
            return False,"MIHOMO_TUN_ROUTES_CHANGED"
    if not LIVE.is_file() or not os.access(LIVE,os.X_OK):
        return False,"UNIFIED_CATALOG_MISSING"
    guard=run(["/usr/local/sbin/awg-transit-routing","status"],timeout=9)
    if not guard or guard.returncode or not all(
        expected in guard.stdout.splitlines() for expected in
        ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")):
        return False,"TRANSIT_GUARD_UNSAFE"
    return True,"PASS"

def candidates(rows):
    eligible=[row for row in rows if row["engine"]=="XRAY" and
              row["basic_network"]=="UNTESTED"]
    present=[row for row in rows if row["engine"]=="XRAY" and
             row["basic_network"]=="NETWORK_OK"]
    return eligible,present

def snapshot():
    spec=importlib.util.spec_from_loader("xray_unified_discovery",
              SourceFileLoader("xray_unified_discovery",str(LIVE)))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter=module.load_adapter()
    nodes,sha,pool,cache=module.snapshots(adapter)
    rows=module.inventory(nodes,pool,cache,adapter)
    return module,rows,sha

def scan(batch_size,scanner=run):
    ok,reason=valid_roots()
    if not ok:
        verdict("ERROR",reason)
        return 2
    try:
        _,rows,startsha=snapshot()
    except (OSError,ValueError,RuntimeError,SystemExit):
        verdict("ERROR","CATALOG_UNAVAILABLE")
        return 2
    pending,good=candidates(rows)
    verdict("SCOPE","ISOLATED_BASIC_HTTPS_ONLY")
    verdict("PROVIDER_PROFILE_COUNT",len(rows))
    verdict("XRAY_PROFILE_COUNT",sum(r["engine"]=="XRAY" for r in rows))
    verdict("NETWORK_OK_BEFORE",len(good))
    # If a recently tested profile already works, stop. No point scanning
    # additional remote servers or spending more traffic.
    if good:
        verdict("SCAN_BATCH",0)
        verdict("NETWORK_OK_AFTER",len(good))
        verdict("FIXED_POLICY_CHANGED","NO")
        verdict("LIVE_SERVICE_CHANGED","NO")
        verdict("CANDIDATE_FOR_REVIEW","YES")
        return 0
    selected=pending[:batch_size]
    verdict("SCAN_BATCH",len(selected))
    if not selected:
        verdict("CANDIDATE_FOR_REVIEW","NO")
        verdict("SCAN_STATUS","NO_UNTESTED_XRAY")
        return 0
    # Existing upstream helper validates exact provider SHA after probing,
    # limits the Xray subprocess to RAM and writes only isolated health cache.
    indices=[str(r["index"]) for r in selected]
    p=scanner([str(LIVE),"probe",*indices],
              timeout=batch_size*PROBE_TIMEOUT_PER_NODE+12)
    if p is None or p.returncode:
        verdict("SCAN_STATUS","PROBE_FAILED_OR_PROVIDER_CHANGED")
        return 1
    try:
        _,after,finalsha=snapshot()
    except (OSError,ValueError,RuntimeError,SystemExit):
        verdict("SCAN_STATUS","PROVIDER_CHANGED_AFTER_PROBE")
        return 1
    if finalsha!=startsha:
        verdict("SCAN_STATUS","PROVIDER_CHANGED_AFTER_PROBE")
        return 1
    _,good=candidates(after)
    verdict("NETWORK_OK_AFTER",len(good))
    verdict("SCAN_STATUS","COMPLETED")
    verdict("FIXED_POLICY_CHANGED","NO")
    verdict("LIVE_SERVICE_CHANGED","NO")
    verdict("CANDIDATE_FOR_REVIEW","YES" if good else "NO")
    return 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--batch",type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.batch<=6:
        verdict("ERROR","BATCH_MUST_BE_1_TO_6")
        return 2
    return scan(args.batch)

if __name__=="__main__":
    sys.exit(main())
