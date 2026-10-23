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
import urllib.error
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
CONFIGURE=Path("/usr/local/sbin/awg-mihomo-configure")
MIHOMO_ENV=Path("/etc/awg-pbr/transports/mihomo/provider.env")
MIHOMO_CONFIG=Path("/etc/awg-pbr/transports/mihomo/config.yaml")
MIHOMO_ENDPOINT=Path("/etc/awg-pbr/transports/mihomo/endpoint-ip")
MIHOMO_EGRESS=Path("/etc/awg-pbr/transports/mihomo/expected-egress-ip")
ALIAS="AWG-XRAY-VLESS-LOCAL"
XRAY="awg-xray-vless.service"
MIHOMO="awg-mihomo.service"
WATCH_SECONDS=180
# Only a bounded, secret-free failure class from the latest HTTPS probe.
# Never log the URL, profile name, provider details, TLS output or credentials.
_LAST_HTTPS_PROBE_CLASS="NOT_RUN"

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
    """Idempotent, bounded controller selection with a verified final state.

    A recovery watchdog must not repeat PUT if the previous node is already
    selected. Some controllers reject redundant PUT requests with HTTP 400.
    """
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        group=controller()
        if group.get("now")==node:
            return
        if node not in group.get("all",[]):
            refuse("CONTROLLER_TARGET_NOT_AVAILABLE")
        req=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO",
            data=json.dumps({"name":node}).encode(),method="PUT",
            headers={"Content-Type":"application/json"})
        try:
            with opener.open(req,timeout=5) as response:
                if response.status not in (200,204):
                    refuse("CONTROLLER_SELECTION_REJECTED")
        except urllib.error.HTTPError as exc:
            # Never treat an HTTP error as success without rereading now.
            if exc.code not in (400,409,503):
                refuse("CONTROLLER_SELECTION_REJECTED")
        try:
            if controller().get("now")==node:
                return
        except (OSError,ValueError,TimeoutError):
            pass
        if attempt<2:
            time.sleep(.5)
    refuse("CONTROLLER_SELECTION_NOT_CONFIRMED")

def https_ok(via):
    global _LAST_HTTPS_PROBE_CLASS
    _LAST_HTTPS_PROBE_CLASS="NOT_COMPLETED"
    env={k:v for k,v in os.environ.items() if k.lower() not in
         ("http_proxy","https_proxy","all_proxy","no_proxy")}
    if via=="tun":
        params=["--interface","mihomo0","--noproxy","*"]
    elif via=="socks":
        params=["--socks5-hostname","127.0.0.1:17892","--noproxy",""]
    elif via=="mixed":
        # Only a diagnostic: test the running Mihomo selector through its
        # loopback HTTP proxy. This never substitutes for the real TUN gate.
        params=["--proxy","http://127.0.0.1:7890","--noproxy",""]
    else:
        _LAST_HTTPS_PROBE_CLASS="UNKNOWN_PROBE_MODE"
        return False
    try:
        p=subprocess.run(["curl","-q","-4","-sS","--connect-timeout",
            ("5" if via=="mixed" else "7"),"--max-time",
            ("10" if via=="mixed" else "18"),"-o","/dev/null","-w","%{http_code}",*params,
            "https://api.openai.com/v1/models"],env=env,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,
            timeout=(15 if via=="mixed" else 23))
        code=p.stdout.strip()
        if p.returncode==0 and re.fullmatch(r"[0-9]{3}",code):
            _LAST_HTTPS_PROBE_CLASS="HTTP_"+code
        elif p.returncode!=0:
            # Curl's exit code is diagnostic, never a proof of network health.
            # Do not expose curl stderr or the endpoint itself.
            known={5,6,7,16,28,35,51,52,55,56,60}
            _LAST_HTTPS_PROBE_CLASS=("CURL_EXIT_"+str(p.returncode)
                                     if p.returncode in known else "CURL_EXIT_OTHER")
        else:
            _LAST_HTTPS_PROBE_CLASS="HTTP_INVALID"
        return p.returncode==0 and code=="401"
    except subprocess.TimeoutExpired:
        _LAST_HTTPS_PROBE_CLASS="PROCESS_TIMEOUT"
        return False
    except OSError:
        _LAST_HTTPS_PROBE_CLASS="PROCESS_ERROR"
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
    # Cached discovery is advisory. An operator may request a fresh
    # isolated test of a previously failed, stale or never-tested profile.
    return node["name"],hashlib.sha256(raw).hexdigest(),identity


def preflight_xray(index,expected):
    """Probe exact candidate in RAM without stopping the incumbent sidecar."""
    from importlib.machinery import SourceFileLoader
    path=Path("/usr/local/sbin/awg-mihomo-unified-nodes")
    if not path.is_file() or path.is_symlink() or path.stat().st_uid!=0:
        refuse("XRAY_ISOLATED_PROBE_MISSING")
    spec=importlib.util.spec_from_loader("awg_manual_probe",SourceFileLoader("awg_manual_probe",str(path)))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Imported test helpers support environment overrides; privileged manual
    # activation MUST use the pinned root-owned production engine and provider.
    module.PROVIDER=PROVIDER
    module.XRAY=Path("/usr/local/bin/awg-xray-vless-core")
    module.ADAPTER=ADAPTER
    module.PROBE_URL="https://api.openai.com/v1/models"
    raw=PROVIDER.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected["sha"]:
        refuse("PROVIDER_CHANGED_BEFORE_PROBE")
    profiles=yaml.safe_load(raw).get("proxies",[])
    if not isinstance(profiles,list) or not 1<=index<=len(profiles):
        refuse("PROVIDER_CHANGED_BEFORE_PROBE")
    node=profiles[index-1]
    adapter=module.load_adapter()
    if adapter.sha_profile(node)!=expected["fingerprint"]:
        refuse("PROFILE_CHANGED_BEFORE_PROBE")
    try:
        result=module.isolated_probe(adapter,node)
    except (OSError,ValueError,subprocess.TimeoutExpired,SystemExit):
        refuse("XRAY_ISOLATED_PROBE_ERROR")
    if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=expected["sha"]:
        refuse("PROVIDER_CHANGED_DURING_PROBE")
    if result!="NETWORK_OK":
        refuse("XRAY_ISOLATED_HTTPS_NOT_VERIFIED")

