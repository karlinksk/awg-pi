#!/usr/bin/env python3
"""TEST-PI ONLY: guarded installation of dormant Xray bridge in live Mihomo.

No Xray selection, no provider mutation, no MikroTik changes.
Explicit apply starts an independently scheduled recovery before restarting
the active Mihomo TUN. This is a hardware test helper, NOT release PASS.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HOST="awg-upgrade"
CONF=Path("/etc/awg-pbr/transports/mihomo/config.yaml")
RENDER=Path("/usr/local/sbin/awg-mihomo-config")
MIHOMO=Path("/usr/local/bin/mihomo")
INSTALL=Path("/usr/local/sbin/awg-xray-bridge-reload-test")
BASE=Path("/var/backups/awg-gateway")
LOCK=Path("/run/awg-maintenance.lock")
TRANSPORT=Path("/etc/awg-pbr/transport")
MODE=Path("/etc/awg-pbr/mode")
SELECTED=Path("/etc/awg-pbr/transports/mihomo/node-name")
ALIAS="AWG-XRAY-VLESS-LOCAL"
SERVICE="awg-mihomo.service"
WATCH=150

def die(code):
    raise RuntimeError(code)

def run(*args,timeout=25,output=True):
    r=subprocess.run(list(map(str,args)),stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if output else subprocess.DEVNULL,
        stderr=subprocess.PIPE,timeout=timeout,text=True)
    if r.returncode!=0:
        die("COMMAND_FAILED_"+Path(str(args[0])).name)
    return r.stdout.strip() if output else ""

def active(unit):
    return subprocess.run(["systemctl","is-active","--quiet",unit],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode==0

def ctl():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=4) as r:
        return json.load(r)

def choose(node):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO",
          data=json.dumps({"name":node}).encode(),method="PUT",
          headers={"Content-Type":"application/json"})
    with opener.open(req,timeout=5) as r:
        if r.status not in (200,204):die("SELECT_FAILED")
    if ctl().get("now")!=node:die("SELECT_MISMATCH")

def guard():
    if MODE.read_text().strip()=="transit":
        output=run("/usr/local/sbin/awg-transit-routing","status")
        for key in ("Transit guard: SAFE","Transit policy rule: ACTIVE",
                    "Transit VPN table: READY"):
            if key not in output:die("TRANSIT_POLICY_NOT_RESTORED")
    else:
        if MODE.read_text().strip()!="selective":die("INVALID_MODE")
    rules=run("ip","-4","rule","show")
    if not re.search(r"fwmark\s+0x100(?:/0xffffffff)?\s+lookup\s+100\b",rules):
        die("ROUTING_RULE_NOT_ACTIVE")
    for table in ("100","101"):
        routes=run("ip","-4","route","show","table",table)
        if "default dev mihomo0" not in routes:die("TUN_ROUTE_NOT_RESTORED")

def https_ok():
    # Basic TUN HTTPS only. Does not run READY media or LAN tests.
    try:
        r=subprocess.run(["curl","-q","-4","-sS","--interface","mihomo0",
            "--noproxy","*","--connect-timeout","7","--max-time","17",
            "-o","/dev/null","-w","%{http_code}",
            "https://api.openai.com/v1/models"],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,timeout=21)
        return r.returncode==0 and r.stdout.strip()=="401"
    except (OSError,subprocess.TimeoutExpired):
        return False

def sanity():
    if os.geteuid()!=0:die("ROOT_REQUIRED")
    if socket.gethostname().split(".")[0]!=HOST:die("WRONG_HOST")
    if TRANSPORT.read_text().strip()!="mihomo":die("ACTIVE_TRANSPORT_CHANGED")
    for unit in (SERVICE,"ssh.service","dnsmasq.service",
                 "awg-pbr-health.service","awg-selection-monitor.service"):
        if not active(unit):die("CRITICAL_SERVICE_DOWN")
    if not CONF.is_file() or CONF.is_symlink():die("INVALID_ACTIVE_CONFIG")
    if not SELECTED.is_file():die("CURRENT_NODE_MISSING")
    if not INSTALL.is_file() or not os.access(INSTALL,os.X_OK):
        die("WATCHDOG_EXECUTOR_MISSING")
    guard()
    details=ctl()
    name=details.get("now")
    if not isinstance(name,str) or not name or name==ALIAS:
        die("PREVIOUS_NODE_INVALID")
    if name!=SELECTED.read_text().strip():
        die("SELECTOR_AND_SAVED_NODE_DIFFER")
    if ALIAS in details.get("all",[]):
        die("ALIAS_ALREADY_ACTIVE")
    if not https_ok():die("CURRENT_TUN_HTTPS_NOT_PROVEN")
    return name

def make_config(folder):
    new=folder/"new.yaml"
    with new.open("wb") as fh:
        proc=subprocess.run([str(RENDER)],stdin=subprocess.DEVNULL,
            stdout=fh,stderr=subprocess.DEVNULL,timeout=15)
    if proc.returncode:die("RENDER_FAILED")
    run(str(MIHOMO),"-t","-d","/var/lib/awg-pbr/mihomo","-f",str(new),timeout=20,output=False)
    # Parse only to confirm group alias+non-alias default; do not log profile.
    import yaml
    config=yaml.safe_load(new.read_bytes())
    choices=[g for g in config.get("proxy-groups",[])
             if g.get("name")=="AWG-MIHOMO"]
    if len(choices)!=1:die("PROXY_GROUP_AMBIGUOUS")
    group=choices[0]
    if ALIAS not in group.get("proxies",[]):die("ALIAS_NOT_STAGED")
    if group.get("default-selected")==ALIAS:die("ALIAS_DEFAULT_UNSAFE")
    if group.get("default-selected")!=SELECTED.read_text().strip():
        die("PREVIOUS_NODE_DEFAULT_MISMATCH")
    return new

def stable_snapshot():
    BASE.mkdir(mode=0o700,exist_ok=True)
    path=BASE/("xray-bridge-"+str(int(time.time()))+"-"+str(os.getpid()))
    path.mkdir(mode=0o700)
    if BASE.is_symlink():die("BACKUP_DIRECTORY_UNTRUSTED")
    return path

def put(path,content):
    fd,temp=tempfile.mkstemp(prefix=".bridge-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def save_state(folder,info):
    put(folder/"state.json",json.dumps(info).encode())

def read_state(folder):
    return json.loads((folder/"state.json").read_text())

def wait_ready(name,alias):
    for _ in range(28):
        if not active(SERVICE):
            time.sleep(1);continue
        try:
            v=ctl()
            if (v.get("now")!=name and
                name in v.get("all",[]) and not alias):
                choose(name)
                v=ctl()
            if v.get("now")!=name:
                time.sleep(1);continue
            if bool(ALIAS in v.get("all",[]))!=alias:
                time.sleep(1);continue
            guard()
            if https_ok():return
        except (OSError,ValueError,RuntimeError):
            pass
        time.sleep(1)
    die("LIVE_MIHOMO_TUN_OR_GUARD_UNVERIFIED")

def restore(folder,state):
    if TRANSPORT.read_text().strip()!="mihomo":die("FOREIGN_TRANSPORT_ABORT_RECOVERY")
    if MODE.read_text().strip()!=state["mode"]:die("FOREIGN_MODE_ABORT_RECOVERY")
    if CONF.is_symlink():die("CONFIG_SYMLINK_UNSAFE")
    put(CONF,(folder/"original.yaml").read_bytes())
    run("systemctl","restart",SERVICE,timeout=45,output=False)
    wait_ready(state["previous"],False)
    print("XRAY_BRIDGE_ROLLBACK=VERIFIED")

def recover(folder):
    if not re.fullmatch(r"xray-bridge-[0-9]+-[0-9]+",folder.name):
        die("UNTRUSTED_SNAPSHOT")
    if folder.parent!=BASE or folder.is_symlink() or folder.stat().st_uid!=0:
        die("UNTRUSTED_SNAPSHOT")
    with LOCK.open("a+") as fh:
        fcntl.flock(fh,fcntl.LOCK_EX)
        state=read_state(folder)
        if state["phase"] in ("committed","restored","cancelled"):return
        if state["phase"]=="pending":
            state["phase"]="cancelled";save_state(folder,state);return
        restore(folder,state)
        state["phase"]="restored";save_state(folder,state)

def do_apply():
    with LOCK.open("a+") as fh:
        fcntl.flock(fh,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=sanity()
        folder=stable_snapshot()
        put(folder/"original.yaml",CONF.read_bytes())
        candidate=make_config(folder)
        if hashlib.sha256(candidate.read_bytes()).digest()==hashlib.sha256(CONF.read_bytes()).digest():
            die("CONFIG_UNCHANGED")
        state={"phase":"pending","previous":previous,
               "mode":MODE.read_text().strip(),
               "watch":"awg-xray-bridge-"+str(os.getpid())}
        save_state(folder,state)
        timer=state["watch"]+".timer"
        try:
            run("systemd-run","--unit="+state["watch"],
                "--on-active="+str(WATCH)+"s",
                str(INSTALL),"recover",str(folder),timeout=12,output=False)
            if not active(timer):die("AUTONOMOUS_WATCHDOG_NOT_ARMED")
            state["phase"]="armed";save_state(folder,state)
            if TRANSPORT.read_text().strip()!="mihomo" or ctl().get("now")!=previous:
                die("PREVIOUS_NODE_CHANGED")
            put(CONF,candidate.read_bytes())
            run("systemctl","restart",SERVICE,timeout=50,output=False)
            wait_ready(previous,True)
            state["phase"]="committed";save_state(folder,state)
            run("systemctl","stop",timer,timeout=10,output=False)
            print("XRAY_BRIDGE_LIVE=PASS")
            print("PREVIOUS_NODE=UNCHANGED")
            print("TRANSIT_GUARD=VERIFIED")
            print("XRAY_TUN_SWITCH=NOT_TESTED")
            print("LAN_CLIENT=NOT_TESTED")
            print("REBOOT=NOT_TESTED")
            print("SNAPSHOT="+str(folder))
        except Exception:
            try:
                restore(folder,state)
                state["phase"]="restored";save_state(folder,state)
                run("systemctl","stop",timer,timeout=10,output=False)
            except Exception:
                print("XRAY_BRIDGE_AUTONOMOUS_RECOVERY=ARMED_OR_REQUIRES_INSPECTION",
                      file=sys.stderr)
                raise RuntimeError("IMMEDIATE_ROLLBACK_NOT_CONFIRMED")
            raise

def main():
    if len(sys.argv)==2 and sys.argv[1]=="preflight":
        # Run in /dev/shm and discard all provider/config copies afterward.
        with tempfile.TemporaryDirectory(prefix="awg-bridge-preflight-",dir="/dev/shm") as d:
            previous=sanity()
            make_config(Path(d))
            print("BRIDGE_RELOAD_PREFLIGHT=PASS")
            print("ACTIVE_NATIVE_NODE=HEALTHY")
            print("TRANSIT_GUARD=SAFE")
            print("RESTART=NOT_STARTED")
        return
    if len(sys.argv)==2 and sys.argv[1]=="apply":
        do_apply();return
    if len(sys.argv)==3 and sys.argv[1]=="recover":
        recover(Path(sys.argv[2]));return
    raise SystemExit("Usage: awg-xray-bridge-reload-test preflight|apply|recover SNAPSHOT")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        # Do not print node names, credentials or provider URLs.
        print("XRAY_BRIDGE_ERROR="+str(exc),file=sys.stderr)
        raise SystemExit(2)
