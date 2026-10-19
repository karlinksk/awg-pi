#!/usr/bin/env python3
"""Append ONE fresh Xray Reality candidate AFTER the existing FIXED fallbacks.

Root-only on test Pi, opt-in command. No currently selected node, service, DNS,
network route, user router, Hot Pool or READY mode is modified. Installed
node-policy must already be byte-identical to cross-core-protected source.
No names, addresses, credentials or subscription links are printed.
"""
import fcntl
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
ROOT_POLICY=Path("/usr/local/sbin/awg-mihomo-node-policy")
SOURCE_POLICY=ROOT/"src"/"awg-mihomo-node-policy"
RESOLVER=Path("/usr/local/sbin/awg-mihomo-unified-nodes")
MODE=Path("/etc/awg-pbr/mode")
POLICY_MODE=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
POLICY_CHAIN=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
LOCK=Path("/run/awg-maintenance.lock")
BACKUPS=Path("/var/backups/awg-gateway")
XRAY_SELECTION=Path("/var/lib/awg-pbr/xray-vless/selected.json")
BRIDGE=Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")

def say(k,v):
    print("XRAY_FIXED_"+k+"="+str(v),flush=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def call(*cmd,timeout=8):
    result=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,text=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError("PRECHECK_SUBPROCESS_FAILED")
    return result.stdout

def check_policy(current,chain):
    return (current in chain and len(chain)>=3 and len(chain)==len(set(chain)) and
            all(isinstance(x,str) and x and "\n" not in x and "\r" not in x for x in chain))

def load_candidates():
    spec=importlib.util.spec_from_loader("safe_xray_fixed_inventory",
        SourceFileLoader("safe_xray_fixed_inventory",str(RESOLVER)))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter=module.load_adapter()
    nodes,provider_hash,pool,cache=module.snapshots(adapter)
    rows=module.inventory(nodes,pool,cache,adapter)
    return rows,provider_hash,adapter,module

def write_chain_atomic(path,names):
    data=("".join(n+"\n" for n in names)).encode()
    fd,tmp=tempfile.mkstemp(prefix=".node-policy-nodes-xray-",dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def execute(append):
    if os.geteuid()!=0 or socket.gethostname()!="awg-upgrade":
        raise RuntimeError("ROOT_TEST_PI_REQUIRED")
    if MODE.read_text().strip()!="transit" or POLICY_MODE.read_text().strip()!="fixed":
        raise RuntimeError("TRANSIT_FIXED_REQUIRED")
    if BRIDGE.exists() or XRAY_SELECTION.exists():
        raise RuntimeError("XRAY_ALREADY_SELECTED")
    if not ROOT_POLICY.is_file() or ROOT_POLICY.is_symlink() or sha(ROOT_POLICY)!=sha(SOURCE_POLICY):
        raise RuntimeError("CROSS_CORE_POLICY_GUARD_NOT_INSTALLED")
    if not RESOLVER.is_file() or RESOLVER.is_symlink():
        raise RuntimeError("RESOLVER_NOT_INSTALLED")
    if not POLICY_CHAIN.is_file() or POLICY_CHAIN.is_symlink():
        raise RuntimeError("UNSAFE_FIXED_POLICY_FILE")
    with LOCK.open("a") as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if call("systemctl","is-active","awg-mihomo.service").strip()!="active":
            raise RuntimeError("MIHOMO_NOT_ACTIVE")
        sidecar=subprocess.run(["systemctl","is-active","--quiet","awg-xray-vless.service"],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if sidecar.returncode==0:raise RuntimeError("XRAY_ALREADY_ACTIVE")
        guard=call("/usr/local/sbin/awg-transit-routing","status")
        required=("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")
        if not all(line in guard.splitlines() for line in required):
            raise RuntimeError("TRANSIT_GUARD_NOT_SAFE")
        for table in ("100","101"):
            if not re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",
                             call("ip","route","show","table",table)):
                raise RuntimeError("TUN_ROUTING_NOT_SAFE")
        mode_before=sha(POLICY_MODE)
        current_before=sha(CURRENT)
        policy_before=sha(POLICY_CHAIN)
        old=CURRENT.read_text().strip()
        chain=POLICY_CHAIN.read_text().splitlines()
        if not check_policy(old,chain):raise RuntimeError("INVALID_CURRENT_FIXED_ORDER")
        rows,provider_sha,adapter,module=load_candidates()
        candidates=[x for x in rows if x["engine"]=="XRAY" and
                    x["basic_network"]=="NETWORK_OK" and isinstance(x["name"],str) and
                    x["name"] and not any(c in x["name"] for c in (chr(10),chr(13),chr(9))) and
                    x["name"] not in chain]
        say("CURRENT_FALLBACKS",len(chain)-chain.index(old)-1)
        say("ELIGIBLE_XRAY_CANDIDATES",len(candidates))
        if not candidates:
            raise RuntimeError("NO_FRESH_OUT_OF_CHAIN_XRAY_NETWORK_OK")
        choice=candidates[0]
        say("CHOSEN_PROVIDER_INDEX",choice["index"])
        say("CANDIDATE_BASIC_NETWORK","NETWORK_OK")
        if not append:
            say("FIXED_CHANGED","NO")
            say("PREVIEW","PASS")
            return
        # Recompute fingerprints against same root-owned provider immediately
        # before atomic update; never depend on a stale list index.
        if hashlib.sha256(adapter.secure_read(module.PROVIDER)).hexdigest()!=provider_sha:
            raise RuntimeError("PROVIDER_ROTATED_DURING_SELECTION")
        if sha(POLICY_MODE)!=mode_before or sha(CURRENT)!=current_before or sha(POLICY_CHAIN)!=policy_before:
            raise RuntimeError("FIXED_STATE_ROTATED_DURING_SELECTION")
        os.makedirs(BACKUPS,mode=0o700,exist_ok=True)
        backup=Path(tempfile.mkdtemp(prefix="xray-fixed-append-",dir=BACKUPS))
        os.chmod(backup,0o700)
        shutil.copy2(POLICY_CHAIN,backup/"node-policy.nodes")
        os.chmod(backup/"node-policy.nodes",0o600)
        try:
            write_chain_atomic(POLICY_CHAIN,chain+[choice["name"]])
            if (sha(CURRENT)!=current_before or sha(POLICY_MODE)!=mode_before or
                POLICY_CHAIN.read_text().splitlines()!=chain+[choice["name"]]):
                raise RuntimeError("FIXED_POSTCHECK_MISMATCH")
            if call("systemctl","is-active","awg-mihomo.service").strip()!="active":
                raise RuntimeError("MIHOMO_INACTIVE_AFTER_APPEND")
        except Exception:
            write_chain_atomic(POLICY_CHAIN,chain)
            raise
        say("FIXED_CHANGED","APPENDED_DORMANT_XRAY")
        say("OLD_FALLBACKS_PRESERVED","YES")
        say("CURRENT_SELECTED_CHANGED","NO")
        say("LIVE_SERVICE_SWITCHED","NO")
        say("SNAPSHOT_FILES","VERIFIED")

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ("--preview","--append"):
        raise SystemExit("Usage: sudo python3 scripts/awg-xray-testpi-fixed-append.py --preview|--append")
    try:
        execute(append=sys.argv[1]=="--append")
    except Exception as e:
        say("ERROR",str(e) if isinstance(e,RuntimeError) else "PRECHECK_OR_APPLY_FAILED")
        return 1
    return 0
if __name__=="__main__":
    sys.exit(main())