def preflight_mihomo(name,expected):
    """Isolated Mihomo HTTPS test; never reconfigure the live TUN."""
    from importlib.machinery import SourceFileLoader
    import tempfile
    pool_path=Path("/usr/local/sbin/awg-mihomo-pool")
    if not pool_path.is_file() or pool_path.is_symlink() or pool_path.stat().st_uid!=0:
        refuse("MIHOMO_ISOLATED_PROBE_MISSING")
    raw=PROVIDER.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected["sha"]:
        refuse("NATIVE_PROVIDER_CHANGED_BEFORE_PROBE")
    doc=yaml.safe_load(raw)
    profiles=doc.get("proxies",[]) if isinstance(doc,dict) else []
    selected=[p for p in profiles if isinstance(p,dict) and p.get("name")==name]
    if len(selected)!=1:refuse("NATIVE_PROFILE_CHANGED_BEFORE_PROBE")
    spec=importlib.util.spec_from_loader("awg_manual_mihomo_probe",
                                        SourceFileLoader("awg_manual_mihomo_probe",str(pool_path)))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MIHOMO_BIN="/usr/local/bin/mihomo"
    module.HEALTH_URL="https://www.gstatic.com/generate_204"
    module.DELAY_TIMEOUT_MS=7000
    node=selected[0]
    if module.uses_xray_sidecar(node):refuse("NATIVE_WRONG_PROBE_ENGINE")
    with tempfile.TemporaryDirectory(prefix="awg-manual-mihomo-",dir="/dev/shm") as tmp:
        root=Path(tmp);root.chmod(0o700)
        port=module.choose_free_port()
        controller_port=module.choose_free_port()
        while controller_port==port:controller_port=module.choose_free_port()
        config,rows=module.make_probe_config([node],port,controller_port)
        if len(rows)!=1 or not rows[0].get("valid"):
            refuse("NATIVE_INVALID_PROBE_PROFILE")
        cfg=root/"config.yaml"
        cfg.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
        cfg.chmod(0o600)
        with (root/"probe.log").open("wb") as log:
            process=subprocess.Popen([module.MIHOMO_BIN,"-d",str(root),"-f",str(cfg)],
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            try:
                # Suppress diagnostic output from the embedded scanner:
                # operator messages must never echo subscription credentials.
                import contextlib,io
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        module.wait_controller(process,controller_port,timeout=12)
                        loaded=module.wait_probe_inventory(process,controller_port,
                                            [rows[0]["probe_name"]],timeout=12)
                except (OSError,ValueError,subprocess.TimeoutExpired,SystemExit):
                    refuse("NATIVE_ISOLATED_PROBE_START_FAILED")
                if rows[0]["probe_name"] not in loaded:
                    refuse("NATIVE_ISOLATED_PROFILE_NOT_LOADED")
                ok,_,_=module.probe_delay(controller_port,rows[0])
                if not ok:
                    time.sleep(15)
                    ok,_,_=module.probe_delay(controller_port,rows[0])
                if not ok:refuse("NATIVE_ISOLATED_HTTPS_NOT_VERIFIED")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=3)
    if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=expected["sha"]:
        refuse("NATIVE_PROVIDER_CHANGED_DURING_PROBE")


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

def candidate_native(name):
    """Obtain the exact native profile/filter and resolved endpoint."""
    import ipaddress
    if not isinstance(name,str) or not 1<=len(name)<=240 or any(
        ch in name for ch in ("\n","\r","\x00")):
        refuse("INVALID_NATIVE_NAME")
    raw=read(PROVIDER)
    if raw is None or len(raw)>8*1024*1024:
        refuse("NATIVE_PROVIDER_UNAVAILABLE")
    try:data=yaml.safe_load(raw)
    except yaml.YAMLError:refuse("NATIVE_PROVIDER_PARSE_FAILED")
    rows=data.get("proxies",[]) if isinstance(data,dict) else []
    profiles=[n for n in rows if isinstance(n,dict) and n.get("name")==name]
    if len(profiles)!=1:refuse("NATIVE_PROFILE_NOT_UNIQUE")
    typ=profiles[0].get("type")
    if typ not in ("ss","trojan","hysteria2","vmess","vless"):
        refuse("NOT_A_NATIVE_MIHOMO_PROFILE")
    if typ=="vless" and profiles[0].get("network") in ("xhttp","grpc"):
        refuse("XRAY_PROFILE_IS_NOT_NATIVE")
    # Same trusted helper that native Mihomo's menu already uses.
    helper="/usr/local/lib/awg-pi/mihomo-provider.py"
    try:
        p=subprocess.run(["python3",helper,"info",str(PROVIDER),name],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=14,text=True)
    except (OSError,subprocess.TimeoutExpired):
        refuse("NATIVE_PROFILE_RESOLVE_FAILED")
    if p.returncode:refuse("NATIVE_PROFILE_RESOLVE_FAILED")
    try:
        info=json.loads(p.stdout)
        addr=str(ipaddress.IPv4Address(info["endpoint_ips"][0]))
        pattern=info["filter_regex"]
        if info.get("name")!=name or not isinstance(pattern,str) or not pattern or (
           len(pattern)>2048 or any(c in pattern for c in "\r\n\x00")):
            refuse("NATIVE_PROFILE_RESOLVE_FAILED")
    except (ValueError,KeyError,TypeError,IndexError):
        refuse("NATIVE_PROFILE_RESOLVE_FAILED")
    return {"candidate":name,"endpoint":addr,"filter":pattern,
            "sha":hashlib.sha256(raw).hexdigest()}

