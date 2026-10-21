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


def stable_error_code(exc):
    """Error metadata must never contain provider URLs, UUIDs or secrets."""
    value=str(exc)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}",value) else "UNCLASSIFIED_FAILURE"

def prove_previous_tun():
    # An Xray service restart can leave the loopback socket ready before the
    # prior TUN HTTPS flow is re-established; give the proven old node bounded
    # retry time before treating rollback as failed.
    for attempt in range(3):
        if not unit_active(XRAY):
            refuse("PREVIOUS_XRAY_SERVICE_EXITED")
        if https_ok("tun"):
            return
        if attempt<2:
            time.sleep(1)
    refuse("PREVIOUS_TUN_RESTORE_FAILED")

def checkpoint(path,state,step):
    # Keep phase ARMED at every step, so a crash never disarms the watchdog.
    state["checkpoint"]=step
    stored(path,state,state["phase"])

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

def inspect_native(name):
    """An already-loaded native Mihomo choice, with active Xray as rollback."""
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    if not isinstance(name,str) or not 1<=len(name)<=240 or (
       "\n" in name or "\r" in name or "\x00" in name):
        refuse("INVALID_NATIVE_NAME")
    invariant()
    con=controller()
    if con.get("now")!=ALIAS or not unit_active(XRAY):
        refuse("XRAY_NOT_ACTIVE")
    if name==ALIAS or name not in con.get("all",[]):
        refuse("NATIVE_NOT_LOADED_IN_MIHOMO")
    # A native profile must already be fully configured by the ordinary
    # installer/selector. Do not rewrite provider/filter while Xray is live.
    configured=read(CURRENT)
    if configured is None or configured.decode("utf-8","replace").strip()!=name:
        refuse("NATIVE_CONFIG_NOT_PREPARED")
    raw=PROVIDER.read_bytes()
    if not raw or len(raw)>8*1024*1024:refuse("INVALID_PROVIDER_SIZE")
    parsed=yaml.safe_load(raw)
    rows=parsed.get("proxies",[]) if isinstance(parsed,dict) else []
    if sum(isinstance(p,dict) and p.get("name")==name for p in rows)!=1:
        refuse("NATIVE_PROFILE_NOT_UNIQUE")
    chosen=read(SELECTED)
    if chosen is None:refuse("PREVIOUS_XRAY_PROFILE_MISSING")
    try: digest=json.loads(chosen).get("sha256")
    except (ValueError,UnicodeError):refuse("PREVIOUS_XRAY_PROFILE_INVALID")
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        refuse("PREVIOUS_XRAY_PROFILE_INVALID")
    if BOOT.is_symlink() or (BOOT.exists() and
       b"AWG_XRAY_MANUAL=1" not in BOOT.read_bytes()):
        refuse("FOREIGN_BOOT_DEPENDENCY")
    if not https_ok("tun"):refuse("PREVIOUS_TUN_NOT_PROVEN")
    return {"previous":ALIAS,"previous_xray":True,"xray_enabled":unit_enabled(XRAY),
            "candidate":name,"sha":hashlib.sha256(raw).hexdigest(),
            "fingerprint":digest,"operation":"NATIVE_RETURN"}

