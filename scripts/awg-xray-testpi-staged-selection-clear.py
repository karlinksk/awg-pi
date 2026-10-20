#!/usr/bin/env python3
"""Test-Pi-only reversible cleanup of a dormant Xray VLESS menu selection.

No changes to running transports, Mihomo configuration, FIXED, DNS, routing,
subscriptions or systemd. Copies the root-only selected.json into a restricted
backup before removing only that staged marker. Never prints its contents.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
BRIDGES=(
    Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
    Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
    Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf"),
)
LOCK=Path("/run/awg-maintenance.lock")
MODE=Path("/etc/awg-pbr/mode")
NODE=Path("/etc/awg-pbr/transports/mihomo/node-name")
CHAIN=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
BACKUPS=Path("/var/backups/awg-gateway")
XRAY="awg-xray-vless.service"
MIHOMO="awg-mihomo.service"

def emit(name,value):
    print("XRAY_STAGED_"+name+"="+str(value),flush=True)

def command(args,timeout=12):
    return subprocess.run(args,capture_output=True,text=True,
        stdin=subprocess.DEVNULL,timeout=timeout)

def require(ok,name):
    if not ok:raise RuntimeError(name)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def active(unit):
    return command(["systemctl","is-active","--quiet",unit],timeout=7).returncode==0

def read_marker():
    if not SELECTED.exists():
        return None
    require(not SELECTED.is_symlink(),"SELECTION_SYMLINK")
    parent=SELECTED.parent
    require(not parent.is_symlink() and parent.stat().st_uid==0 and
        parent.stat().st_mode & 0o077==0,"SELECTION_DIRECTORY_UNSAFE")
    info=SELECTED.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and
        info.st_mode & 0o077==0 and info.st_size<=2048,
        "SELECTION_FILE_UNSAFE")
    contents=SELECTED.read_bytes()
    try:
        body=json.loads(contents)
    except (ValueError,UnicodeError):
        raise RuntimeError("SELECTION_INVALID_JSON")
    require(isinstance(body,dict) and body.get("version")==1 and
        set(body)=={"version","sha256"} and
        isinstance(body.get("sha256"),str) and
        re.fullmatch(r"[0-9a-f]{64}",body["sha256"]) is not None,
        "SELECTION_INVALID_FORMAT")
    return contents

def healthy_state():
    require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade",
        "ROOT_TEST_PI_REQUIRED")
    require(MODE.read_text().strip()=="transit","TRANSIT_ONLY")
    require(active(MIHOMO) and active("dnsmasq.service") and
        active("awg-selection-monitor.service"),"CORE_SERVICES_INACTIVE")
    require(not active(XRAY),"XRAY_ALREADY_RUNNING")
    enabled=command(["systemctl","is-enabled",XRAY],timeout=7)
    require(enabled.stdout.strip() in ("disabled","static"),"XRAY_AUTOSTART_UNEXPECTED")
    require(not any(p.exists() or p.is_symlink() for p in BRIDGES),
        "XRAY_BRIDGE_PRESENT")
    timers=command(["systemctl","list-timers","--all","--no-pager"],timeout=9)
    require(timers.returncode==0 and
        "awg-xray-live-rollback" not in timers.stdout,
        "XRAY_ROLLBACK_TIMER_PRESENT")
    require(NODE.is_file() and CHAIN.is_file(),"FIXED_STATE_MISSING")
    g=command(["/usr/local/sbin/awg-transit-routing","status"],timeout=12)
    require(g.returncode==0 and all(line in g.stdout.splitlines() for line in
        ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
        "TRANSIT_GUARD_UNSAFE")
    routes=[]
    for table in ("100","101"):
        route=command(["ip","-4","route","show","table",table],timeout=7)
        require(route.returncode==0 and
            re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",route.stdout),
            "TUN_ROUTE_"+table+"_UNSAFE")
        routes.append(route.stdout)
    up=command(["curl","-q","-4","--noproxy","*","--interface","mihomo0",
        "--connect-timeout","7","--max-time","18","-sS","-o","/dev/null",
        "-w","%{http_code}","https://api.openai.com/v1/models"],timeout=23)
    require(up.returncode==0 and up.stdout=="401","ORIGINAL_TUN_UNHEALTHY")
    return (tuple(routes),sha(NODE.read_bytes()),sha(CHAIN.read_bytes()))

def clear():
    with LOCK.open("a") as fd:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=healthy_state()
        data=read_marker()
        emit("ORIGINAL_TRANSPORT","MIHOMO_ACTIVE")
        emit("XRAY_SERVICE","INACTIVE")
        emit("TRANSIT_GUARD","SAFE")
        emit("SELECTION_PRESENT","YES" if data is not None else "NO")
        if data is None:
            emit("RESULT","ALREADY_CLEAR")
            return
        if args.check:
            emit("RESULT","READY_FOR_SAFE_CLEAR")
            return
        require(BACKUPS.is_dir() and BACKUPS.stat().st_uid==0 and
            not BACKUPS.is_symlink(),"BACKUP_LOCATION_UNSAFE")
        snap=Path(tempfile.mkdtemp(prefix="xray-staged-selection-",dir=BACKUPS))
        snap.chmod(0o700)
        backup=snap/"selected.json"
        fdout=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fdout,"wb") as fp:
            fp.write(data);fp.flush();os.fsync(fp.fileno())
        require(sha(backup.read_bytes())==sha(data),"BACKUP_VERIFICATION_FAILED")
        try:
            require(read_marker()==data,"SELECTION_CHANGED_DURING_BACKUP")
            SELECTED.unlink()
            require(not SELECTED.exists(),"SELECTION_STILL_PRESENT")
            require(healthy_state()==before,"POSTCHECK_TRANSPORT_CHANGED")
        except Exception:
            # Recover the exact staged-only menu selection, not the route.
            fdtemp,temp=tempfile.mkstemp(prefix=".xray-selection-restore-",
                dir=SELECTED.parent)
            with os.fdopen(fdtemp,"wb") as fp:
                fp.write(data);fp.flush();os.fsync(fp.fileno())
            os.chmod(temp,0o600)
            os.replace(temp,SELECTED)
            emit("ROLLBACK","STAGED_PROFILE_RESTORED")
            raise
        emit("BACKUP","VERIFIED")
        emit("SELECTION_CLEARED","YES")
        emit("ORIGINAL_TRANSPORT_CHANGED","NO")
        emit("FIXED_POLICY_CHANGED","NO")
        emit("SERVICES_RESTARTED","NO")
        emit("ROUTING_CHANGED","NO")
        emit("RESULT","PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--clear",action="store_true")
    args=parser.parse_args()
    try:
        clear()
    except Exception as ex:
        # Do not print exception parameters (could include provider filenames).
        emit("ERROR",str(ex) if isinstance(ex,RuntimeError) else "PRECHECK_OR_RESTORE_FAILED")
        sys.exit(1)