def native_env(key,value):
    """Update only an allowlisted env field with safe Bash quoting."""
    import shlex
    if key not in ("MIHOMO_NODE_FILTER","MIHOMO_ENDPOINT_IP",
                   "MIHOMO_XRAY_VLESS_BRIDGE","MIHOMO_EXPECTED_EGRESS_IP"):
        refuse("NATIVE_ENV_KEY_FORBIDDEN")
    raw=read(MIHOMO_ENV)
    if raw is None or len(raw)>131072:refuse("NATIVE_ENV_UNAVAILABLE")
    lines=raw.decode("utf-8").splitlines()
    matches=[i for i,line in enumerate(lines) if line.startswith(key+"=")]
    if len(matches)>1:refuse("NATIVE_ENV_DUPLICATE")
    if value is None:
        lines=[line for line in lines if not line.startswith(key+"=")]
    else:
        if not isinstance(value,str) or any(c in value for c in "\r\n\x00"):
            refuse("NATIVE_ENV_INVALID")
        entry=key+"="+shlex.quote(value)
        if matches:lines[matches[0]]=entry
        else:lines.append(entry)
    atomic(MIHOMO_ENV,("\n".join(lines)+"\n").encode())

def wait_native_controller(name):
    for _ in range(40):
        if unit_active(MIHOMO):
            try:
                group=controller()
                if name in group.get("all",[]):return
            except (OSError,ValueError,KeyError,TimeoutError):
                pass
        time.sleep(.5)
    refuse("NATIVE_CONTROLLER_NOT_READY")

def native_tun_proof():
    # Selective FAIL-OPEN intentionally removes the fwmark rule while the TUN
    # restarts. The independent health service restores it after a successful
    # transport health cycle; waiting for it is not the same as passing a TUN
    # HTTPS check. Transit re-arms synchronously through its guarded command.
    until=time.monotonic()+20
    while not routing_ok():
        if time.monotonic()>=until:
            refuse("NATIVE_ROUTING_NOT_RESTORED")
        time.sleep(.5)
    for attempt in range(2):
        if https_ok("tun"):return
        if attempt==0:time.sleep(1)
    refuse("NATIVE_TUN_HTTPS_UNVERIFIED")

def inspect_native(name):
    """One preflight for native→native and Xray→native, no mutation."""
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    target=candidate_native(name)
    invariant()
    con=controller()
    previous=con.get("now")
    if not isinstance(previous,str) or previous not in con.get("all",[]):
        refuse("ACTIVE_CONTROLLER_UNKNOWN")
    was_xray=previous==ALIAS
    xray_active=unit_active(XRAY)
    if was_xray and not xray_active:
        refuse("PREVIOUS_XRAY_DOWN")
    if not was_xray and xray_active:
        # A previously selected local sidecar may still be running after a
        # native controller switch. Treat it as managed only when the exact
        # installer-owned boot marker and selected fingerprint exist.
        if (not BOOT.is_file() or BOOT.is_symlink() or
             b"AWG_XRAY_MANUAL=1" not in BOOT.read_bytes() or
             read(SELECTED) is None):
            refuse("FOREIGN_XRAY_RUNNING")
    if BOOT.is_symlink() or (BOOT.exists() and
            b"AWG_XRAY_MANUAL=1" not in BOOT.read_bytes()):
        refuse("FOREIGN_BOOT_DEPENDENCY")
    if not https_ok("tun"):refuse("PREVIOUS_TUN_NOT_PROVEN")
    if was_xray:
        try:
            digest=json.loads(SELECTED.read_text()).get("sha256")
        except (ValueError,OSError,UnicodeError):
            refuse("PREVIOUS_XRAY_PROFILE_INVALID")
        if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
            refuse("PREVIOUS_XRAY_PROFILE_INVALID")
    configured=read(CURRENT)
    already=(not was_xray and previous==name and configured is not None and
            configured.decode("utf-8","replace").strip()==name)
    target.update({"previous":previous,"previous_xray":was_xray,
        "xray_enabled":unit_enabled(XRAY),"xray_active":xray_active,
        "operation":"NATIVE_SWITCH","already_selected":already})
    return target

