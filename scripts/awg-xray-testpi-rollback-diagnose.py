#!/usr/bin/env python3
"""Root-only read-only diagnostic for a single failed Xray healthy-node canary.

Never prints VPN profiles, YAML values, node names, keys, tokens, IP addresses
or subscription URLs. Requires the independent rollback timer to be stopped.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path("/var/backups/awg-gateway")
CONF=Path("/etc/awg-pbr/transports/mihomo/config.yaml")
RENDERER=Path("/usr/local/sbin/awg-mihomo-config")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
OVERRIDE=Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf")
RUNTIME_BRIDGE=Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
PERSISTENT_BRIDGE=Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
TIMER="awg-xray-live-rollback-150820.timer"
SNAP=ROOT/"xray-live-switch-20261019-210015"

def out(key,value):
    print("XRAY_ROLLBACK_AUDIT_"+key+"="+str(value),flush=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if os.geteuid()!=0 or sys.argv[1:]!=["--check"]:
        out("ERROR","ROOT_AND_CHECK_REQUIRED");return 2
    p=subprocess.run(["systemctl","is-active","--quiet",TIMER],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
    if p.returncode==0:
        out("ERROR","STOP_WATCHDOG_TIMER_FIRST");return 2
    if not SNAP.is_dir() or SNAP.is_symlink():
        out("ERROR","SNAPSHOT_NOT_FOUND");return 2
    state=json.loads((SNAP/"state.json").read_text())
    if state.get("state") not in ("armed","restored"):
        out("ERROR","UNEXPECTED_SNAPSHOT_STATE");return 2
    saved=SNAP/"config.previous"
    if not saved.is_file() or not CONF.is_file():
        out("ERROR","CONFIG_FILE_MISSING");return 2
    out("WATCHDOG_TIMER","INACTIVE")
    out("SNAPSHOT_STATE",state.get("state").upper())
    out("BACKUP_CONFIG_INTEGRITY","PASS" if sha(saved)==state.get("old_config_sha256") else "FAIL")
    out("CURRENT_CONFIG_HASH_MATCH","YES" if sha(saved)==sha(CONF) else "NO")
    try:
        original=yaml.safe_load(saved.read_text())
        current=yaml.safe_load(CONF.read_text())
        if not isinstance(original,dict) or not isinstance(current,dict):
            raise ValueError("configuration not mapping")
        out("CONFIG_YAML_EQUIVALENT","YES" if original==current else "NO")
        out("DIFF_TOP_LEVEL_COUNT",len({*original,*current} - {key for key in {*original,*current} if original.get(key)==current.get(key)}))
        # Never print keys: unusual provider names could themselves be sensitive.
    except Exception:
        out("CONFIG_YAML_EQUIVALENT","UNKNOWN")
    out("RENDERER_MATCH","YES" if sha(RENDERER)==state.get("old_renderer_sha256") else "NO")
    out("CANARY_OVERRIDE_PRESENT","YES" if OVERRIDE.exists() else "NO")
    out("CROSS_CORE_OVERRIDE_PRESENT","YES" if RUNTIME_BRIDGE.exists() or PERSISTENT_BRIDGE.exists() else "NO")
    out("XRAY_SELECTION_PRESENT","YES" if SELECTED.exists() else "NO")
    for service,label in (("awg-mihomo.service","MIHOMO"),("awg-xray-vless.service","XRAY"),
                          ("dnsmasq.service","DNS"),("awg-selection-monitor.service","MONITOR")):
        p=subprocess.run(["systemctl","is-active",service],stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,text=True,timeout=6)
        out(label,p.stdout.strip().upper())
    for table in ("100","101"):
        p=subprocess.run(["ip","route","show","table",table],stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL,text=True,timeout=6)
        out("TABLE_"+table,"MIHOMO0" if "default dev mihomo0" in p.stdout else "UNEXPECTED")
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=4) as response:
            live=json.load(response).get("now")
        out("ORIGINAL_SELECTION_MATCH","YES" if live==state.get("previous_group") else "NO")
    except Exception:
        out("ORIGINAL_SELECTION_MATCH","UNKNOWN")
    out("CHANGES_MADE","NO")
    return 0
if __name__=="__main__":
    sys.exit(main())
