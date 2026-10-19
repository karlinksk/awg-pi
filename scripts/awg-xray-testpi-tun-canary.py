#!/usr/bin/env python3
"""Authorized real test-Pi Mihomo-TUN VLESS transaction, fail closed, watchdog rollback."""
import fcntl,hashlib,json,os,pathlib,shutil,socket,subprocess,sys,tempfile,time,urllib.request
import yaml

BASE=pathlib.Path("/var/backups/awg-gateway")
CONF=pathlib.Path("/etc/awg-pbr/transports/mihomo/config.yaml")
SELECTED=pathlib.Path("/var/lib/awg-pbr/xray-vless/selected.json")
PROVIDER=pathlib.Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
ROOT=pathlib.Path(__file__).resolve().parents[1]
RENDER=ROOT/"src/awg-mihomo-config"
FIXED=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
CURRENT=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-name")
UNIFIED=pathlib.Path("/usr/local/sbin/awg-mihomo-unified-nodes")
ROLLBACK_SOURCE=ROOT/"scripts/awg-xray-testpi-tun-rollback.py"
ROLLBACK_RUNTIME=pathlib.Path("/run/awg-pbr/xray-live-canary-rollback.py")
LIVE_RENDERER=pathlib.Path("/usr/local/sbin/awg-mihomo-config")
OVERRIDE=pathlib.Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf")
BRIDGE_PERSISTENT=pathlib.Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
BRIDGE_RUNTIME=pathlib.Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
CORE=pathlib.Path("/usr/local/bin/mihomo")
TIMER_NAME="awg-xray-live-rollback-"+str(os.getpid())
XUNIT="awg-xray-vless.service"
MUNIT="awg-mihomo.service"
GROUP="AWG-MIHOMO"
LOCAL="AWG-XRAY-VLESS-LOCAL"
def proc(a,timeout=30,env=None):
 return subprocess.run(a,capture_output=True,text=True,timeout=timeout,env=env)
def require(ok,label):
 if not ok:raise RuntimeError(label)