def restore_native(path,state):
    """Watchdog-grade byte-for-byte restoration of native config and engine."""
    if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
        refuse("FOREIGN_TRANSPORT_DURING_RECOVERY")
    mode=MODE.read_text().strip()
    if mode=="transit":
        # The nft forward guard remains DROP while the TUN is absent.
        cmd("/usr/local/sbin/awg-transit-routing","disable")
    elif mode=="selective":
        # Preserve selective FAIL-OPEN behavior during controller restart.
        cmd("/usr/local/sbin/awg-pbr-failopen")
    else:refuse("INVALID_GATEWAY_MODE")
    cmd("systemctl","stop",MIHOMO)
    for label,dest in (("env.prev",MIHOMO_ENV),("config.prev",MIHOMO_CONFIG),
                       ("endpoint.prev",MIHOMO_ENDPOINT),("egress.prev",MIHOMO_EGRESS),
                       ("selected.prev",SELECTED),("current.prev",CURRENT),
                       ("boot.prev",BOOT),("policy.prev",POLICY),("order.prev",ORDER)):
        original=read(path/label)
        if original is None:dest.unlink(missing_ok=True)
        else:atomic(dest,original,0o644 if dest==BOOT else 0o600)
    cmd("systemctl","daemon-reload")
    if state["previous_xray"]:
        if not unit_active(XRAY):cmd("systemctl","start",XRAY)
        prove_local_xray()
    cmd("systemctl","start",MIHOMO,timeout=40)
    wait_native_controller(state["previous"])
    choose(state["previous"])
    if MODE.read_text().strip()=="transit":
        cmd("/usr/local/sbin/awg-transit-routing","apply")
    native_tun_proof()
    if not state["previous_xray"]:
        if state.get("xray_active") and not unit_active(XRAY):
            cmd("systemctl","start",XRAY)
        elif not state.get("xray_active") and unit_active(XRAY):
            cmd("systemctl","stop",XRAY)
    cmd("systemctl","enable" if state["xray_enabled"] else "disable",XRAY)
    invariant()

def native_return(name):
    """One guarded arbitrary manual native-target transition (either engine)."""
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        info=inspect_native(name)
        if info.get("already_selected"):
            print("NATIVE_MANUAL_ALREADY_SELECTED=YES")
            print("NATIVE_RETURN_TUN=EXISTING_HEALTHY_NOT_SWITCHED")
            return
        # A manual native target is qualified before live Mihomo is stopped.
        preflight_mihomo(name,info)
        path,state=save_snap(info)
        timer=state["watchdog"]+".timer"
        mutated=False
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):refuse("WATCHDOG_NOT_ARMED")
            stored(path,state,"armed")
            checkpoint(path,state,"VERIFY_NATIVE_CANDIDATE")
            fresh=candidate_native(name)
            if any(fresh[k]!=info[k] for k in ("candidate","endpoint","filter","sha")):
                refuse("NATIVE_PROVIDER_CHANGED")
            checkpoint(path,state,"NATIVE_RECONFIGURE")
            mutated=True
            # Transit must enter its existing nft-guarded FAIL-CLOSED state
            # before the Mihomo TUN disappears. No forwarded DIRECT escape.
            mode=MODE.read_text().strip()
            if mode=="transit":
                cmd("/usr/local/sbin/awg-transit-routing","disable")
            elif mode=="selective":
                cmd("/usr/local/sbin/awg-pbr-failopen")
            else:refuse("INVALID_GATEWAY_MODE")
            # Previous Xray SOCKS stays alive for rollback; Mihomo TUN will
            # briefly stop while its native provider filter is replaced.
            cmd("systemctl","stop",MIHOMO)
            native_env("MIHOMO_NODE_FILTER",info["filter"])
            native_env("MIHOMO_ENDPOINT_IP",info["endpoint"])
            native_env("MIHOMO_EXPECTED_EGRESS_IP",None)
            atomic(MIHOMO_ENDPOINT,(info["endpoint"]+"\n").encode())
            MIHOMO_EGRESS.unlink(missing_ok=True)
            atomic(CURRENT,(name+"\n").encode())
            cmd("/usr/local/sbin/awg-mihomo-prepare",timeout=45)
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=info["sha"]:
                refuse("NATIVE_PROVIDER_CHANGED")
            checkpoint(path,state,"NATIVE_START")
            cmd("systemctl","start",MIHOMO,timeout=40)
            wait_native_controller(name)
            checkpoint(path,state,"NATIVE_SELECT")
            choose(name)
            if MODE.read_text().strip()=="transit":
                checkpoint(path,state,"NATIVE_TRANSIT_REARM")
                cmd("/usr/local/sbin/awg-transit-routing","apply")
            checkpoint(path,state,"NATIVE_TUN_PROOF")
            native_tun_proof()
            invariant()
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=info["sha"]:
                refuse("NATIVE_PROVIDER_CHANGED_BEFORE_COMMIT")
            checkpoint(path,state,"NATIVE_COMMIT")
            if state["previous_xray"]:
                # Commit new native exit before detaching the standby sidecar.
                BOOT.unlink(missing_ok=True)
                SELECTED.unlink(missing_ok=True)
                cmd("systemctl","daemon-reload")
                cmd("systemctl","stop",XRAY)
                cmd("systemctl","disable",XRAY)
            checkpoint(path,state,"NATIVE_FINAL_VERIFY")
            if controller().get("now")!=name or (
                    state["previous_xray"] and unit_active(XRAY)):
                refuse("NATIVE_EXIT_MISMATCH")
            native_tun_proof()
            invariant()
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("NATIVE_RETURN_TUN=VERIFIED")
            print("ACTIVE_EXIT=MIHOMO_NATIVE")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
            print("NATIVE_RETURN_REBOOT=NOT_TESTED")
        except Exception as exc:
            state["failure_code"]=stable_error_code(exc)
            if state["failure_code"]=="NATIVE_TUN_HTTPS_UNVERIFIED":
                state["tun_probe_last"]=_LAST_HTTPS_PROBE_CLASS
            state["failed_at"]=state.get("checkpoint","NOT_STARTED")
            if not mutated:
                stored(path,state,"cancelled")
                try:cmd("systemctl","stop",timer)
                except Exception:pass
                raise
            try:checkpoint(path,state,"ROLLBACK_ATTEMPT")
            except Exception:pass
            try:
                restore_native(path,state)
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