def native_return(name):
    """Guarded controller switch back to already-configured Mihomo native.

    Never pass through node select-auto while Xray owns the TUN: that helper
    reconfigures metadata/restarts Mihomo and can leave the Xray alias selected.
    """
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        info=inspect_native(name)
        path,state=save_snap(info)
        timer=state["watchdog"]+".timer"
        mutated=False
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):refuse("WATCHDOG_NOT_ARMED")
            stored(path,state,"armed")
            checkpoint(path,state,"NATIVE_VERIFY")
            if inspect_native(name)["sha"]!=info["sha"]:
                refuse("PROVIDER_CHANGED")
            checkpoint(path,state,"NATIVE_CONTROLLER_SELECT")
            mutated=True
            choose(name)
            checkpoint(path,state,"NATIVE_TUN_CHECK")
            if not https_ok("tun") or not routing_ok():
                refuse("NATIVE_TUN_OR_ROUTES_UNVERIFIED")
            invariant()
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=info["sha"]:
                refuse("PROVIDER_CHANGED_BEFORE_COMMIT")
            # Only after live native TUN success detach the old Xray sidecar.
            checkpoint(path,state,"NATIVE_COMMIT")
            atomic(CURRENT,(name+"\n").encode())
            BOOT.unlink(missing_ok=True)
            SELECTED.unlink(missing_ok=True)
            cmd("systemctl","daemon-reload")
            cmd("systemctl","stop",XRAY)
            cmd("systemctl","disable",XRAY)
            checkpoint(path,state,"NATIVE_POSTCOMMIT_CHECK")
            if controller().get("now")!=name or unit_active(XRAY) or (
               unit_enabled(XRAY)) or not https_ok("tun") or not routing_ok():
                refuse("NATIVE_POSTCOMMIT_UNVERIFIED")
            invariant()
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("NATIVE_RETURN_TUN=VERIFIED")
            print("ACTIVE_EXIT=MIHOMO_NATIVE")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
            print("NATIVE_RETURN_REBOOT=NOT_TESTED")
        except Exception as exc:
            state["failure_code"]=stable_error_code(exc)
            state["failed_at"]=state.get("checkpoint","NOT_STARTED")
            if not mutated:
                # Neither controller nor service was touched. Do not stop a
                # healthy incumbent Xray when watchdog arm/preflight fails.
                stored(path,state,"cancelled")
                try:cmd("systemctl","stop",timer)
                except Exception:pass
                raise
            try:checkpoint(path,state,"ROLLBACK_ATTEMPT")
            except Exception:pass
            try:
                restore(path,state)
                checkpoint(path,state,"ROLLBACK_COMPLETE")
                stored(path,state,"rolled_back")
            except Exception as rollback_exc:
                state["rollback_failure_code"]=stable_error_code(rollback_exc)
                try:checkpoint(path,state,"WATCHDOG_RECOVERY_PENDING")
                except Exception:pass
                raise RuntimeError("XRAY_MANUAL_ROLLBACK_UNCONFIRMED")
            try:cmd("systemctl","stop",timer)
            except Exception:pass
            raise

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
        prove_previous_tun()
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
        mutated=False
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):refuse("WATCHDOG_NOT_ARMED")
            stored(path,state,"armed")
            checkpoint(path,state,"VERIFY_CANDIDATE")
            # Recheck current credential identity before touching healthy VPN.
            node,sha,fingerprint=source_node(index)
            if (node,sha,fingerprint)!=(info["candidate"],info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED")
            checkpoint(path,state,"STAGE_NEW_XRAY")
            mutated=True
            if state["previous_xray"]:cmd("systemctl","stop",XRAY)
            cmd(str(ADAPTER),"select",str(index))
            cmd("systemctl","start",XRAY)
            checkpoint(path,state,"PROBE_NEW_XRAY_SOCKS")
            # systemctl start only confirms the launch was queued, not that
            # the SOCKS listener or outbound HTTPS is ready. This probe uses
            # the same local-socks path as isolated validation, with a bounded
            # startup wait and actionable failure codes.
            prove_local_xray()
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED")
            checkpoint(path,state,"SWITCH_TUN")
            choose(ALIAS)
            if not https_ok("tun") or not routing_ok():
                refuse("XRAY_TUN_OR_ROUTES_UNVERIFIED")
            invariant()
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED_BEFORE_COMMIT")
            checkpoint(path,state,"COMMIT_POLICY")
            # Manual selection changes the CURRENT exit only. The user's
            # configured manual/FIXED/AUTO failover and READY/Hot Pool choices
            # are independent and must never be silently replaced here.
            atomic(CURRENT,(info["candidate"]+"\n").encode())
            BOOT.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            atomic(BOOT,b'[Unit]\nWants=awg-xray-vless.service\nAfter=awg-xray-vless.service\n# AWG_XRAY_MANUAL=1\n',0o644)
            cmd("systemctl","daemon-reload")
            cmd("systemctl","enable",XRAY)
            checkpoint(path,state,"POSTCOMMIT_TUN")
            if not unit_enabled(XRAY) or not https_ok("tun") or not routing_ok():
                refuse("XRAY_POSTCOMMIT_UNVERIFIED")
            if source_node(index)[1:]!=(info["sha"],info["fingerprint"]):
                refuse("PROVIDER_CHANGED_AFTER_TUN_POSTCHECK")
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("XRAY_MANUAL_TUN=VERIFIED")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
            print("XRAY_MANUAL_REBOOT=NOT_TESTED")
        except Exception as exc:
            # Durable, root-only, code-only failure report; no credentials.
            state["failure_code"]=stable_error_code(exc)
            state["failed_at"]=state.get("checkpoint","NOT_STARTED")
            if not mutated:
                stored(path,state,"cancelled")
                try:cmd("systemctl","stop",timer)
                except Exception:pass
                raise
            # If immediate rollback fails, preserve phase=armed for watchdog.
            try:
                checkpoint(path,state,"ROLLBACK_ATTEMPT")
            except Exception:
                pass
            try:
                restore(path,state)
                checkpoint(path,state,"ROLLBACK_COMPLETE")
                stored(path,state,"rolled_back")
            except Exception as rollback_exc:
                state["rollback_failure_code"]=stable_error_code(rollback_exc)
                try:checkpoint(path,state,"WATCHDOG_RECOVERY_PENDING")
                except Exception:pass
                # Leave the watchdog ARMED. The other unit will retry safely.
                raise RuntimeError("XRAY_MANUAL_ROLLBACK_UNCONFIRMED")
            try:cmd("systemctl","stop",timer)
            except Exception:pass
            raise

def last_failure():
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    snapshots=[p for p in ROOT.glob("xray-manual-[0-9]*-[0-9]*")
               if p.is_dir() and not p.is_symlink() and p.stat().st_uid==0]
    if not snapshots:
        print("XRAY_MANUAL_DIAG=NO_SNAPSHOT")
        return
    folder=max(snapshots,key=lambda p:p.stat().st_mtime)
    state=json.loads((folder/"state.json").read_text())
    # Expose only enumerated nonsecret words; no profile names or hashes.
    for key in ("phase","failure_code","failed_at","rollback_failure_code","checkpoint"):
        value=state.get(key,"UNKNOWN")
        safe=value if isinstance(value,str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}|rolled_back|committed|armed|pending|cancelled",value) else "UNKNOWN"
        print("XRAY_MANUAL_"+key.upper()+"="+safe)

def main():
    if len(sys.argv)==3 and sys.argv[1] in ("native-preview","native-apply"):
        if sys.argv[1]=="native-preview":
            inspect_native(sys.argv[2])
            print("NATIVE_RETURN_PREFLIGHT=PASS")
            print("NATIVE_RETURN_TUN=NOT_TESTED")
        else:native_return(sys.argv[2])
        return
    if len(sys.argv)==2 and sys.argv[1]=="diagnose":
        last_failure();return
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
