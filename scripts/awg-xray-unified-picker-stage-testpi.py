#!/usr/bin/env python3
"""Install ONLY reviewed unified Mihomo/Xray picker menu fragments on test Pi.

Preserve stable deployed menu outside selected functions. Atomic file replace,
root-only backup; no service start/stop, route, FIXED policy or node changes.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-menu"
SOURCE_PICKER=ROOT/"src/awg-mihomo-node-picker.py"
INSTALLED=Path("/usr/local/sbin/awg-menu")
PICKER=Path("/usr/local/sbin/awg-mihomo-node-picker")
BACKUPS=Path("/var/backups/awg-gateway")
EXPECTED_INSTALLED_SHA="8e48c79c6ccb94c50672154c77bf8f67a80fca63c322d23520146e645128c568"
SELECTED=("select_tsv_node_dialog","mihomo_pool_pick","mihomo_node_menu","mihomo_menu")
NEW_MENU="mihomo_xray_vless_menu"

def log(k,v):print("XRAY_PICKER_STAGE_"+k+"="+str(v),flush=True)
def digest(b):return hashlib.sha256(b).hexdigest()

def function(source,name):
    pattern=rf"(?m)^{re.escape(name)}\(\)\{{\n"
    match=re.search(pattern,source)
    if not match:raise RuntimeError("FUNCTION_ANCHOR_MISSING")
    next_match=re.search(r"(?m)^[a-zA-Z_][\w]*\(\)\{\n",source[match.end():])
    end=match.end()+next_match.start() if next_match else len(source)
    return source[match.start():end]

def patch(previous,new):
    result=previous
    for name in SELECTED:
        old=function(result,name)
        replacement=function(new,name)
        if old==replacement:
            raise RuntimeError("OLD_FUNCTION_ALREADY_NEW")
        if result.count(old)!=1:raise RuntimeError("FUNCTION_NOT_UNIQUE")
        result=result.replace(old,replacement,1)
    if re.search(r"(?m)^"+NEW_MENU+r"\(\)\{",result):
        raise RuntimeError("XRAY_SUBMENU_PREEXISTING")
    begin=re.search(r"(?m)^mihomo_menu\(\)\{\n",result)
    if not begin:raise RuntimeError("MAIN_MIHOMO_MENU_MISSING")
    xray=function(new,NEW_MENU)
    result=result[:begin.start()]+xray+result[begin.start():]
    before='MIHOMO_UNIFIED=/usr/local/sbin/awg-mihomo-unified-nodes\n'
    after='MIHOMO_NODE_PICKER=/usr/local/sbin/awg-mihomo-node-picker\n'
    if result.count(before)!=1 or after in result:
        raise RuntimeError("PICKER_CONSTANT_UNSAFE")
    result=result.replace(before,before+after,1)
    if (result.count("MIHOMO_NODE_PICKER=")!=1 or
        result.count('if [[ "$engine" == XRAY ]]; then')!=1 or
        result.count("mihomo_xray_vless_menu(){")!=1):
        raise RuntimeError("POST_PATCH_INVALID")
    return result

def is_active(service):
    r=subprocess.run(["systemctl","is-active","--quiet",service],
          stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
    return r.returncode==0

def state():
    if not is_active("awg-mihomo.service") or is_active("awg-xray-vless.service"):
        raise RuntimeError("TRANSPORT_NOT_PASSIVE")
    if not is_active("dnsmasq.service") or not is_active("awg-selection-monitor.service"):
        raise RuntimeError("CORE_SERVICES_NOT_ACTIVE")
    values=[]
    for table in ("100","101"):
        r=subprocess.run(["ip","route","show","table",table],capture_output=True,text=True,timeout=8)
        if r.returncode!=0 or "default dev mihomo0" not in r.stdout:
            raise RuntimeError("TUN_ROUTE_MISMATCH")
        values.append(r.stdout)
    return tuple(values)

def put(path,data):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".new-")
    try:
        os.fchown(fd,0,0);os.fchmod(fd,0o755)
        with os.fdopen(fd,"wb") as fp:
            fp.write(data);fp.flush();os.fsync(fp.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)

def check():
    if socket.gethostname()!="awg-upgrade":raise RuntimeError("TEST_PI_ONLY")
    for p in (SOURCE,SOURCE_PICKER,INSTALLED):
        if not p.is_file() or p.is_symlink():raise RuntimeError("SOURCE_OR_MENU_MISSING")
    if PICKER.exists():raise RuntimeError("UNREVIEWED_EXISTING_PICKER")
    previous=INSTALLED.read_bytes()
    if digest(previous)!=EXPECTED_INSTALLED_SHA:raise RuntimeError("LIVE_MENU_UNREVIEWED_HASH")
    updated=patch(previous.decode("utf8"),SOURCE.read_text())
    with tempfile.TemporaryDirectory(prefix="awg-menu-picker-check-") as root:
        test=Path(root)/"awg-menu";test.write_text(updated)
        syntax=subprocess.run(["bash","-n",str(test)],capture_output=True,timeout=8)
        picker_syntax=subprocess.run([sys.executable,"-m","py_compile",str(SOURCE_PICKER)],
                        capture_output=True,timeout=8)
        if syntax.returncode or picker_syntax.returncode:
            raise RuntimeError("PATCH_SYNTAX_INVALID")
    return previous,updated.encode()

def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--stage",action="store_true")
    args=p.parse_args()
    try:
        original,new=check()
        before=state()
        log("PREFLIGHT","PASS")
        log("SCOPE","UNIFIED_PICKER_ONLY")
        if args.check:
            log("INSTALLED","NO");return 0
        if os.geteuid()!=0:raise RuntimeError("ROOT_REQUIRED")
        if not BACKUPS.is_dir():raise RuntimeError("BACKUP_DIRECTORY_MISSING")
        snap=Path(tempfile.mkdtemp(prefix="xray-unified-picker-",dir=BACKUPS))
        os.chmod(snap,0o700)
        (snap/"awg-menu.previous").write_bytes(original)
        os.chmod(snap/"awg-menu.previous",0o600)
        (snap/"picker.absent").write_text("not installed\n")
        try:
            put(PICKER,SOURCE_PICKER.read_bytes())
            put(INSTALLED,new)
            if (digest(INSTALLED.read_bytes())!=digest(new) or
                digest(PICKER.read_bytes())!=digest(SOURCE_PICKER.read_bytes()) or
                state()!=before):
                raise RuntimeError("POSTCHECK_MISMATCH")
        except Exception:
            put(INSTALLED,original)
            PICKER.unlink(missing_ok=True)
            raise
        log("INSTALLED","PASSIVE")
        log("BACKUP","VERIFIED")
        log("SERVICES_RESTARTED","NO")
        log("ROUTES_CHANGED","NO")
        return 0
    except Exception:
        log("ERROR","PRECHECK_OR_INSTALL_FAILED");return 1

if __name__=="__main__":
    sys.exit(main())