def dead_xray_xray(index):
    """Recover failed Xray->different Xray without reviving the broken one.

    Preserves provider identity, uses the exact isolated HTTPS preflight,
    arms an independent watchdog, and only commits after live Mihomo TUN
    HTTPS/OpenAI 401, guarded transit/Selective policy and sidecar fingerprint.
    """
    if os.geteuid()!=0:
        raise DeadXrayPreflight("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
                refuse("ACTIVE_TRANSPORT_NOT_MIHOMO")
            if MODE.read_text().strip() not in ("transit","selective"):
                refuse("INVALID_GATEWAY_MODE")
            if not all(unit_active(x) for x in ("ssh.service","dnsmasq.service")):
                refuse("MANAGEMENT_CHANNEL_NOT_HEALTHY")
            dead_xray_owned_bridge()
            con=controller()
            if con.get("now")!=ALIAS:
                refuse("FAILED_XRAY_BRIDGE_NOT_SELECTED")
            if https_ok("tun"):
                refuse("PREVIOUS_TUN_STILL_HEALTHY")
            candidate,sha,fingerprint=source_node(index)
            prior=json.loads(SELECTED.read_text())
            if prior.get("sha256")==fingerprint:
                refuse("FAILED_XRAY_CANDIDATE_REUSED")
            info={"operation":"DEAD_XRAY_XRAY","previous":ALIAS,
                  "previous_xray":True,"candidate":candidate,
                  "sha":sha,"fingerprint":fingerprint,
                  "xray_enabled":unit_enabled(XRAY)}
            preflight_xray(index,info)
            if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
                refuse("TRANSPORT_CHANGED_DURING_PREFLIGHT")
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
            raise DeadXrayPreflight(stable_error_code(exc)) from None

        path,state=save_snap(info)
        timer=state["watchdog"]+".timer"
        armed=False
        mutated=False
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):
                refuse("WATCHDOG_NOT_ARMED")
            armed=True
            stored(path,state,"armed")
            checkpoint(path,state,"QUIESCE_DEAD_XRAY")
            mutated=True
            dead_xray_quiesce()
            checkpoint(path,state,"SELECT_XRAY_CANDIDATE")
            if source_node(index)!=(candidate,sha,fingerprint):
                refuse("XRAY_PROVIDER_CHANGED")
            cmd(str(ADAPTER),"select",str(index))
            cmd("systemctl","start",XRAY,timeout=35)
            prove_local_xray()
            checkpoint(path,state,"START_MIHOMO_BRIDGE")
            # The old sidecar bridge has been removed; explicitly build a
            # new owned one only after the new SOCKS HTTPS is verified.
            # Persistent bridge state belongs to an owned systemd drop-in,
            # never to provider.env: manual Xray->native must stay possible.
            native_env("MIHOMO_XRAY_VLESS_BRIDGE","auto")
            native_env("MIHOMO_EXPECTED_EGRESS_IP",None)
            MIHOMO_EGRESS.unlink(missing_ok=True)
            BOOT.parent.mkdir(parents=True,mode=0o755,exist_ok=True)
            atomic(BOOT,b'[Unit]\nWants=awg-xray-vless.service\nAfter=awg-xray-vless.service\n# AWG_XRAY_MANUAL=1\n[Service]\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n',0o644)
            cmd("systemctl","daemon-reload")
            # ExecStartPre renders the bridge using the owned drop-in
            # Environment; running prepare outside systemd would not see it.
            cmd("systemctl","start",MIHOMO,timeout=45)
            wait_native_controller(ALIAS)
            choose(ALIAS)
            if MODE.read_text().strip()=="transit":
                cmd("/usr/local/sbin/awg-transit-routing","apply")
            checkpoint(path,state,"VERIFY_NEW_XRAY_TUN")
            native_tun_proof()
            invariant()
            if source_node(index)!=(candidate,sha,fingerprint):
                refuse("XRAY_PROVIDER_CHANGED_BEFORE_COMMIT")
            if not unit_active(XRAY) or controller().get("now")!=ALIAS:
                refuse("XRAY_POSTCHECK_ENGINE_MISMATCH")
            now=json.loads(SELECTED.read_text())
            if now.get("sha256")!=fingerprint:
                refuse("XRAY_COMMIT_FINGERPRINT_MISMATCH")
            atomic(CURRENT,(candidate+"\n").encode())
            cmd("systemctl","enable",XRAY)
            native_tun_proof()
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("DEAD_XRAY_XRAY_TUN=VERIFIED")
        except Exception as exc:
            state["failure_code"]=stable_error_code(exc)
            if mutated:
                try:
                    dead_xray_quiesce()
                    stored(path,state,"rolled_back")
                    if armed:cmd("systemctl","stop",timer)
                except Exception:
                    raise DeadXrayAbort("DEAD_XRAY_WATCHDOG_PENDING") from None
            else:
                stored(path,state,"cancelled")
                if armed:
                    try:cmd("systemctl","stop",timer)
                    except Exception:pass
            raise DeadXrayAbort(stable_error_code(exc)) from None


