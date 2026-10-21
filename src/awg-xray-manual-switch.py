#!/usr/bin/env python3
"""Guarded MANUAL switch to a current Xray Reality node through existing Mihomo TUN.

Never invoked by the subscription scanner. This is NOT the AUTO failed-incumbent
transaction. Requires the dormant AWG-XRAY-VLESS-LOCAL alias in running Mihomo.
A separate systemd watchdog restores the previously healthy native/Xray exit on
aborted operations. Nothing touches RouterOS, DNS, SSH, or global default routes.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request
import yaml

ROOT=Path("/var/backups/awg-gateway")
PROVIDER=Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
HEALTH=Path("/var/lib/awg-pbr/xray-vless/network-health.json")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
POLICY=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
ORDER=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
MODE=Path("/etc/awg-pbr/mode")
BOOT=Path("/etc/systemd/system/awg-mihomo.service.d/62-awg-xray-manual.conf")
LOCK=Path("/run/awg-maintenance.lock")
ADAPTER=Path("/usr/local/sbin/awg-xray-vless")
SWITCH=Path("/usr/local/sbin/awg-xray-manual-switch")
ALIAS="AWG-XRAY-VLESS-LOCAL"
XRAY="awg-xray-vless.service"
MIHOMO="awg-mihomo.service"
WATCH_SECONDS=180

def refuse(code):
    raise RuntimeError(code)

def cmd(*args,timeout=20):
    p=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL,text=True,timeout=timeout)
    if p.returncode:refuse("PROCESS_FAILED_"+Path(args[0]).name)
    return p.stdout.strip()

def unit_active(name):
    return subprocess.run(["systemctl","is-active","--quiet",name],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=6).returncode==0

def unit_enabled(name):
    return subprocess.run(["systemctl","is-enabled","--quiet",name],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=6).returncode==0

def controller():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=5) as response:
        return json.load(response)

def choose(node):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO",
        data=json.dumps({"name":node}).encode(),method="PUT",
        headers={"Content-Type":"application/json"})
    with opener.open(req,timeout=5) as resp:
        if resp.status not in (200,204):refuse("CONTROLLER_REJECTED")
    if controller().get("now")!=node:refuse("CONTROLLER_SELECTION_MISMATCH")

def https_ok(via):
    env={k:v for k,v in os.environ.items() if k.lower() not in
         ("http_proxy","https_proxy","all_proxy","no_proxy")}
    params=(["--interface","mihomo0","--noproxy","*"] if via=="tun" else
            ["--socks5-hostname","127.0.0.1:17892","--noproxy",""])
    try:
        p=subprocess.run(["curl","-q","-4","-sS","--connect-timeout","7",
            "--max-time","18","-o","/dev/null","-w","%{http_code}",*params,
            "https://api.openai.com/v1/models"],env=env,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=23)
        return p.returncode==0 and p.stdout.strip()=="401"
    except (OSError,subprocess.TimeoutExpired):
        return False

def prove_local_xray():
    """Bounded readiness + two HTTPS probes, before the TUN selector changes.

    An isolated candidate can pass when the systemd service has not yet bound
    its fixed SOCKS port. Do not conflate service crashes, missing listener and
    an actual HTTPS failure; expose a stable error code, never credentials.
    """
    until=time.monotonic()+10
    listener=False
    while time.monotonic()<until:
        if unit_active(XRAY):
            try:
                with socket.create_connection(("127.0.0.1",17892),timeout=.4):
                    listener=True
                    break
            except OSError:
                pass
        time.sleep(.3)
    if not unit_active(XRAY):
        refuse("XRAY_SERVICE_NOT_ACTIVE")
    if not listener:
        refuse("XRAY_SOCKS_PORT_NOT_LISTENING")
    for attempt in range(2):
        if https_ok("socks"):
            return
        if not unit_active(XRAY):
            refuse("XRAY_SERVICE_EXITED_DURING_HTTPS")
        if attempt==0:
            time.sleep(1)
    refuse("XRAY_SOCKS_HTTPS_NOT_VERIFIED")


def atomic(path,data,mode=0o600):
    import tempfile
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink():refuse("UNTRUSTED_STATE_PATH")
    fd,tmp=tempfile.mkstemp(prefix=".awg-xray-manual-",dir=path.parent)
    tmp=Path(tmp)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def read(path):
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None

def source_node(index):
    raw=PROVIDER.read_bytes()
    if len(raw)>8*1024*1024:refuse("PROVIDER_TOO_LARGE")
    obj=yaml.safe_load(raw)
    profiles=obj.get("proxies") if isinstance(obj,dict) else None
    if not isinstance(profiles,list) or not 1<=index<=len(profiles)<=10000:
        refuse("INVALID_PROVIDER_INDEX")
    node=profiles[index-1]
    if not isinstance(node,dict) or not isinstance(node.get("name"),str):
        refuse("INVALID_PROFILE")
    if sum(isinstance(p,dict) and p.get("name")==node["name"] for p in profiles)!=1:
        refuse("DUPLICATE_NODE_NAME")
    if node.get("type")!="vless" or node.get("network") not in ("xhttp","grpc"):
        refuse("XRAY_REALITY_ONLY")
    spec=importlib.util.spec_from_file_location("adapter",str(ADAPTER))
    if spec is None:
        from importlib.machinery import SourceFileLoader
        spec=importlib.util.spec_from_loader("adapter",SourceFileLoader("adapter",str(ADAPTER)))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    mod.validate(node)
    identity=mod.sha_profile(node)
    cache=json.loads(HEALTH.read_text())
    proof=cache.get("results",{}).get(identity,{})
    age=time.time()-proof.get("at",0) if isinstance(proof,dict) else 1e9
    if not 0<=age<=600 or proof.get("status")!="NETWORK_OK":
        refuse("XRAY_FRESH_NETWORK_PROOF_REQUIRED")
    return node["name"],hashlib.sha256(raw).hexdigest(),identity

def routing_ok():
    for table in ("100","101"):
        lines=cmd("ip","-4","route","show","table",table,timeout=6).splitlines()
        if len(lines)!=1 or not re.fullmatch(
                r"default\s+dev\s+mihomo0(?:\s+.*)?",lines[0].strip()):
            return False
    rules=cmd("ip","-4","rule","show",timeout=6)
    return bool(re.search(r"\bfwmark\s+(?:0x100|256)\s+lookup\s+100\b",rules))

def invariant():
    if not all(unit_active(x) for x in (MIHOMO,"ssh.service","dnsmasq.service",
                                         "awg-pbr-health.service")):
        refuse("MANAGEMENT_OR_MIHOMO_UNHEALTHY")
    if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
        refuse("ACTIVE_TRANSPORT_NOT_MIHOMO")
    if MODE.read_text().strip() not in ("selective","transit"):refuse("INVALID_GATEWAY_MODE")
    if not routing_ok():refuse("ROUTING_NOT_SAFE")
    if MODE.read_text().strip()=="transit":
        status=cmd("/usr/local/sbin/awg-transit-routing","status")
        if not all(x in status for x in ("Transit guard: SAFE",
                  "Transit policy rule: ACTIVE","Transit VPN table: READY")):
            refuse("TRANSIT_GUARD_NOT_SAFE")

def inspect(index):
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    if not ADAPTER.is_file():refuse("XRAY_ADAPTER_MISSING")
    candidate,provider_sha,fingerprint=source_node(index)
    invariant()
    con=controller()
    if ALIAS not in con.get("all",[]):refuse("XRAY_BRIDGE_NOT_IN_RUNNING_CONFIG")
    previous=con.get("now")
    if not isinstance(previous,str) or not previous:refuse("MISSING_PREVIOUS_NODE")
    if previous==ALIAS and not unit_active(XRAY):refuse("PREVIOUS_XRAY_DEAD")
    if previous!=ALIAS and unit_active(XRAY):refuse("FOREIGN_XRAY_RUNNING")
    if not https_ok("tun"):refuse("PREVIOUS_TUN_NOT_PROVEN")
    if (BOOT.exists() or BOOT.is_symlink()) and (
        BOOT.is_symlink() or b"AWG_XRAY_MANUAL=1" not in BOOT.read_bytes()):
        refuse("FOREIGN_BOOT_DEPENDENCY")
    # Idempotency is critical: selecting the already-healthy Xray profile
    # must NEVER stop its active SOCKS service or arm a recovery watchdog.
    # Compare the exact current transport fingerprint, never name or index.
    same_xray=False
    if previous==ALIAS:
        try:
            selected=json.loads(SELECTED.read_text())
        except (OSError,ValueError,UnicodeError):
            refuse("ACTIVE_XRAY_FINGERPRINT_UNAVAILABLE")
        if not isinstance(selected,dict) or not isinstance(selected.get("sha256"),str):
            refuse("ACTIVE_XRAY_FINGERPRINT_INVALID")
        same_xray=(selected["sha256"]==fingerprint)
    return {"index":index,"candidate":candidate,"sha":provider_sha,
            "fingerprint":fingerprint,"previous":previous,
            "previous_xray":previous==ALIAS,
            "already_selected":same_xray,"xray_enabled":unit_enabled(XRAY)}

def save_snap(info):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=ROOT/("xray-manual-"+str(int(time.time()))+"-"+str(os.getpid()))
    path.mkdir(mode=0o700)
    state={"phase":"pending",**info,"watchdog": "awg-xray-manual-"+str(os.getpid())}
    atomic(path/"state.json",json.dumps(state).encode())
    for name,source in (("selected.prev",SELECTED),("current.prev",CURRENT),
                        ("policy.prev",POLICY),("order.prev",ORDER),
                        ("boot.prev",BOOT)):
        data=read(source)
        if data is not None:atomic(path/name,data)
    return path,state

def stored(path,state,phase):
    state["phase"]=phase
    atomic(path/"state.json",json.dumps(state).encode())

def restore(path,state):
    # A separately selected healthy AWG must never be replaced by the watchdog.
    if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
        refuse("FOREIGN_TRANSPORT_DURING_RECOVERY")
    previous=state["previous"]
    if state["previous_xray"]:
        cmd("systemctl","stop",XRAY)
        data=read(path/"selected.prev")
        if data is None:refuse("PREVIOUS_XRAY_PROFILE_MISSING")
        atomic(SELECTED,data)
        cmd("systemctl","start",XRAY)
        try:
            prove_local_xray()
        except RuntimeError:
            refuse("PREVIOUS_XRAY_RESTORE_FAILED")
        choose(ALIAS)
    else:
        choose(previous)
    if not https_ok("tun"):refuse("PREVIOUS_TUN_RESTORE_FAILED")
    for name,target in (("selected.prev",SELECTED),("boot.prev",BOOT),
                        ("current.prev",CURRENT),("policy.prev",POLICY),
                        ("order.prev",ORDER)):
        data=read(path/name)
        if data is None:target.unlink(missing_ok=True)
        else:atomic(target,data)
    if not state["previous_xray"]:cmd("systemctl","stop",XRAY)
    cmd("systemctl","enable" if state["xray_enabled"] else "disable",XRAY)
    cmd("systemctl","daemon-reload")
    invariant()

def watchdog(path):
    if path.parent!=ROOT or not re.fullmatch(r"xray-manual-[0-9]+-[0-9]+",path.name):
        refuse("UNTRUSTED_RECOVERY_PATH")
    if path.is_symlink():refuse("UNTRUSTED_RECOVERY_PATH")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state=json.loads((path/"state.json").read_text())
        if state.get("phase") not in ("armed","pending"):return
        if state["phase"]=="pending":
            stored(path,state,"cancelled")
            return
        restore(path,state)
        stored(path,state,"rolled_back")

def apply(index):
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        info=inspect(index)
        if info.get("already_selected"):
            # inspect has already proved service/TUN health; no change needed.
            print("XRAY_MANUAL_ALREADY_SELECTED=YES")
            print("XRAY_MANUAL_TUN=EXISTING_HEALTHY_NOT_SWITCHED")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
            return
        path,state=save_snap(info)
        timer=state["watchdog"]+".timer"
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):refuse("WATCHDOG_NOT_ARMED")
            stored(path,state,"armed")
            # Recheck current credential identity before touching healthy VPN.
            node,sha,fingerprint=source_node(index)
            if (node,sha,fingerprint)!=(info["candidate"],info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED")
            if state["previous_xray"]:cmd("systemctl","stop",XRAY)
            cmd(str(ADAPTER),"select",str(index))
            cmd("systemctl","start",XRAY)
            # systemctl start only confirms the launch was queued, not that
            # the SOCKS listener or outbound HTTPS is ready. This probe uses
            # the same local-socks path as isolated validation, with a bounded
            # startup wait and actionable failure codes.
            prove_local_xray()
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED")
            choose(ALIAS)
            if not https_ok("tun") or not routing_ok():
                refuse("XRAY_TUN_OR_ROUTES_UNVERIFIED")
            invariant()
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED_BEFORE_COMMIT")
            # Manual selection changes the CURRENT exit only. The user's
            # configured manual/FIXED/AUTO failover and READY/Hot Pool choices
            # are independent and must never be silently replaced here.
            atomic(CURRENT,(info["candidate"]+"\n").encode())
            BOOT.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            atomic(BOOT,b'[Unit]\nWants=awg-xray-vless.service\nAfter=awg-xray-vless.service\n# AWG_XRAY_MANUAL=1\n',0o644)
            cmd("systemctl","daemon-reload")
            cmd("systemctl","enable",XRAY)
            if not unit_enabled(XRAY) or not https_ok("tun") or not routing_ok():
                refuse("XRAY_POSTCOMMIT_UNVERIFIED")
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED_AFTER_TUN_POSTCHECK")
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("XRAY_MANUAL_TUN=VERIFIED")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
            print("XRAY_MANUAL_REBOOT=NOT_TESTED")
        except Exception:
            try:
                restore(path,state)
                stored(path,state,"rolled_back")
            except Exception:
                # Independent watchdog remains armed and may recover later.
                raise RuntimeError("XRAY_MANUAL_ROLLBACK_UNCONFIRMED")
            try:cmd("systemctl","stop",timer)
            except Exception:pass
            raise

def main():
    if len(sys.argv)==3 and sys.argv[1]=="watchdog":
        watchdog(Path(sys.argv[2]));return
    if len(sys.argv)==3 and sys.argv[1] in ("preview","apply"):
        if not re.fullmatch(r"[1-9][0-9]{0,4}",sys.argv[2]):
            refuse("INVALID_NODE_INDEX")
        index=int(sys.argv[2])
        if sys.argv[1]=="preview":
            result=inspect(index)
            print("XRAY_MANUAL_PREFLIGHT=PASS")
            if result.get("already_selected"):
                print("XRAY_MANUAL_ALREADY_SELECTED=YES")
                print("XRAY_MANUAL_TUN=EXISTING_HEALTHY_NOT_SWITCHED")
            else:
                print("XRAY_MANUAL_TUN=NOT_TESTED")
        else:apply(index)
        return
    raise SystemExit("Usage: awg-xray-manual-switch preview|apply INDEX")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        # Error codes only: never print UUID, Reality keys or provider URLs.
        print("XRAY_MANUAL_ERROR="+str(exc),file=sys.stderr)
        raise SystemExit(2)