def status():
 return json.load(urllib.request.urlopen("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=4))
def choose(name):
 req=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO",
  method="PUT",data=json.dumps({"name":name}).encode(),headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=5) as r:
  require(r.status in (200,204),"CONTROLLER_PUT_FAILED")
 require(status().get("now")==name,"CONTROLLER_SELECTION_NOT_CONFIRMED")
def https(target=None):
 a=["curl","-4","-sS","--noproxy","*", "--connect-timeout","7","--max-time","19",
    "-o","/dev/null","-w","%{http_code}","https://api.openai.com/v1/models"]
 if target is not None:
  a[1:1]=["--interface",target]
 r=proc(a,timeout=24)
 return r.returncode==0 and r.stdout=="401"
def socks():
 a=["curl","-4","-sS","--socks5-hostname","127.0.0.1:17892","--noproxy","",
    "--connect-timeout","8","--max-time","19",
    "-o","/dev/null","-w","%{http_code}","https://api.openai.com/v1/models"]
 r=proc(a,timeout=24)
 return r.returncode==0 and r.stdout=="401"
def resolve_fixed_xray(candidate, provider_sha):
 resolved=proc([str(UNIFIED),"resolve",candidate],timeout=12)
 require(resolved.returncode==0,"XRAY_CANDIDATE_NOT_RESOLVABLE")
 fields=dict(line.split("=",1) for line in resolved.stdout.splitlines() if "=" in line)
 require(fields.get("NODE_ENGINE")=="XRAY" and fields.get("NODE_BASIC_NETWORK")=="NETWORK_OK",
         "XRAY_CANDIDATE_NOT_NETWORK_QUALIFIED")
 require(fields.get("NODE_PROVIDER_SHA256")==provider_sha,"XRAY_PROVIDER_ROTATED")
 ix=fields.get("NODE_INDEX","")
 require(ix.isdigit() and int(ix)>=1,"XRAY_INDEX_INVALID")
 return ix

def restored_config_proof(saved,current,baseline_sha):
 """Verify the saved bytes first; permit only YAML-equivalent re-rendering.

 Mihomo ExecStartPre can rewrite ordering/comments after a restart.
 Neither changed VPN settings nor a corrupted snapshot may pass.
 """
 baseline=saved.read_bytes()
 live=current.read_bytes()
 if hashlib.sha256(baseline).hexdigest()!=baseline_sha:
  return "BACKUP_HASH_INVALID"
 if hashlib.sha256(live).hexdigest()==baseline_sha:
  return "BYTE_IDENTICAL"
 try:
  a=yaml.safe_load(baseline)
  b=yaml.safe_load(live)
  if isinstance(a,dict) and a==b:
   return "YAML_EQUIVALENT"
 except (yaml.YAMLError,ValueError,UnicodeDecodeError):
  pass
 return "CONFIG_DIFFERENT"

def mode_id():
 # Read only the root-protected mode state: awg-route CLI acquires the
 # maintenance flock and can fail when the canary itself owns that lock.
 value=pathlib.Path("/etc/awg-pbr/mode").read_text().strip()
 return value if value in ("transit","selective") else "INVALID"
def check_routes():
 for t in ("100","101"):
  p=proc(["ip","route","show","table",t])
  require(p.returncode==0 and "default dev mihomo0" in p.stdout,"ROUTE_TABLE_"+t+"_CHANGED")
def restore_kernel_tun_routes():
 # Restarting Mihomo recreates mihomo0; Linux removes routes bound to the
 # old netdev. Recreate ONLY the two defaults proven present at preflight.
 # Never add/move a MikroTik rule, fwmark or active transport.
 for t in ("100","101"):
  p=proc(["ip","route","show","table",t],timeout=6)
  require(p.returncode==0,"IP_ROUTE_SHOW_FAILED")
  if "default dev mihomo0" in p.stdout:continue
  require(not p.stdout.strip(),"UNEXPECTED_ROUTE_TABLE_CONTENT_"+t)
  updated=proc(["ip","route","replace","table",t,"default","dev","mihomo0"],timeout=8)
  require(updated.returncode==0,"TUN_DEFAULT_ROUTE_RESTORE_FAILED_"+t)
  print("TUN_TABLE_"+t+"_DEFAULT_REINSTATED=YES",flush=True)
 check_routes()
def wait_mihomo():
 for _ in range(48):
  if proc(["systemctl","is-active","--quiet",MUNIT],timeout=3).returncode==0:
   try:
    d=status()
    if isinstance(d,dict) and LOCAL in d.get("all",[]):return d
   except Exception:pass
  time.sleep(.22)
 raise RuntimeError("MIHOMO_CONTROLLER_NO_XRAY_OUTBOUND")
def main():
 require(os.geteuid()==0 and len(sys.argv)==2 and sys.argv[1]=="--confirm-live-transit",
         "EXPLICIT_CONFIRM_REQUIRED")
 require(proc(["hostname"]).stdout.strip()=="awg-upgrade","NOT_TEST_PI")
 require(mode_id()=="transit","TRANSIT_MODE_CHANGED")
 require(proc(["/usr/local/sbin/awg-transport","status"]).stdout.find("Transport ID: mihomo")>=0,
         "MIHOMO_NOT_ACTIVE")
 require(proc(["systemctl","is-active","--quiet",MUNIT]).returncode==0,"MIHOMO_NOT_RUNNING")
 require(proc(["systemctl","is-active","--quiet","awg-selection-monitor.service"]).returncode==0,
         "MONITOR_NOT_RUNNING")
 require(proc(["systemctl","is-active","--quiet",XUNIT]).returncode!=0,"XRAY_ALREADY_RUNNING")
 require(proc(["systemctl","is-enabled","--quiet",XUNIT]).returncode!=0,"XRAY_AUTOSTART_UNEXPECTED")
 require(not SELECTED.exists(),"XRAY_PREVIOUS_SELECTION_PRESENT")
 require(RENDER.is_file() and CORE.is_file() and PROVIDER.is_file() and LIVE_RENDERER.is_file(),"SOURCE_MISSING")
 require(not OVERRIDE.exists() and not BRIDGE_RUNTIME.exists() and not BRIDGE_PERSISTENT.exists(),
         "XRAY_BRIDGE_ALREADY_INSTALLED")
 guard=proc(["/usr/local/sbin/awg-transit-routing","status"],timeout=10)
 require(guard.returncode==0 and all(line in guard.stdout.splitlines() for line in
         ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
         "TRANSIT_GUARD_NOT_SAFE")
 require(hashlib.sha256(RENDER.read_bytes()).hexdigest()==hashlib.sha256(LIVE_RENDERER.read_bytes()).hexdigest(),
         "INSTALLED_RENDERER_SOURCE_MISMATCH")
 policy=proc(["/usr/local/sbin/awg-mihomo-node-policy","auto-strategy","status"]).stdout
 require("MIHOMO_NODE_POLICY=fixed" in policy and "MIHOMO_READY_AUTO=0" in policy,"POLICY_CHANGED")
 check_routes()
 fixed=FIXED.read_text().splitlines()
 require(len(fixed)>=4 and len(fixed)==len(set(fixed)) and CURRENT.read_text().strip() in fixed,
         "FIXED_NODE_STATE_UNEXPECTED")
 candidate=fixed[-1]
 require(candidate!=CURRENT.read_text().strip(),"FIXED_LAST_IS_ACTIVE")
 before_config_hash=hashlib.sha256(CONF.read_bytes()).hexdigest()
 before_provider_hash=hashlib.sha256(PROVIDER.read_bytes()).hexdigest()
 require(https("mihomo0"),"BASELINE_TUN_HTTPS_FAILED")
 original=status()
 chosen=original.get("now")
 require(isinstance(chosen,str) and chosen in original.get("all",[]),"OLD_SELECTION_UNAVAILABLE")
 require(chosen==CURRENT.read_text().strip(),"CURRENT_SELECTED_NODE_MISMATCH")
 with (pathlib.Path("/run/awg-maintenance.lock")).open("a") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  snap=BASE/("xray-live-switch-"+time.strftime("%Y%m%d-%H%M%S"))
  snap.mkdir(mode=0o700)
  (snap/"config.previous").write_bytes(CONF.read_bytes())
  (snap/"config.previous").chmod(0o600)
  (snap/"renderer.previous").write_bytes(LIVE_RENDERER.read_bytes())
  (snap/"renderer.previous").chmod(0o600)
  initial={"state":"armed","selection_preexisting":False,"previous_group":chosen,
           "renderer_preexisting":True,"old_renderer_sha256":hashlib.sha256(LIVE_RENDERER.read_bytes()).hexdigest(),
           "mode":"transit","old_config_sha256":before_config_hash}
  (snap/"state.json").write_text(json.dumps(initial));(snap/"state.json").chmod(0o600)
  require(ROLLBACK_SOURCE.is_file(),"ROLLBACK_SOURCE_MISSING")
  ROLLBACK_RUNTIME.parent.mkdir(parents=True,exist_ok=True)
  rollback_tmp=ROLLBACK_RUNTIME.with_name("."+ROLLBACK_RUNTIME.name+".canary-"+str(os.getpid()))
  rollback_tmp.write_bytes(ROLLBACK_SOURCE.read_bytes());rollback_tmp.chmod(0o700)
  os.replace(rollback_tmp,ROLLBACK_RUNTIME)
  timeout_unit=TIMER_NAME
  watchdog=proc(["systemd-run","--unit="+timeout_unit,"--on-active=300s",
   "/usr/bin/python3","-B","/run/awg-pbr/xray-live-canary-rollback.py",str(snap)],timeout=12)
  require(watchdog.returncode==0,"ROLLBACK_TIMER_CREATION_FAILED")
  require(proc(["systemctl","is-active","--quiet",timeout_unit+".timer"]).returncode==0,
          "ROLLBACK_TIMER_NOT_ACTIVE")
  print("ROLLBACK_WATCHDOG=ARMED_300S",flush=True)
  phase="discover"
  try:
   ix=resolve_fixed_xray(candidate,before_provider_hash)
   phase="xray_selection"
   selected=proc(["/usr/local/sbin/awg-xray-vless","select",ix])
   require(selected.returncode==0,"XRAY_SELECT_FAILED")
   phase="xray_start"
   xr=proc(["systemctl","start",XUNIT],timeout=18)
   require(xr.returncode==0,"XRAY_SERVICE_START_FAILED")
   phase="xray_https"
   for attempt in range(1,4):
    if socks():break
    print("XRAY_SIDECAR_CONNECT_RETRY="+str(attempt),flush=True)
    time.sleep(1.0)
   else:raise RuntimeError("XRAY_SOCKS_HTTPS_NOT_READY")
   print("XRAY_SIDECAR_NETWORK=PASS_401",flush=True)
   phase="config_render"
   env=os.environ.copy();env["MIHOMO_XRAY_VLESS_BRIDGE"]="1"
   env["MIHOMO_XRAY_SELECTED"]=str(SELECTED)
   with tempfile.TemporaryDirectory(prefix="awg-live-xray-config-",dir="/run") as d:
    temp=pathlib.Path(d)
    rendered=proc(["bash",str(RENDER)],env=env,timeout=12)
    require(rendered.returncode==0,"RENDER_FAILED")
    (temp/"config.yaml").write_text(rendered.stdout)
    (temp/"config.yaml").chmod(0o600)
    validate=proc([str(CORE),"-t","-d","/var/lib/awg-pbr/mihomo","-f",str(temp/"config.yaml")],timeout=13)
    require(validate.returncode==0,"MIHOMO_CONFIG_TEST_FAILED")
    print("MIHOMO_XRAY_CONFIGURATION_TEST=PASS",flush=True)
    content=yaml.safe_load(rendered.stdout)
    require(content.get("tun",{}).get("device")=="mihomo0","TUN_DEVICE_MISMATCH")
    require(any(p.get("name")==LOCAL and p.get("server")=="127.0.0.1" and p.get("udp")==False
        for p in content.get("proxies",[])),"XRAY_OUTBOUND_MISSING")
    require(hashlib.sha256(PROVIDER.read_bytes()).hexdigest()==before_provider_hash,
            "PROVIDER_CHANGED_DURING_RENDER")
   # The production Mihomo unit runs awg-mihomo-prepare as ExecStartPre.
   # Install the versioned renderer temporarily, and expose an opt-in flag
   # through a /run-only systemd drop-in; let ExecStartPre regenerate and
   # validate the actual live config instead of bypassing the installer.
   phase="renderer_stage"
   OVERRIDE.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   OVERRIDE.write_text('[Service]\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n')
   OVERRIDE.chmod(0o600)
   reload=proc(["systemctl","daemon-reload"],timeout=22)
   require(reload.returncode==0,"DAEMON_RELOAD_FAILED")
   envshow=proc(["systemctl","show",MUNIT,"-p","Environment"]).stdout
   require("MIHOMO_XRAY_VLESS_BRIDGE=1" in envshow,"CANARY_UNIT_ENVIRONMENT_NOT_APPLIED")
   phase="mihomo_restart"
   restarted=proc(["systemctl","restart",MUNIT],timeout=25)
   require(restarted.returncode==0,"ACTIVE_MIHOMO_RESTART_FAILED")
   group=wait_mihomo()
   restore_kernel_tun_routes()
   require(LOCAL in group["all"],"XRAY_LOCAL_NOT_IN_LIVE_GROUP")
   # Ensure the live ExecStartPre persisted the opt-in outlet, not a
   # stale config served briefly by an old controller.
   staged_live=yaml.safe_load(CONF.read_text())
   require(any(p.get("name")==LOCAL for p in staged_live.get("proxies",[])),
           "LIVE_EXECSTARTPRE_RENDERER_DID_NOT_INSTALL_BRIDGE")
   print("LIVE_EXECSTARTPRE_XRAY_OUTBOUND=PASS",flush=True)
   phase="tun_xray_select"
   choose(LOCAL)
   phase="tun_xray_https"
   require(https("mihomo0"),"LIVE_MIHOMO_TUN_XRAY_HTTPS_FAILED")
   check_routes()
   print("LIVE_TUN_VLESS=PASS_401",flush=True)
   phase="tun_hy2_select"
   choose(chosen)
   phase="tun_hy2_https"
   require(https("mihomo0"),"LIVE_MIHOMO_TUN_HY2_RETURN_FAILED")
   check_routes()
   print("LIVE_TUN_HY2_RETURN=PASS_401",flush=True)
  except Exception as ex:
   print("LIVE_CANARY_FAILED_PHASE="+phase,flush=True)
   print("LIVE_CANARY_FAILED_CAUSE="+type(ex).__name__+":"+str(ex),flush=True)
   raise
  finally:
   print("LIVE_CANARY_RESTORE=STARTING",flush=True)
   rolled=proc(["/usr/bin/python3","-B","/run/awg-pbr/xray-live-canary-rollback.py",str(snap)],timeout=48)
   # Do not cancel watchdog until rollback is independently verified.
   if rolled.returncode!=0:
    print("LIVE_CANARY_RESTORE=INCOMPLETE_WATCHDOG_STILL_ARMED",flush=True)
    for line in rolled.stdout.splitlines():
     if line.startswith("LIVE_CANARY_"):
      print("ROLLBACK_LOG="+line[:110],flush=True)
   else:
    proof=restored_config_proof(snap/"config.previous",CONF,before_config_hash)
    require(proof in ("BYTE_IDENTICAL","YAML_EQUIVALENT"),
            "RESTORED_CONFIG_"+proof)
    verified_state=json.loads((snap/"state.json").read_text())
    require(verified_state.get("state")=="restored", "ROLLBACK_SNAPSHOT_NOT_RESTORED")
    print("LIVE_CANARY_CONFIG_RESTORED="+proof,flush=True)
    require(not SELECTED.exists(),"SELECTION_NOT_CLEANED")
    require(proc(["systemctl","is-active","--quiet",XUNIT]).returncode!=0,"XRAY_NOT_STOPPED")
    require(https("mihomo0"),"RESTORED_TUN_UNHEALTHY")
    require(status().get("now")==chosen,"OLD_NODE_NOT_RESTORED")
    require(mode_id()=="transit","OPERATING_MODE_CHANGED")
    require(policy==proc(["/usr/local/sbin/awg-mihomo-node-policy","auto-strategy","status"]).stdout,
            "POLICY_CHANGED")
    check_routes()
    proc(["systemctl","stop",timeout_unit+".timer"],timeout=8)
    print("LIVE_CANARY_RESTORED=PASS",flush=True)
    print("BACKUP_SNAPSHOT="+str(snap),flush=True)
  if rolled.returncode!=0:raise RuntimeError("ROLLBACK_INCOMPLETE")
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("LIVE_CANARY_ERROR="+type(e).__name__+":"+str(e),file=sys.stderr,flush=True)
  sys.exit(2)