class DeadXrayPreflight(RuntimeError):
    """No active state was changed: next distinct candidate may be attempted."""

class DeadXrayAbort(RuntimeError):
    """Fail closed/open under existing gateway policy, then permit AWG fallback."""

def dead_xray_owned_bridge():
    """Never detach an unrelated systemd override or a foreign sidecar."""
    for overlay,signature in (
        (Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
         b"MIHOMO_XRAY_VLESS_BRIDGE=1"),
        (Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
         b"MIHOMO_XRAY_VLESS_BRIDGE=1"),
        (BOOT,b"AWG_XRAY_MANUAL=1")):
        if overlay.is_symlink() or (overlay.exists() and (
                not overlay.is_file() or signature not in overlay.read_bytes())):
            refuse("FOREIGN_XRAY_BOOT_DEPENDENCY")
    if SELECTED.is_symlink() or not SELECTED.is_file() or SELECTED.stat().st_uid!=0:
        refuse("XRAY_BRIDGE_SELECTION_UNOWNED")

def dead_xray_quiesce():
    """A failed Xray is NEVER an acceptable rollback; leave a guarded outage.

    Called while the gateway maintenance lock is held. If AWG already took
    over, preserve its live route, SSTP management and SSH untouched.
    """
    current=cmd("/usr/local/sbin/awg-transport","get")
    if current=="awg" and cmd("/usr/local/sbin/awg-transport","check","awg")=="healthy":
        return
    if current!="mihomo":
        refuse("FOREIGN_TRANSPORT_DURING_RECOVERY")
    mode=MODE.read_text().strip()
    if mode=="transit":
        cmd("/usr/local/sbin/awg-transit-routing","disable")
    elif mode=="selective":
        cmd("/usr/local/sbin/awg-pbr-failopen")
    else:
        refuse("INVALID_GATEWAY_MODE")
    cmd("systemctl","stop",MIHOMO,timeout=35)
    cmd("systemctl","stop",XRAY,timeout=25)
    for overlay in (
        Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
        Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
        BOOT):
        # Do not delete foreign overlays if another component changed them.
        if overlay.exists() or overlay.is_symlink():
            dead_xray_owned_bridge()
            overlay.unlink()
    SELECTED.unlink(missing_ok=True)
    cmd("systemctl","disable",XRAY)
    cmd("systemctl","daemon-reload")
    if unit_active(MIHOMO):
        refuse("UNVERIFIED_BACKEND_NOT_QUIESCED")
    if not all(unit_active(x) for x in ("ssh.service","dnsmasq.service")):
        refuse("MANAGEMENT_CHANNEL_NOT_HEALTHY")

