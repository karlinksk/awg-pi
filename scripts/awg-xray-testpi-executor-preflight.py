#!/usr/bin/env python3
"""Preflight-only test-Pi HY2 -> dormant Xray bridge readiness.

Zero network service or policy mutations. Uses root-owned real provider,
last FIXED candidate and a temporary selected profile in /dev/shm. Never
outputs subscription URI, node name, IP, UUID, public key, or YAML.
"""
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import yaml

ROOT=Path(__file__).resolve().parents[1]
BACKEND_SOURCE=ROOT/"src/awg-xray-live-backend.py"
BACKEND_LIVE=Path("/usr/local/sbin/awg-xray-live-backend")
RENDERER=Path("/usr/local/sbin/awg-mihomo-config")
MIHOMO_BIN=Path("/usr/local/bin/mihomo")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
FIXED=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
GROUP="AWG-MIHOMO"
LOCAL="AWG-XRAY-VLESS-LOCAL"

def result(k,value):
    print("XRAY_EXEC_PREFLIGHT_"+k+"="+str(value),flush=True)

def read_chain():
    current=CURRENT.read_text().strip()
    nodes=FIXED.read_text().splitlines()
    if len(nodes)<4 or current not in nodes or len(set(nodes))!=len(nodes):
        raise RuntimeError("UNSAFE_FIXED_CHAIN")
    if nodes.index(current)>=len(nodes)-1:
        raise RuntimeError("NO_LATER_FIXED_CANDIDATE")
    return current,nodes[-1]

def load_backend():
    spec=importlib.util.spec_from_loader("xray_real_backend_preflight",
        SourceFileLoader("xray_real_backend_preflight",str(BACKEND_LIVE)))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def check():
    if os.geteuid()!=0 or socket.gethostname()!="awg-upgrade":
        raise RuntimeError("ROOT_TEST_PI_ONLY")
    if not BACKEND_LIVE.is_file() or BACKEND_LIVE.is_symlink():
        raise RuntimeError("BACKEND_NOT_INSTALLED")
    src_sha=hashlib.sha256(BACKEND_SOURCE.read_bytes()).hexdigest()
    live_sha=hashlib.sha256(BACKEND_LIVE.read_bytes()).hexdigest()
    if src_sha!=live_sha:
        raise RuntimeError("BACKEND_UPDATE_REQUIRED")
    if b"--on-active=300s" not in BACKEND_LIVE.read_bytes():
        raise RuntimeError("WATCHDOG_RUNTIME_STILL_180_SECONDS")
    result("SOURCE","INSTALLED_HASH_MATCH")
    failed,candidate=read_chain()
    backend=load_backend()
    impl=backend.LinuxBackend(failed,candidate)
    # preflight checks the exact profile, resolved index, fresh NETWORK_OK
    # proof, current transport, TUN route tables and Transit nft guard.
    impl.preflight(failed,candidate)
    result("PROVIDER_IDENTITY","CURRENT")
    result("EXACT_XRAY_PROFILE","VALID")
    result("TRANSIT_GUARD","SAFE")
    result("BASIC_NETWORK","NETWORK_OK")
    result("WATCHDOG_BUDGET_SECONDS",300)

    if not RENDERER.is_file() or not MIHOMO_BIN.is_file():
        raise RuntimeError("MISSING_MIHOMO_DEPENDENCIES")
    # Simulate the real bridge environment without writing selected.json or
    # any systemd drop-in. The temp identity has no raw VLESS credentials.
    with tempfile.TemporaryDirectory(prefix="awg-xray-preflight-",dir="/dev/shm") as directory:
        temp=Path(directory)
        temp.chmod(0o700)
        marker=temp/"selected.json"
        marker.write_text(json.dumps({"version":1,"sha256":impl.fingerprint}))
        marker.chmod(0o600)
        env=os.environ.copy()
        env["MIHOMO_XRAY_VLESS_BRIDGE"]="1"
        env["MIHOMO_XRAY_SELECTED"]=str(marker)
        render=subprocess.run([str(RENDERER)],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,
            timeout=15,env=env)
        if render.returncode:
            raise RuntimeError("BRIDGE_RENDER_FAILED")
        try:
            config=yaml.safe_load(render.stdout)
        except yaml.YAMLError:
            raise RuntimeError("BRIDGE_RENDER_NOT_YAML")
        if not isinstance(config,dict):
            raise RuntimeError("BRIDGE_RENDER_NOT_MAPPING")
        proxies=config.get("proxies")
        groups=config.get("proxy-groups")
        if (not isinstance(proxies,list) or
            not any(isinstance(item,dict) and item.get("name")==LOCAL
                    and item.get("type")=="socks5" and item.get("server")=="127.0.0.1"
                    for item in proxies) or not isinstance(groups,list) or
            not any(isinstance(item,dict) and item.get("name")==GROUP
                    and LOCAL in item.get("proxies",[]) for item in groups)):
            raise RuntimeError("XRAY_BRIDGE_NOT_IN_MIHOMO_GROUP")
        path=temp/"mihomo.yaml"
        path.write_text(render.stdout)
        path.chmod(0o600)
        test=subprocess.run([str(MIHOMO_BIN),"-t",
            "-d","/var/lib/awg-pbr/mihomo","-f",str(path)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,timeout=35)
        if test.returncode:
            raise RuntimeError("MIHOMO_BRIDGE_CONFIG_REJECTED")
    result("BRIDGE_CONFIG","MIHOMO_VALID")
    result("SERVICE_RESTARTED","NO")
    result("ROUTING_CHANGED","NO")
    result("REAL_TUN_TEST","NOT_PERFORMED")
    result("LAN_TEST","NOT_PERFORMED")
    result("WATCHDOG_TRIGGER_TEST","NOT_PERFORMED")
    result("PREFLIGHT","PASS")

def main():
    if sys.argv[1:]!=["--check"]:
        raise SystemExit("Usage: sudo python3 scripts/awg-xray-testpi-executor-preflight.py --check")
    try:check()
    except Exception as e:
        # Do not echo raw exceptions from YAML/provider/library: can include secrets.
        reason=str(e) if isinstance(e,RuntimeError) else "UNEXPECTED_CHECK_ERROR"
        if reason not in {
            "ROOT_TEST_PI_ONLY","BACKEND_NOT_INSTALLED","BACKEND_UPDATE_REQUIRED",
            "WATCHDOG_RUNTIME_STILL_180_SECONDS","UNSAFE_FIXED_CHAIN",
            "NO_LATER_FIXED_CANDIDATE","MISSING_MIHOMO_DEPENDENCIES",
            "BRIDGE_RENDER_FAILED","BRIDGE_RENDER_NOT_YAML",
            "BRIDGE_RENDER_NOT_MAPPING","XRAY_BRIDGE_NOT_IN_MIHOMO_GROUP",
            "MIHOMO_BRIDGE_CONFIG_REJECTED"}:
            reason="LIVE_EXACT_IDENTITY_OR_NETWORK_PREFLIGHT_FAILED"
        result("ERROR",reason)
        return 1
    return 0
if __name__=="__main__":
    raise SystemExit(main())
