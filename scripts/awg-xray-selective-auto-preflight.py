#!/usr/bin/env python3
"""Test-Pi-only bounded Selective Xray candidate audit; no live routing changes.

--check: read-only; --scan: isolated loopback Xray HTTPS and its identity cache.
Never stages/enables Xray, touches nft/PBR/router, or changes active node.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

MODE=Path("/etc/awg-pbr/mode")
NODE=Path("/etc/awg-pbr/transports/mihomo/node-name")
POLICY=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
READY=Path("/etc/awg-pbr/transports/mihomo/ready-auto.mode")
BRIDGES=(Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
         Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
         Path("/var/lib/awg-pbr/xray-vless/selected.json"))
HELPER="/usr/local/sbin/awg-mihomo-unified-nodes"
TIMER="awg-mihomo-hot-pool.timer"

def run(*args,timeout=18):
    p=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError("COMMAND_FAILED_"+Path(args[0]).name)
    return p.stdout.strip()

def active(name):
    return subprocess.run(["systemctl","is-active","--quiet",name],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode==0

def fingerprint():
    if os.geteuid()!=0 or socket.gethostname()!="awg-upgrade":
        raise RuntimeError("TEST_PI_ROOT_ONLY")
    if MODE.read_text().strip()!="selective":raise RuntimeError("NOT_SELECTIVE")
    if POLICY.read_text().strip()!="auto":raise RuntimeError("NODE_AUTO_NOT_CONFIGURED")
    if READY.read_text().strip()!="0":raise RuntimeError("READY_OPTIN_NOT_DISABLED")
    if any(p.exists() for p in BRIDGES):raise RuntimeError("XRAY_BRIDGE_ALREADY_STAGED")
    if active("awg-xray-vless.service") or active(TIMER):
        raise RuntimeError("XRAY_OR_HOT_POOL_ACTIVE")
    for name in ("awg-mihomo.service","awg-quick@awg0.service","awg-selection-monitor.service",
                 "awg-pbr-health.service","ssh.service","dnsmasq.service"):
        if not active(name):raise RuntimeError("MISSING_SERVICE_"+name.split(".")[0])
    if run("/usr/local/sbin/awg-transport","get")!="mihomo":
        raise RuntimeError("ACTIVE_TRANSPORT_NOT_MIHOMO")
    for backend in ("mihomo","awg"):
        if run("/usr/local/sbin/awg-transport","check",backend)!="healthy":
            raise RuntimeError("BACKEND_NOT_HEALTHY_"+backend)
    for table in ("100","101"):
        output=run("ip","-4","route","show","table",table)
        if not re.fullmatch(r"default\s+dev\s+mihomo0(?:\s+.*)?",output.strip()):
            raise RuntimeError("FOREIGN_ROUTE_TABLE_"+table)
    ipv4=run("ip","-4","route","show","default")
    if not re.search(r"\bdev\s+eth0\b",ipv4):
        raise RuntimeError("MAIN_DEFAULT_NOT_LAN")
    if not NODE.is_file() or not NODE.read_bytes().strip():
        raise RuntimeError("NO_ACTIVE_NODE")
    chosen=hashlib.sha256(NODE.read_bytes()).hexdigest()
    config=hashlib.sha256(POLICY.read_bytes()).hexdigest()
    return chosen,config

def count_network(lines):
    results={}
    for line in lines:
        if not line.startswith("NODE="):continue
        try:
            fields=dict(p.split("=",1) for p in line.split() if "=" in p)
            engine=fields["ENGINE"]
            status=fields["BASIC_NETWORK"]
        except (ValueError,KeyError):continue
        key=(engine,status)
        results[key]=results.get(key,0)+1
    return results

def safe_report():
    lines=run(HELPER,"list",timeout=20).splitlines()
    for line in lines:
        if line.startswith(("UNIFIED_PROVIDER_COUNT=","UNIFIED_POOL_CACHE=","UNIFIED_XRAY_CACHE=")):
            print(line,flush=True)
    for (engine,health),n in sorted(count_network(lines).items()):
        # Aggregates only: never output a provider URL, credentials or node name.
        print("ENGINE="+engine+" HEALTH="+health+" COUNT="+str(n),flush=True)

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ("--check","--scan"):
        raise SystemExit("Usage: python3 script --check|--scan")
    baseline=fingerprint()
    print("SELECTIVE_PREFLIGHT=PASS",flush=True)
    if sys.argv[1]=="--scan":
        # The helper stages temporary Xray process/config strictly in RAM;
        # it only persists bounded, credential-fingerprinted network cache.
        # Five Xray records need at most two batches of <=4.
        for round_no in (1,2):
            if fingerprint()!=baseline:raise RuntimeError("STATE_CHANGED_BEFORE_SCAN")
            print("SELECTIVE_SCAN_ROUND="+str(round_no),flush=True)
            out=run(HELPER,"probe-vless-all",timeout=125)
            for line in out.splitlines():
                if line.startswith(("UNIFIED_XRAY_SCAN_","UNIFIED_PROBE_INDEX=")):
                    print(line,flush=True)
            if "UNIFIED_XRAY_SCAN_BATCH=0" in out:break
    if fingerprint()!=baseline:raise RuntimeError("ACTIVE_STATE_CHANGED")
    safe_report()
    print("SELECTIVE_ACTIVE_TRANSPORT_UNCHANGED=PASS",flush=True)
    print("SELECTIVE_ROOTLESS_AUTO_XRAY_ENABLED=NO",flush=True)

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("SELECTIVE_PREFLIGHT=FAIL_"+str(exc),flush=True)
        raise SystemExit(1)