def dead_xray_native(name):
    """Guarded AUTO repair of a confirmed dead Xray bridge to one native exit.

    Does not reuse healthy-old-TUN manual switching, since old Xray is dead.
    Return 2 only for pre-mutation rejection, 1 for failed recovery requiring
    AWG, and 0 only after a newly selected real Mihomo TUN passes HTTPS 401.
    """
    if os.geteuid()!=0:
        raise DeadXrayPreflight("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
                refuse("ACTIVE_TRANSPORT_NOT_MIHOMO")
            if MODE.read_text().strip() not in ("transit","selective"):
                refuse("INVALID_GATEWAY_MODE")
            if not all(unit_active(x) for x in ("ssh.service","dnsmasq.service")):
                refuse("MANAGEMENT_CHANNEL_NOT_HEALTHY")
            dead_xray_owned_bridge()
            con=controller()
            if con.get("now")!=ALIAS or ALIAS not in con.get("all",[]):
                refuse("FAILED_XRAY_BRIDGE_NOT_SELECTED")
            if https_ok("tun"):
                refuse("PREVIOUS_TUN_STILL_HEALTHY")
            target=candidate_native(name)
            preflight_mihomo(name,target)
            if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
                refuse("TRANSPORT_CHANGED_DURING_PREFLIGHT")
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=target["sha"]:
                refuse("PROVIDER_CHANGED_DURING_PREFLIGHT")
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
            raise DeadXrayPreflight(stable_error_code(exc)) from None

        target.update({"operation":"DEAD_XRAY_NATIVE","previous_xray":True,
                       "previous":ALIAS,"xray_enabled":unit_enabled(XRAY)})
        path,state=save_snap(target)
        timer=state["watchdog"]+".timer"
        armed=False
        mutated=False
        try:
            cmd("systemd-run","--unit="+state["watchdog"],
                "--on-active="+str(WATCH_SECONDS)+"s",str(SWITCH),
                "watchdog",str(path))
            if not unit_active(timer):
                refuse("WATCHDOG_NOT_ARMED")
            armed=True
            stored(path,state,"armed")
            checkpoint(path,state,"QUIESCE_DEAD_XRAY")
            mutated=True
            dead_xray_quiesce()
            checkpoint(path,state,"STAGE_NATIVE")
            fresh=candidate_native(name)
            if any(fresh[k]!=target[k] for k in ("candidate","endpoint","filter","sha")):
                refuse("NATIVE_PROVIDER_CHANGED")
            # Enforce a native renderer, not even an optional stale SOCKS alias.
            native_env("MIHOMO_XRAY_VLESS_BRIDGE","auto")
            native_env("MIHOMO_NODE_FILTER",target["filter"])
            native_env("MIHOMO_ENDPOINT_IP",target["endpoint"])
            native_env("MIHOMO_EXPECTED_EGRESS_IP",None)
            atomic(MIHOMO_ENDPOINT,(target["endpoint"]+"\n").encode())
            MIHOMO_EGRESS.unlink(missing_ok=True)
            atomic(CURRENT,(name+"\n").encode())
            cmd("/usr/local/sbin/awg-mihomo-prepare",timeout=45)
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=target["sha"]:
                refuse("PROVIDER_CHANGED_DURING_NATIVE_STAGE")
            checkpoint(path,state,"START_NATIVE")
            cmd("systemctl","start",MIHOMO,timeout=45)
            wait_native_controller(name)
            choose(name)
            if MODE.read_text().strip()=="transit":
                cmd("/usr/local/sbin/awg-transit-routing","apply")
            checkpoint(path,state,"VERIFY_NATIVE_TUN")
            native_tun_proof()
            invariant()
            if controller().get("now")!=name or unit_active(XRAY):
                refuse("NATIVE_POSTCHECK_ENGINE_MISMATCH")
            if SELECTED.exists() or BOOT.exists():
                refuse("DEAD_XRAY_METADATA_PERSISTED")
            if hashlib.sha256(PROVIDER.read_bytes()).hexdigest()!=target["sha"]:
                refuse("PROVIDER_CHANGED_BEFORE_COMMIT")
            stored(path,state,"committed")
            cmd("systemctl","stop",timer)
            print("DEAD_XRAY_NATIVE_TUN=VERIFIED")
            print("MIHOMO_NODE_POLICY=UNCHANGED")
        except Exception as exc:
            state["failure_code"]=stable_error_code(exc)
            state["failed_at"]=state.get("checkpoint","NOT_STARTED")
            if mutated:
                try:
                    dead_xray_quiesce()
                    stored(path,state,"rolled_back")
                    if armed:
                        cmd("systemctl","stop",timer)
                except Exception:
                    # Watchdog remains ARMED; never restore broken Xray.
                    raise DeadXrayAbort("DEAD_XRAY_WATCHDOG_PENDING") from None
            else:
                stored(path,state,"cancelled")
                if armed:
                    try:cmd("systemctl","stop",timer)
                    except Exception:pass
            raise DeadXrayAbort(stable_error_code(exc)) from None

def save_snap(info):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=ROOT/("xray-manual-"+str(int(time.time()))+"-"+str(os.getpid()))
    path.mkdir(mode=0o700)
    state={"phase":"pending",**info,"watchdog": "awg-xray-manual-"+str(os.getpid())}
    atomic(path/"state.json",json.dumps(state).encode())
    for name,source in (("selected.prev",SELECTED),("current.prev",CURRENT),
                        ("policy.prev",POLICY),("order.prev",ORDER),
                        ("boot.prev",BOOT),("env.prev",MIHOMO_ENV),
                        ("config.prev",MIHOMO_CONFIG),
                        ("endpoint.prev",MIHOMO_ENDPOINT),("egress.prev",MIHOMO_EGRESS)):
        data=read(source)
        if data is not None:atomic(path/name,data)
    return path,state

def stored(path,state,phase):
    state["phase"]=phase
    atomic(path/"state.json",json.dumps(state).encode())

def restore(path,state):
    if state.get("operation")=="NATIVE_SWITCH":
        return restore_native(path,state)
    # A separately selected healthy AWG must never be replaced by the watchdog.
    if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
        refuse("FOREIGN_TRANSPORT_DURING_RECOVERY")
    previous=state["previous"]
    # An arbitrary native candidate may have rewritten the Mihomo provider
    # filter and config, so restore those bytes BEFORE selecting previous Xray.
    if state.get("operation")=="NATIVE_RETURN" and state.get("native_reconfigured"):
        for name,target in (("env.prev",MIHOMO_ENV),("config.prev",MIHOMO_CONFIG),
                            ("endpoint.prev",MIHOMO_ENDPOINT),
                            ("egress.prev",MIHOMO_EGRESS),
                            ("current.prev",CURRENT),("boot.prev",BOOT),
                            ("selected.prev",SELECTED)):
            data=read(path/name)
            if data is None:target.unlink(missing_ok=True)
            else:atomic(target,data,0o644 if target==BOOT else 0o600)
        cmd("systemctl","daemon-reload")
        cmd("systemctl","restart",MIHOMO,timeout=90)
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
        # Routes can lag after restoring the incumbent node.
        native_tun_proof()
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
        if state.get("operation") in ("DEAD_XRAY_NATIVE","DEAD_XRAY_XRAY"):
            if state["phase"]=="pending":
                stored(path,state,"cancelled")
                return
            dead_xray_quiesce()
            stored(path,state,"rolled_back")
            return
        if state["phase"]=="pending":
            stored(path,state,"cancelled")
            return
        # AUTO may have selected healthy AWG while the manual transaction failed.
        # Never overwrite that transport or leave a failing recovery unit.
        active_transport=cmd("/usr/local/sbin/awg-transport","get")
        if active_transport=="awg" and cmd(
                "/usr/local/sbin/awg-transport","check","awg")=="healthy":
            stored(path,state,"superseded")
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
        # Fresh on-demand HTTPS test comes before snapshot/watchdog and,
        # critically, before stopping the current Xray process.
        preflight_xray(index,info)
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
            # Third independent leg of the proof chain:
            # (1) Xray SOCKS was already HTTPS-proven before this selection;
            # (2) Mihomo's own mixed proxy now tests the selected Xray alias;
            # (3) ONLY the subsequent mihomo0 bound-TUN 401 can commit.
            # An unsuccessful mixed proxy diagnostic never passes OR vetoes
            # a healthy TUN; it is recorded solely for failure isolation.
            state["mixed_probe_last"]="NOT_RUN"
            mixed_ok=https_ok("mixed")
            state["mixed_probe_last"]=_LAST_HTTPS_PROBE_CLASS
            # This remains the sole approval for real TUN HTTPS:
            native_tun_proof()
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
            if not unit_enabled(XRAY):
                refuse("XRAY_POSTCOMMIT_SERVICE_NOT_ENABLED")
            native_tun_proof()
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
            if state["failure_code"]=="NATIVE_TUN_HTTPS_UNVERIFIED":
                state["tun_probe_last"]=_LAST_HTTPS_PROBE_CLASS
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
    for key in ("phase","failure_code","failed_at","rollback_failure_code","checkpoint","tun_probe_last","mixed_probe_last"):
        value=state.get(key,"UNKNOWN")
        safe=value if isinstance(value,str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}|rolled_back|committed|armed|pending|cancelled",value) else "UNKNOWN"
        print("XRAY_MANUAL_"+key.upper()+"="+safe)

def dead_xray_exhausted():
    """Quiesce only the failed Xray-owned exit after FULL current-provider scan.

    A provider scan can find no viable node while the independently healthy AWG
    is still standby. Do not leave a broken TUN managing Selective/Transit.
    This function is never called from the manual picker or subscription scan.
    """
    if os.geteuid()!=0:refuse("ROOT_REQUIRED")
    with LOCK.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if cmd("/usr/local/sbin/awg-transport","get")!="mihomo":
            refuse("ACTIVE_TRANSPORT_NOT_MIHOMO")
        dead_xray_owned_bridge()
        if controller().get("now")!=ALIAS:
            refuse("CURRENT_XRAY_ALIAS_NOT_SELECTED")
        if https_ok("tun"):
            refuse("CURRENT_XRAY_TUN_HEALTHY")
        dead_xray_quiesce()
        print("DEAD_XRAY_EXHAUSTED=QUIESCED_SAFE")


def fresh_candidate_probe(engine,value):
    """No gateway mutation: exact provider, independent engine, HTTPS only."""
    if os.geteuid()!=0:
        refuse("ROOT_REQUIRED")
    if engine=="native":
        info=candidate_native(value)
        preflight_mihomo(value,info)
    elif engine=="xray":
        if not re.fullmatch(r"[1-9][0-9]{0,4}",value):
            refuse("INVALID_NODE_INDEX")
        index=int(value)
        candidate,sha,fingerprint=source_node(index)
        preflight_xray(index,{"candidate":candidate,"sha":sha,
                              "fingerprint":fingerprint})
    else:
        refuse("INVALID_ENGINE")
    print("FRESH_CANDIDATE_PROOF=PASS_NO_MUTATION")


def main():
    if len(sys.argv)==2 and sys.argv[1]=="dead-xray-exhausted":
        dead_xray_exhausted()
        return
    if len(sys.argv)==3 and sys.argv[1] in ("probe-native","probe-xray"):
        fresh_candidate_probe("native" if sys.argv[1]=="probe-native" else "xray",sys.argv[2])
        return
    if len(sys.argv)==3 and sys.argv[1]=="dead-xray-xray":
        if not re.fullmatch(r"[1-9][0-9]{0,4}",sys.argv[2]):
            raise SystemExit(2)
        try:
            dead_xray_xray(int(sys.argv[2]))
        except DeadXrayPreflight as exc:
            print("DEAD_XRAY_XRAY_REJECT="+stable_error_code(exc),file=sys.stderr)
            raise SystemExit(2)
        except DeadXrayAbort as exc:
            print("DEAD_XRAY_XRAY_ABORT="+stable_error_code(exc),file=sys.stderr)
            raise SystemExit(1)
        return
    if len(sys.argv)==3 and sys.argv[1]=="dead-xray-native":
        try:
            dead_xray_native(sys.argv[2])
        except DeadXrayPreflight as exc:
            print("DEAD_XRAY_NATIVE_REJECT="+stable_error_code(exc),file=sys.stderr)
            raise SystemExit(2)
        except DeadXrayAbort as exc:
            print("DEAD_XRAY_NATIVE_ABORT="+stable_error_code(exc),file=sys.stderr)
            raise SystemExit(1)
        return
    if len(sys.argv)==3 and sys.argv[1] in ("native-preview","native-apply"):
        if sys.argv[1]=="native-preview":
            candidate=inspect_native(sys.argv[2])
            print("NATIVE_RETURN_PREFLIGHT=PASS")
            if candidate["already_selected"]:
                print("NATIVE_MANUAL_ALREADY_SELECTED=YES")
                print("NATIVE_RETURN_TUN=EXISTING_HEALTHY_NOT_SWITCHED")
            else:print("NATIVE_RETURN_TUN=NOT_TESTED")
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
