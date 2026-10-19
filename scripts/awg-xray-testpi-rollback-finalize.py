#!/usr/bin/env python3
"""One-shot, root-only *metadata* reconciliation after recovered Xray canary.

Never restarts services, changes routes, restores files, changes the selected
node or alters the rollback timer. Refuses to write unless the watchdog is
stopped and all independent recovery proofs agree.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import yaml

SNAP=Path("/var/backups/awg-gateway/xray-live-switch-20261019-210015")
TIMER="awg-xray-live-rollback-150820.timer"
CONFIG=Path("/etc/awg-pbr/transports/mihomo/config.yaml")
RENDERER=Path("/usr/local/sbin/awg-mihomo-config")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
OVERRIDES=(
    Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf"),
    Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
    Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
)
MODE=Path("/etc/awg-pbr/mode")

def emit(key,val):
    print("XRAY_ROLLBACK_FINALIZE_"+key+"="+str(val),flush=True)

def require(ok,code):
    if not ok:raise RuntimeError(code)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def equivalent(original,actual,expected_hash):
    if digest(original)!=expected_hash:
        return "BACKUP_CORRUPT"
    if original==actual:
        return "BYTE_IDENTICAL"
    try:
        before=yaml.safe_load(original)
        after=yaml.safe_load(actual)
        if isinstance(before,dict) and before==after:
            return "YAML_EQUIVALENT"
    except (ValueError,UnicodeDecodeError,yaml.YAMLError):
        pass
    return "CONTENT_DIFFERENT"

def command(*args,timeout=8):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL,text=True,timeout=timeout)

def is_active(unit):
    return command("systemctl","is-active","--quiet",unit).returncode==0

def live_selection():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=4) as response:
        return json.load(response).get("now")

def verify(state,original,actual):
    require(state.get("state") in ("armed","restored"),"STATE_UNEXPECTED")
    require(state.get("mode")=="transit" and MODE.read_text().strip()=="transit","MODE_CHANGED")
    proof=equivalent(original,actual,state.get("old_config_sha256"))
    require(proof in ("BYTE_IDENTICAL","YAML_EQUIVALENT"),"CONFIG_OR_BACKUP_UNSAFE")
    require(digest(RENDERER.read_bytes())==state.get("old_renderer_sha256"),"RENDERER_CHANGED")
    require(not any(p.exists() for p in OVERRIDES),"UNEXPECTED_BRIDGE_OVERRIDE")
    require(SELECTED.exists()==state.get("selection_preexisting",False),"XRAY_SELECTION_STATE")
    require(is_active("awg-mihomo.service") and not is_active("awg-xray-vless.service"),
            "MIHOMO_OR_XRAY_SERVICE_UNSAFE")
    require(is_active("dnsmasq.service") and is_active("awg-selection-monitor.service"),
            "MANAGEMENT_SERVICES_UNSAFE")
    for table in ("100","101"):
        routes=command("ip","route","show","table",table).stdout
        require(re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",routes)!=None,
                "ROUTE_NOT_MIHOMO0")
    guard=command("/usr/local/sbin/awg-transit-routing","status").stdout.splitlines()
    require(all(x in guard for x in
                ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
            "TRANSIT_GUARD_UNSAFE")
    require(live_selection()==state.get("previous_group") and state.get("previous_group"),
            "ORIGINAL_NODE_NOT_RESTORED")
    probe=command("curl","-q","-4","--noproxy","*","--interface","mihomo0",
                  "--connect-timeout","7","--max-time","18","-sS",
                  "-o","/dev/null","-w","%{http_code}",
                  "https://api.openai.com/v1/models",timeout=23)
    require(probe.returncode==0 and probe.stdout=="401","TUN_OPENAI_NOT_REACHABLE")
    return proof

def finalize():
    require(os.geteuid()==0,"ROOT_REQUIRED")
    require(command("hostname").stdout.strip()=="awg-upgrade","WRONG_TEST_HOST")
    require(not is_active(TIMER) and not is_active(TIMER.replace(".timer",".service")),
            "WATCHDOG_STILL_ACTIVE")
    require(SNAP.is_dir() and not SNAP.is_symlink(),"SNAPSHOT_UNAVAILABLE")
    with (SNAP/"state.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state_file=SNAP/"state.json"
        require(state_file.is_file() and not state_file.is_symlink(),"STATE_FILE_UNSAFE")
        state=json.loads(state_file.read_text())
        saved=SNAP/"config.previous"
        require(saved.is_file() and not saved.is_symlink(),"BACKUP_FILE_UNSAFE")
        proof=verify(state,saved.read_bytes(),CONFIG.read_bytes())
        emit("BACKUP_AND_CONFIG","PASS_"+proof)
        if state["state"]=="restored":
            emit("SNAPSHOT_STATE","ALREADY_RESTORED")
            return
        state["state"]="restored"
        state["restored_at"]=int(time.time())
        state["reconciled_from"]="RECOVERED_EQUIVALENT_LIVE_STATE"
        tmp=SNAP/(".state.json.reconciled-"+str(os.getpid()))
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            with os.fdopen(fd,"w") as fp:
                json.dump(state,fp)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp,state_file)
        finally:
            tmp.unlink(missing_ok=True)
        emit("WATCHDOG","INACTIVE")
        emit("ORIGINAL_NODE","VERIFIED")
        emit("TUN_OPENAI","HTTP_401")
        emit("SNAPSHOT_STATE","RESTORED")
        emit("NETWORK_MUTATION","NO")

def main():
    if sys.argv[1:]!=["--finalize"]:
        raise SystemExit("Usage: sudo python3 scripts/awg-xray-testpi-rollback-finalize.py --finalize")
    try:
        finalize()
        return 0
    except Exception:
        # Internal errors can accidentally print config paths/names. Redact.
        emit("ERROR","RECONCILIATION_PRECHECK_FAILED")
        return 1

if __name__=="__main__":
    raise SystemExit(main())
