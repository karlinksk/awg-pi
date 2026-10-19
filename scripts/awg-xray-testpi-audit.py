#!/usr/bin/env python3
"""Read-only privileged preflight for the authorized AWG test Pi.

Prints no node names, subscription URLs, addresses, keys or credentials.
NO writes, service changes, route changes, probe scans, or sidecar activation.
"""
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
LIVE=Path("/usr/local/sbin")
PBR=Path("/etc/awg-pbr")
POLICY=PBR/"transports/mihomo"
BACKUPS=Path("/var/backups/awg-gateway")
FILES={
 "awg-mihomo-config":"src/awg-mihomo-config",
 "awg-mihomo-unified-nodes":"src/awg-mihomo-unified-nodes.py",
 "awg-xray-activation-transaction":"src/awg-xray-activation-transaction.py",
 "awg-xray-live-backend":"src/awg-xray-live-backend.py",
}

def run(args,timeout=12):
    try:
        return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
          stderr=subprocess.DEVNULL,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        return None

def exact_mode(mode):
    return mode in ("fixed","auto","manual")

def later_nodes(current, names):
    if len(names)!=len(set(names)) or current not in names:
        return []
    return names[names.index(current)+1:]

def get_engine(name):
    p=run([str(LIVE/"awg-mihomo-unified-nodes"),"resolve",name],timeout=14)
    if p is None or p.returncode!=0 or len(p.stdout)>1500:
        return "UNKNOWN","UNVERIFIED"
    info=dict(line.split("=",1) for line in p.stdout.splitlines()
              if "=" in line and re.fullmatch(r"[A-Z_]{3,60}",line.split("=",1)[0]))
    return info.get("NODE_ENGINE","UNKNOWN"), info.get("NODE_BASIC_NETWORK","UNVERIFIED")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def status(message,value):
    print("XRAY_AUDIT_"+message+"="+str(value),flush=True)

def main():
    if len(sys.argv)!=2 or sys.argv[1]!="--check":
        raise SystemExit("Usage: sudo python3 scripts/awg-xray-testpi-audit.py --check")
    if os.geteuid()!=0 or socket.gethostname()!="awg-upgrade":
        status("ERROR","ROOT_TEST_PI_REQUIRED")
        return 2
    if (PBR/"mode").read_text().strip()!="transit":
        status("ERROR","WRONG_MODE")
        return 2
    status("SCOPE","READ_ONLY")
    for target,source in FILES.items():
        live=LIVE/target
        reference=ROOT/source
        if (not live.is_file() or live.is_symlink() or live.stat().st_uid!=0 or
            not reference.is_file() or digest(live)!=digest(reference)):
            status("ERROR","INSTALLED_HASH_MISMATCH")
            return 1
    status("SOURCE_HASHES","MATCH")
    snapshots=sorted(BACKUPS.glob("xray-passive-stage-*"))
    backup_ok=False
    for snap in reversed(snapshots):
        if not snap.is_dir() or snap.is_symlink():continue
        if all((snap/item).is_file() or (snap/(item+".absent")).is_file()
               for item in FILES):
            backup_ok=True
            break
    status("PASSIVE_BACKUP","VERIFIED" if backup_ok else "MISSING_OR_INCOMPLETE")
    if not backup_ok:return 1
    statuses={}
    for service in ("awg-mihomo.service","awg-xray-vless.service",
                    "awg-selection-monitor.service","dnsmasq.service"):
        p=run(["systemctl","is-active",service],timeout=5)
        statuses[service]=(p.stdout.strip() if p else "UNKNOWN")
    status("MIHOMO",statuses["awg-mihomo.service"].upper())
    status("XRAY",statuses["awg-xray-vless.service"].upper())
    if statuses["awg-mihomo.service"]!="active" or statuses["awg-xray-vless.service"]=="active":
        status("ERROR","UNEXPECTED_ACTIVE_TRANSPORT")
        return 1
    if statuses["awg-selection-monitor.service"]!="active" or statuses["dnsmasq.service"]!="active":
        status("ERROR","MANAGEMENT_SERVICE_INACTIVE")
        return 1
    enabled=run(["systemctl","is-enabled","awg-xray-vless.service"],timeout=5)
    if enabled is None or enabled.stdout.strip() not in ("disabled","static"):
        status("ERROR","XRAY_AUTOSTART_UNEXPECTED")
        return 1
    if Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf").exists():
        status("ERROR","BRIDGE_ALREADY_INSTALLED")
        return 1
    if Path("/var/lib/awg-pbr/xray-vless/selected.json").exists():
        status("ERROR","SELECTION_ALREADY_PRESENT")
        return 1
    for t in ("100","101"):
        p=run(["ip","route","show","table",t],timeout=4)
        if p is None or p.returncode!=0 or not re.search(
                r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",p.stdout):
            status("ERROR","TUN_ROUTE_MISSING")
            return 1
    status("POLICY_TABLES","MIHOMO0")
    p=run(["/usr/local/sbin/awg-transit-routing","status"],timeout=9)
    if p is None or p.returncode!=0 or not all(
            line in p.stdout.splitlines() for line in
            ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")):
        status("ERROR","TRANSIT_GUARD_NOT_SAFE")
        return 1
    status("TRANSIT_GUARD","SAFE")
    mode=(POLICY/"node-policy.mode").read_text().strip() if (POLICY/"node-policy.mode").exists() else "manual"
    if not exact_mode(mode):
        status("ERROR","INVALID_NODE_POLICY")
        return 1
    status("NODE_POLICY",mode.upper())
    current=(POLICY/"node-name").read_text().strip()
    if not current or "\n" in current:
        status("ERROR","INVALID_CURRENT_NODE")
        return 1
    if mode=="fixed":
        nodes=(POLICY/"node-policy.nodes").read_text().splitlines()
        candidates=later_nodes(current,nodes)
        verified=0
        for item in candidates:
            engine,health=get_engine(item)
            if engine=="XRAY" and health=="NETWORK_OK":
                verified+=1
        status("FIXED_FALLBACK_COUNT",len(candidates))
        status("XRAY_FIXED_NETWORK_OK",verified)
        if verified==0:
            status("LIVE_CROSS_CORE_GATE","NO_VERIFIED_FIXED_XRAY_CANDIDATE")
        else:
            status("LIVE_CROSS_CORE_GATE","CANDIDATE_PRESENT_NEEDS_OUTAGE_AUTHORIZATION")
    else:
        status("LIVE_CROSS_CORE_GATE","NO_EXPLICIT_FIXED_CHAIN")
    status("AWG_PROFILE",("CONFIGURED" if Path("/etc/amnezia/amneziawg/awg0.conf").is_file() else "ABSENT"))
    status("LAN_CLIENT_TEST","NOT_PERFORMED")
    status("REBOOT_TEST","NOT_PERFORMED")
    status("PREFLIGHT","PASS")
    return 0

if __name__=="__main__":
    sys.exit(main())
