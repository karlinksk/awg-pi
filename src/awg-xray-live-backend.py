#!/usr/bin/env python3
"""EXPERIMENTAL test-Pi cross-core activation backend.

Not installed/enabled by default. An independent systemd watchdog fails closed
rather than restoring a known-dead predecessor. Never change router or DNS.
A successful runtime check is NOT proof of reboot/LAN acceptance.
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

BASE=Path("/var/backups/awg-gateway")
PROVIDER=Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
MODE=Path("/etc/awg-pbr/mode")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
NODE_POLICY_MODE=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
NODE_POLICY_ORDER=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
BRIDGE=Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
BRIDGE_RUNTIME=Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
RENDERER=Path("/usr/local/sbin/awg-mihomo-config")
ADAPTER=Path("/usr/local/sbin/awg-xray-vless")
CORE=Path("/usr/local/bin/mihomo")
XRAY="awg-xray-vless.service"
MIHOMO="awg-mihomo.service"
GROUP="AWG-MIHOMO"
LOCAL="AWG-XRAY-VLESS-LOCAL"
EXECUTOR=Path("/usr/local/sbin/awg-xray-live-backend")

def run(*args,timeout=20,env=None):
    p=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,text=True,timeout=timeout,env=env)
    if p.returncode:
        raise RuntimeError("PROCESS_FAILED_"+Path(args[0]).name)
    return p.stdout.strip()

def active(service):
    return subprocess.run(["systemctl","is-active","--quiet",service],
      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode==0

def routes_ok():
    for table in ("100","101"):
        output=run("ip","route","show","table",table,timeout=6)
        if not any(re.fullmatch(r"default\s+dev\s+mihomo0(?:\s+.*)?",s.strip())
                   for s in output.splitlines()):
            return False
    return True

def http_code(args):
    env={k:v for k,v in os.environ.items() if k.lower() not in
         ("http_proxy","https_proxy","all_proxy","no_proxy")}
    try:
        return run("curl","-q","-4","-sS","--connect-timeout","7","--max-time","20",
          "-o","/dev/null","-w","%{http_code}",*args,
          "https://api.openai.com/v1/models",timeout=25,env=env)=="401"
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        return False

def original_tun_unreachable_twice():
    # This emergency executor is NOT a manual healthy-node selector.
    # Never disrupt a proven reachable incumbent just to try VLESS.
    return (not http_code(["--interface","mihomo0","--noproxy","*"]) and
            not http_code(["--interface","mihomo0","--noproxy","*"]))

def controller():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:9090/proxies/"+GROUP,timeout=3) as r:
        return json.load(r)

def choose(value):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request("http://127.0.0.1:9090/proxies/"+GROUP,
      data=json.dumps({"name":value}).encode(),method="PUT",
      headers={"Content-Type":"application/json"})
    with opener.open(req,timeout=5) as resp:
        if resp.status not in (200,204):raise RuntimeError("CONTROLLER_REJECTED")
    if controller().get("now")!=value:raise RuntimeError("CONTROLLER_NOT_COMMITTED")

def failclosed():
    # Transit remains subject to existing nft drop guard; never open DIRECT.
    if MODE.read_text().strip()!="transit":return False
    try:
        run("/usr/local/sbin/awg-transit-routing","disable",timeout=16)
        for service in (MIHOMO,XRAY):
            run("systemctl","stop",service,timeout=20)
        # The live candidate was not certified. Do not leave a persistent
        # bridge pointing at its unverified sidecar on the next reboot.
        for overlay in (BRIDGE_RUNTIME,BRIDGE):
            if overlay.exists():
                if overlay.is_symlink() or b"MIHOMO_XRAY_VLESS_BRIDGE=1" not in overlay.read_bytes():
                    return False
                overlay.unlink()
        run("systemctl","disable",XRAY,timeout=15)
        run("systemctl","daemon-reload",timeout=15)
        SELECTED.unlink(missing_ok=True)  # preflight requires it absent
        proof=run("/usr/local/sbin/awg-transit-routing","status",timeout=10)
        return (not active(MIHOMO) and
                "Transit policy rule: INACTIVE" in proof and
                ("Transit guard: SAFE" in proof or "Transit guard: LOCKDOWN" in proof))
    except Exception:
        return False

def candidate_allowed_by_policy(failed, candidate):
    try:
        mode=NODE_POLICY_MODE.read_text().strip()
        if mode=="auto":return True
        if mode!="fixed":return False
        chain=[line.strip() for line in NODE_POLICY_ORDER.read_text().splitlines() if line.strip()]
        # Exact names and one-way order only; never infer countries or loop.
        if len(chain)!=len(set(chain)) or failed not in chain or candidate not in chain:
            return False
        return chain.index(candidate)>chain.index(failed)
    except (OSError,UnicodeError):return False

def write_atomic(path, data,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_name("."+path.name+".txn-"+str(os.getpid()))
    try:
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,mode)
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

class LinuxBackend:
    def __init__(self,failed,candidate):
        self.failed,self.candidate=failed,candidate
        self.provider_hash=""
        self.index=None
        self.fingerprint=None
        self.snapshot=None
        self.watchdog_unit=None
    def preflight(self,failed,candidate):
        if os.geteuid()!=0 or MODE.read_text().strip()!="transit":
            raise RuntimeError("ROOT_TRANSIT_REQUIRED")
        if CURRENT.read_text().strip()!=failed or failed==candidate:
            raise RuntimeError("FAILED_NODE_IDENTITY_CHANGED")
        if not candidate_allowed_by_policy(failed,candidate):
            raise RuntimeError("CANDIDATE_NOT_ALLOWED_BY_NODE_POLICY")
        if not active(MIHOMO) or active(XRAY) or not routes_ok():
            raise RuntimeError("LIVE_BASELINE_UNSAFE")
        if BRIDGE.exists() or BRIDGE_RUNTIME.exists() or SELECTED.exists() or not RENDERER.is_file() or not ADAPTER.is_file():
            raise RuntimeError("BRIDGE_NOT_UNINSTALLED_OR_ADAPTER_MISSING")
        if not (EXECUTOR.is_file() and CORE.is_file()):raise RuntimeError("INSTALL_FIRST")
        raw=PROVIDER.read_bytes()
        if len(raw)>8*1024*1024:raise RuntimeError("PROVIDER_TOO_LARGE")
        doc=yaml.safe_load(raw)
        nodes=doc.get("proxies") if isinstance(doc,dict) else None
        if not isinstance(nodes,list):raise RuntimeError("BAD_PROVIDER")
        matches=[(i,n) for i,n in enumerate(nodes,1) if isinstance(n,dict)
                 and n.get("name")==candidate]
        if len(matches)!=1:raise RuntimeError("AMBIGUOUS_XRAY_NODE")
        self.index,node=matches[0]
        if node.get("type")!="vless" or node.get("network") not in ("xhttp","grpc"):
            raise RuntimeError("NOT_XRAY_VLESS")
        # Dynamic loader performs the same strict Reality validation as Xray.
        spec=importlib.util.spec_from_file_location("xray_adapter",str(ADAPTER))
        if spec is None:
            from importlib.machinery import SourceFileLoader
            spec=importlib.util.spec_from_loader("xray_adapter",SourceFileLoader("xray_adapter",str(ADAPTER)))
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        mod.validate(node)
        self.fingerprint=mod.sha_profile(node)
        self.provider_hash=hashlib.sha256(raw).hexdigest()
        resolution=run("/usr/local/sbin/awg-mihomo-unified-nodes","resolve",candidate,timeout=12)
        fields=dict(line.split("=",1) for line in resolution.splitlines() if "=" in line)
        if (fields.get("NODE_ENGINE")!="XRAY" or
            fields.get("NODE_INDEX")!=str(self.index) or
            fields.get("NODE_PROVIDER_SHA256")!=self.provider_hash or
            fields.get("NODE_BASIC_NETWORK")!="NETWORK_OK"):
            raise RuntimeError("XRAY_CANDIDATE_NOT_FRESHLY_NETWORK_QUALIFIED")
        # Do not call awg-route while holding the maintenance lock: that CLI
        # acquires the same flock. The transit-routing helper is lock-free.
        policy=run("/usr/local/sbin/awg-transit-routing","status",timeout=10)
        if "Transit guard: SAFE" not in policy or "Transit policy rule: ACTIVE" not in policy:
            raise RuntimeError("TRANSIT_GUARD_NOT_SAFE")
    def arm_watchdog(self):
        if not self.provider_hash:raise RuntimeError("PREFLIGHT_NOT_COMPLETE")
        self.snapshot=BASE/("xray-failover-"+str(int(time.time()))+"-"+str(os.getpid()))
        self.snapshot.mkdir(mode=0o700)
        state={"state":"armed","failed_sha256":hashlib.sha256(self.failed.encode()).hexdigest(),
               "candidate_fingerprint":self.fingerprint,"provider_sha256":self.provider_hash}
        write_atomic(self.snapshot/"state.json",json.dumps(state).encode())
        self.watchdog_unit="awg-xray-failover-"+str(os.getpid())
        try:
            run("systemd-run","--unit="+self.watchdog_unit,"--on-active=300s",
                str(EXECUTOR),"watchdog",str(self.snapshot),timeout=12)
            if not active(self.watchdog_unit+".timer"):
                raise RuntimeError("INDEPENDENT_WATCHDOG_NOT_ACTIVE")
        except Exception:
            # There have been no live mutations yet. Mark as cancelled even
            # if the timer exists but is not observable; the watchdog MUST
            # ignore this snapshot rather than stopping a healthy Mihomo.
            state["state"]="cancelled"
            write_atomic(self.snapshot/"state.json",json.dumps(state).encode())
            try:run("systemctl","stop",self.watchdog_unit+".timer",timeout=9)
            except Exception:pass
            raise
    def check_provider_unchanged(self):
        return hashlib.sha256(PROVIDER.read_bytes()).hexdigest()==self.provider_hash
    def stage_xray(self,candidate):
        if candidate!=self.candidate or not self.check_provider_unchanged():
            raise RuntimeError("PROVIDER_OR_CANDIDATE_CHANGED")
        run(str(ADAPTER),"select",str(self.index))
    def start_xray(self):
        run("systemctl","start",XRAY,timeout=25)
        if not active(XRAY):raise RuntimeError("XRAY_SERVICE_NOT_ACTIVE")
    def check_local_https(self):
        return http_code(["--socks5-hostname","127.0.0.1:17892","--noproxy",""])
    def stage_mihomo_bridge(self):
        if not self.check_provider_unchanged():raise RuntimeError("PROVIDER_ROTATED")
        # Always validate exactly the versioned renderer that the live unit uses.
        content=RENDERER.read_bytes()
        if b"MIHOMO_XRAY_VLESS_BRIDGE" not in content:raise RuntimeError("RENDERER_OUTDATED")
        env=os.environ.copy();env["MIHOMO_XRAY_VLESS_BRIDGE"]="1"
        raw=run(str(RENDERER),timeout=10,env=env)
        import tempfile
        with tempfile.TemporaryDirectory(prefix="awg-xray-check-",dir="/run") as folder:
            config=Path(folder)/"config.yaml"
            config.write_text(raw)
            config.chmod(0o600)
            run(str(CORE),"-t","-d","/var/lib/awg-pbr/mihomo","-f",str(config),timeout=20)
        result=yaml.safe_load(raw)
        if not any(p.get("name")==LOCAL for p in result.get("proxies",[])):
            raise RuntimeError("BRIDGE_NOT_PRESENT")
        # Do not persist this dependency until the live TUN passes.
        # An interrupted reboot clears the /run override automatically.
        unit=b'[Unit]\nRequires=awg-xray-vless.service\nAfter=awg-xray-vless.service\n[Service]\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n'
        write_atomic(BRIDGE_RUNTIME,unit)
        run("systemctl","daemon-reload",timeout=20)
    def restart_mihomo(self):
        run("systemctl","restart",MIHOMO,timeout=30)
        if not active(MIHOMO):raise RuntimeError("MIHOMO_DID_NOT_START")
    def restore_kernel_routes(self):
        # Kernel drops routes to destroyed TUN ifindex during service restart.
        # Wait for the new interface, not just active systemd service state.
        deadline=time.monotonic()+14
        while time.monotonic()<deadline:
            try:
                run("ip","link","show","dev","mihomo0",timeout=4)
                break
            except Exception:time.sleep(.3)
        else:raise RuntimeError("TUN_DEVICE_NOT_RECREATED")
        for t in ("100","101"):
            output=run("ip","route","show","table",t)
            if re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",output):continue
            if output.strip():raise RuntimeError("FOREIGN_ROUTE_IN_TABLE_"+t)
            run("ip","route","replace","table",t,"default","dev","mihomo0")
        if not routes_ok():raise RuntimeError("ROUTE_REINSTATE_FAILED")
    def select_xray_bridge(self):
        deadline=time.monotonic()+14
        while time.monotonic()<deadline:
            try:
                if LOCAL in controller().get("all",[]):choose(LOCAL);return
            except Exception:pass
            time.sleep(.3)
        raise RuntimeError("BRIDGE_NOT_SELECTABLE")
    def check_tun_https(self):
        return http_code(["--interface","mihomo0","--noproxy","*"])
    def check_policy_routes(self):
        status=run("/usr/local/sbin/awg-transit-routing","status",timeout=12)
        return (routes_ok() and "Transit guard: SAFE" in status and
                "Transit policy rule: ACTIVE" in status and
                "Transit VPN table: READY" in status)
    def install_boot_dependencies(self):
        # Called strictly AFTER live TUN HTTPS + policy route postcheck.
        # Up to this point an interrupted reboot discards /run overrides.
        if not BRIDGE_RUNTIME.is_file() or BRIDGE_RUNTIME.is_symlink():
            raise RuntimeError("EPHEMERAL_BRIDGE_NOT_READY")
        unit=BRIDGE_RUNTIME.read_bytes()
        if b"Requires=awg-xray-vless.service" not in unit or b"MIHOMO_XRAY_VLESS_BRIDGE=1" not in unit:
            raise RuntimeError("EPHEMERAL_BRIDGE_INVALID")
        write_atomic(BRIDGE,unit)
        run("systemctl","daemon-reload",timeout=15)
        run("systemctl","enable",XRAY,timeout=15)
    def check_boot_dependencies(self):
        result=subprocess.run(["systemctl","is-enabled","--quiet",XRAY],timeout=5)
        return (result.returncode==0 and BRIDGE.is_file() and not BRIDGE.is_symlink()
                and BRIDGE_RUNTIME.is_file() and
                BRIDGE.read_bytes()==BRIDGE_RUNTIME.read_bytes() and
                b"Requires=awg-xray-vless.service" in BRIDGE.read_bytes())
    def verify_committed_node(self,candidate):
        if candidate!=self.candidate or not self.check_provider_unchanged():return False
        try:
            value=json.loads(SELECTED.read_text())
            return value.get("sha256")==self.fingerprint and controller().get("now")==LOCAL
        except Exception:return False
    def commit(self):
        if not self.snapshot or not self.check_policy_routes():raise RuntimeError("NOT_VERIFIED")
        if not self.verify_committed_node(self.candidate):
            raise RuntimeError("LIVE_XRAY_SELECTION_MISMATCH")
        state=json.loads((self.snapshot/"state.json").read_text())
        if state.get("state")!="armed":raise RuntimeError("WATCHDOG_ALREADY_FIRED")
        # Selection monitor shares the maintenance flock. Publish the new
        # logical profile before releasing that lock so its next failover
        # starts AFTER this VLESS, never from the already-dead HY2 profile.
        if CURRENT.read_text().strip()!=self.failed:
            raise RuntimeError("FAILED_NODE_IDENTITY_CHANGED_DURING_ACTIVATION")
        write_atomic(CURRENT,(self.candidate+chr(10)).encode())
        if CURRENT.read_text().strip()!=self.candidate:
            raise RuntimeError("NODE_STATE_NOT_PERSISTED")
        state["state"]="committed"
        state["boot_tested"]=False
        write_atomic(self.snapshot/"state.json",json.dumps(state).encode())
    def disarm_watchdog(self):
        run("systemctl","stop",self.watchdog_unit+".timer",timeout=9)
    def fail_closed(self):
        return failclosed()

def watchdog(path):
    if path.parent!=BASE or not re.fullmatch(r"xray-failover-[0-9]+-[0-9]+",path.name):
        raise RuntimeError("INVALID_SNAPSHOT")
    if path.is_symlink():raise RuntimeError("SYMLINK_SNAPSHOT")
    state=json.loads((path/"state.json").read_text())
    if state.get("state")=="cancelled":
        return  # no live mutation was made; never quiesce a healthy gateway
    if state.get("state")=="committed":
        # If the watchdog fires just after commit, check live state anyway.
        try:
            status=run("/usr/local/sbin/awg-transit-routing","status",timeout=10)
            good=("Transit guard: SAFE" in status and
                  "Transit policy rule: ACTIVE" in status and
                  "Transit VPN table: READY" in status)
        except Exception:good=False
        if good and routes_ok() and http_code(["--interface","mihomo0","--noproxy","*"]):
            return
    if not failclosed():raise RuntimeError("FAIL_CLOSED_NOT_CONFIRMED")
    state["state"]="quiesced"
    write_atomic(path/"state.json",json.dumps(state).encode())

def cli():
    if len(sys.argv)==3 and sys.argv[1]=="watchdog":
        watchdog(Path(sys.argv[2]));return
    if len(sys.argv)!=4 or sys.argv[1]!="apply":
        raise SystemExit("Usage: awg-xray-live-backend apply FAILED_NODE CANDIDATE (disabled until explicit test authorization)")
    if os.environ.get("AWG_XRAY_EXPERIMENTAL_APPLY")!="TEST_PI_AUTHORIZED":
        raise SystemExit("EXPERIMENTAL_APPLY_DISABLED")
    if socket.gethostname()!="awg-upgrade":
        raise SystemExit("TEST_PI_ONLY")
    from importlib.machinery import SourceFileLoader
    loader=SourceFileLoader("awg_xray_activation", "/usr/local/sbin/awg-xray-activation-transaction")
    import types
    module=types.ModuleType(loader.name)
    sys.modules[loader.name]=module
    loader.exec_module(module)
    with Path("/run/awg-maintenance.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if not original_tun_unreachable_twice():
            raise SystemExit("XRAY_TRANSACTION_ABORT=ORIGINAL_TUN_STILL_REACHABLE")
        receipt=module.activate(sys.argv[2],sys.argv[3],LinuxBackend(sys.argv[2],sys.argv[3]))
    print("XRAY_TRANSACTION_RUNTIME_TUN_VERIFIED="+str(receipt.tun_verified).upper())
    print("XRAY_TRANSACTION_REBOOT_TESTED=NO")

if __name__=="__main__":
    cli()
