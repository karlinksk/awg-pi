#!/usr/bin/env python3
"""Safely deploy only the engine-aware results screen to the AWG test Pi.

Does NOT update the broader experimental menu, change the selected node,
restart Mihomo, start Xray, alter routing, refresh a provider, or run probes.
Both modes work from committed source; --stage needs root on awg-upgrade.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE_MENU=ROOT/"src/awg-menu"
SOURCE_VIEW=ROOT/"src/awg-mihomo-results-view.py"
LIVE_MENU=Path("/usr/local/sbin/awg-menu")
LIVE_VIEW=Path("/usr/local/sbin/awg-mihomo-results-view")
BACKUPS=Path("/var/backups/awg-gateway")
BASELINE_MENU_SHA="332e27ccf5bcf1ce57ba44f36d2c38735a08080bb59a46bccacc4583de6008b5"
ASSIGNMENT="MIHOMO_POOL=/usr/local/sbin/awg-mihomo-pool\n"
EXTRA=(
    "MIHOMO_RESULTS_VIEW=/usr/local/sbin/awg-mihomo-results-view\n"
    "MIHOMO_UNIFIED=/usr/local/sbin/awg-mihomo-unified-nodes\n"
)
ORIGINAL_ACTION='        title="Проверка узлов Mihomo"\n        capture "$MIHOMO_POOL" scan "$target" --geo-if-policy || true'

def emit(k,v):
    print("XRAY_UI_STAGE_"+k+"="+str(v),flush=True)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def between(text,beg,end):
    a=text.index(beg)
    b=text.index(end,a)
    return text[a:b]

def extract_line(content,token):
    lines=[x for x in content.splitlines(keepends=True)
           if x.startswith(token)]
    if len(lines)!=1:raise ValueError("expected unique UI help line")
    return lines[0]

def patched_menu(original,source):
    if original==source:
        return original
    marker="mihomo_pool_results_dialog(){\n"
    closing="\nselect_tsv_node_dialog(){"
    ours=between(source,marker,closing)
    if ("$MIHOMO_RESULTS_VIEW" not in ours
        or 'probe-vless-all' not in source):
        raise ValueError("unreviewed new source")
    if EXTRA in original:
        # Already patched, possibly from an older revision. Refuse instead
        # of layering patches over unreviewed versions.
        raise ValueError("other installed UI variant")
    if original.count(ASSIGNMENT)!=1 or original.count(ORIGINAL_ACTION)!=1:
        raise ValueError("unreviewed installed menu")
    new=original.replace(ASSIGNMENT,ASSIGNMENT+EXTRA,1)
    new=new.replace(between(new,marker,closing),ours,1)
    needle='      4 "Обновить проверку сейчас"'
    other='      6 "Показать все результаты"'
    for token in (needle,other):
        old=extract_line(new,token)
        fresh=extract_line(source,token)
        if old==fresh:raise ValueError("old menu unexpectedly already modified")
        new=new.replace(old,fresh,1)
    fresh=between(source,'        title="Проверка узлов Mihomo"\n',
                  '\n        ;;\n      5)')
    if ORIGINAL_ACTION not in new or 'probe-vless-all' not in fresh:
        raise ValueError("unexpected scan action")
    new=new.replace(ORIGINAL_ACTION,fresh.rstrip("\n"),1)
    if new.count('MIHOMO_RESULTS_VIEW=')!=1 or new.count('probe-vless-all')!=1:
        raise ValueError("unsafe composite patch")
    return new

def check_current():
    if socket.gethostname()!="awg-upgrade":
        raise RuntimeError("TEST_PI_ONLY")
    if not all(p.is_file() and not p.is_symlink()
               for p in (SOURCE_MENU,SOURCE_VIEW,LIVE_MENU)):
        raise RuntimeError("SOURCE_OR_MENU_MISSING")
    source=SOURCE_MENU.read_text()
    old=LIVE_MENU.read_text()
    if EXTRA in old:
        # For a completed installation check patch equality via source
        # markers, not an exact old baseline checksum.
        if 'probe-vless-all' not in old or '$MIHOMO_RESULTS_VIEW' not in old:
            raise RuntimeError("UNREVIEWED_ALREADY_PATCHED")
        if not LIVE_VIEW.is_file() or sha(LIVE_VIEW.read_bytes())!=sha(SOURCE_VIEW.read_bytes()):
            raise RuntimeError("VIEW_NOT_INSTALLED_OR_MISMATCH")
        return old,"ALREADY_INSTALLED"
    if sha(old.encode())!=BASELINE_MENU_SHA:
        raise RuntimeError("UNREVIEWED_MENU_HASH")
    newer=patched_menu(old,source)
    with tempfile.TemporaryDirectory(prefix="awg-xray-ui-check-",dir="/tmp") as td:
        path=Path(td)/"awg-menu"
        path.write_text(newer)
        p=subprocess.run(["bash","-n",str(path)],stdin=subprocess.DEVNULL,
             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
        if p.returncode:raise RuntimeError("PATCH_BASH_SYNTAX")
        p=subprocess.run([sys.executable,"-m","py_compile",str(SOURCE_VIEW)],
             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
             stderr=subprocess.DEVNULL,timeout=8)
        if p.returncode:raise RuntimeError("VIEW_PYTHON_SYNTAX")
    return newer,"READY"

def safe_state():
    def status(unit):
        q=subprocess.run(["systemctl","is-active",unit],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=5)
        return q.stdout.strip()
    if (status("awg-mihomo.service")!="active" or
        status("dnsmasq.service")!="active" or
        status("awg-xray-vless.service")=="active"):
        raise RuntimeError("TRANSPORT_STATE_NOT_PASSIVE")
    return tuple(subprocess.run(["ip","route","show","table",x],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,timeout=6).stdout for x in ("100","101"))

def put(path,data):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".stage-")
    try:
        os.fchmod(fd,0o755)
        os.fchown(fd,0,0)
        with os.fdopen(fd,"wb") as fp:
            fp.write(data);fp.flush();os.fsync(fp.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)

def run(mode):
    newer,status=check_current()
    before=safe_state()
    emit("PREFLIGHT","PASS")
    emit("MENU_PATCH","ONLY_RESULTS_VIEW")
    if mode=="--check":
        emit("INSTALLED","YES" if status=="ALREADY_INSTALLED" else "NO")
        return
    if os.geteuid()!=0:
        raise RuntimeError("ROOT_REQUIRED")
    if status=="ALREADY_INSTALLED":
        emit("INSTALLED","ALREADY")
        return
    if LIVE_VIEW.exists():
        raise RuntimeError("UNREVIEWED_EXISTING_VIEW")
    snapshot=Path(tempfile.mkdtemp(prefix="mihomo-xray-ui-",dir=BACKUPS))
    os.chmod(snapshot,0o700)
    old=LIVE_MENU.read_bytes()
    (snapshot/"awg-menu.previous").write_bytes(old)
    os.chmod(snapshot/"awg-menu.previous",0o600)
    (snapshot/"view.absent").write_text("absent\n")
    try:
        put(LIVE_VIEW,SOURCE_VIEW.read_bytes())
        put(LIVE_MENU,newer.encode())
        if (sha(LIVE_MENU.read_bytes())!=sha(newer.encode())
             or sha(LIVE_VIEW.read_bytes())!=sha(SOURCE_VIEW.read_bytes())
             or safe_state()!=before):
            raise RuntimeError("POSTCHECK_CHANGED")
    except Exception:
        put(LIVE_MENU,old)
        LIVE_VIEW.unlink(missing_ok=True)
        raise
    emit("INSTALLED","PASSIVE")
    emit("BACKUP","VERIFIED")
    emit("SERVICES_RESTARTED","NO")
    emit("ROUTES_CHANGED","NO")

def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--stage",action="store_true")
    args=parser.parse_args()
    try:
        run("--stage" if args.stage else "--check")
    except Exception:
        emit("ERROR","PRECHECK_OR_INSTALL_FAILED")
        return 1
    return 0

if __name__=="__main__":
    sys.exit(main())
