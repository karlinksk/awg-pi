#!/usr/bin/env python3
"""TEST PI ONLY: independent rescue for both completed Xray and FAIL-CLOSED.

--check: read-only preflight.
--arm: create a root-private snapshot and TWO independent systemd-run recovery
timers (180s, 330s) BEFORE an explicitly separate test fault is injected.
--recover SNAPSHOT: root-only recovery unit, idempotent and self-contained.

This is test infrastructure, NOT production auto-return or user node policy.
If original HY2 is still unavailable, retain Transit FAIL-CLOSED; do not claim
restoration. NEVER modify MikroTik, SSH, DNS, other mounts or production SD.
"""
import fcntl,hashlib,json,os,pathlib,re,shutil,socket,subprocess,sys,tempfile,time,urllib.request
import yaml

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=pathlib.Path(__file__).resolve()
BASE=pathlib.Path("/var/backups/awg-gateway")
MODE=pathlib.Path("/etc/awg-pbr/mode")
NODE_MODE=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
CHAIN=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
PROVIDER=pathlib.Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
HOME=pathlib.Path("/etc/awg-pbr/transports/mihomo")
FILES=("config.yaml","provider.env","node-name","endpoint-ip","expected-egress-ip")
CURRENT=HOME/"node-name"
SELECTED=pathlib.Path("/var/lib/awg-pbr/xray-vless/selected.json")
BRIDGE=pathlib.Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
RUNTIME_BRIDGE=pathlib.Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")
MONITOR_OVERRIDE=pathlib.Path("/run/systemd/system/awg-selection-monitor.service.d/90-awg-xray-fixed-failover-test.conf")
MONITOR_OWNED=b'[Service]\nEnvironment="MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1"\n'

MAINT=pathlib.Path("/run/awg-maintenance.lock")
GROUP="AWG-MIHOMO"
LOCAL="AWG-XRAY-VLESS-LOCAL"
TIMER_A=180
TIMER_B=330
SNAP_RX=re.compile(r"^xray-auto-rescue-[0-9]+-[0-9]+$")
OWNED_OVERRIDE=b'[Unit]\nRequires=awg-xray-vless.service\nAfter=awg-xray-vless.service\n[Service]\nEnvironment="MIHOMO_XRAY_VLESS_BRIDGE=1"\n'

def emit(k,v):print("XRAY_FIXED_RESCUE_"+k+"="+str(v),flush=True)
def require(p,why):
 if not p:raise RuntimeError(why)
def run(*args,timeout=15):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,timeout=timeout)
def ok(*args,timeout=15):
 r=run(*args,timeout=timeout)
 require(r.returncode==0,"PROCESS_FAILED_"+pathlib.Path(args[0]).name)
 return r.stdout.strip()
def active(s):return run("systemctl","is-active","--quiet",s,timeout=5).returncode==0
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe_name(s):return isinstance(s,str) and bool(s) and len(s)<200 and "\n" not in s
def atomic(path,data,mode=0o600):
 fd,name=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".test-")
 try:
  os.fchmod(fd,mode)
  with os.fdopen(fd,"wb") as f:
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
 finally:
  if os.path.lexists(name):os.unlink(name)
def jsonput(p,obj):atomic(p,(json.dumps(obj,sort_keys=True)+"\n").encode())
def baseline_root():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","TEST_PI_ROOT_REQUIRED")
 require(MODE.read_text().strip()=="transit" and NODE_MODE.read_text().strip()=="fixed",
         "TRANSIT_FIXED_REQUIRED")
 require(BASE.is_dir() and not BASE.is_symlink() and BASE.stat().st_uid==0,
         "BACKUP_BASE_UNSAFE")
 require(active("ssh.service") and active("dnsmasq.service"),"MANAGEMENT_NOT_READY")
def routes():
 result=[]
 for table in ("100","101"):
  r=ok("ip","-4","route","show","table",table,timeout=6)
  require(not r or all(re.fullmatch(r"default\s+dev\s+mihomo0(?:\s+.*)?",x)
     for x in r.splitlines()),"FOREIGN_ROUTE_"+table)
  result.append(r)
 return tuple(result)
def openai():
 r=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
       "--connect-timeout","5","--max-time","16","-sS","-o","/dev/null",
       "-w","%{http_code}","https://api.openai.com/v1/models",timeout=21)
 return r.returncode==0 and r.stdout=="401"
def guard():return ok("/usr/local/sbin/awg-transit-routing","status",timeout=12).splitlines()
def healthy_guard():
 s=guard()
 return all(x in s for x in ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY"))
def qualified_current():
 chain=[n.strip() for n in CHAIN.read_text().splitlines() if n.strip()]
 require(len(chain)>=2 and len(chain)==len(set(chain)),"FIXED_CHAIN_INVALID")
 old=CURRENT.read_text().strip()
 require(safe_name(old) and old in chain[:-1],"ORIGINAL_NODE_NOT_ALLOWED")
 result=ok("/usr/local/sbin/awg-mihomo-unified-nodes","resolve",chain[-1],timeout=12)
 fields=dict(x.split("=",1) for x in result.splitlines() if "=" in x)
 require(fields.get("NODE_ENGINE")=="XRAY","NO_XRAY_LAST_FALLBACK")
 return old,chain[-1]
def preflight():
 baseline_root()
 require(active("awg-mihomo.service") and active("awg-selection-monitor.service") and
         not active("awg-xray-vless.service"),"NOT_HEALTHY_OR_XRAY_ACTIVE")
 require(not SELECTED.exists() and not BRIDGE.exists() and not RUNTIME_BRIDGE.exists(),
         "BRIDGE_ALREADY_STAGED")
 require(healthy_guard(),"TRANSIT_NOT_HEALTHY")
 require(all("default dev mihomo0" in x for x in routes()),"ROUTES_NOT_READY")
 require(openai(),"ORIGINAL_TUN_NOT_401")
 for file in FILES:
  p=HOME/file
  if file!="expected-egress-ip":require(p.is_file() and not p.is_symlink(),"MISSING_BACKUP_MEMBER")
 require(PROVIDER.is_file() and not PROVIDER.is_symlink(),"PROVIDER_MISSING")
 old,backup=qualified_current()
 timers=ok("systemctl","list-timers","--all","--no-pager")
 require(not any(s in timers for s in ("awg-xray-rescue-","awg-xray-failover-",
                                      "awg-xray-auto-rescue-","awg-xray-live-rollback-")),
         "EXISTING_RESCUE_OR_WATCHDOG")
 return old,backup
def snapshot_id():
 return "xray-auto-rescue-"+str(int(time.time()))+"-"+str(os.getpid())
def check_snapshot(snap):
 baseline_root()
 require(snap.parent==BASE and SNAP_RX.fullmatch(snap.name) and
         snap.is_dir() and not snap.is_symlink() and
         snap.stat().st_uid==0 and snap.stat().st_mode & 0o077==0,
         "UNTRUSTED_SNAPSHOT")
 manifest=json.loads((snap/"manifest.json").read_text())
 require(manifest.get("purpose")=="Xray FIXED test-Pi independent restoration" and
         safe_name(manifest.get("old")) and safe_name(manifest.get("xray")) and
         manifest.get("old")!=manifest.get("xray"),"INVALID_RESCUE_MANIFEST")
 require(manifest.get("saved",{}).keys()<=set(FILES) and
         "node-name" in manifest["saved"] and
         "config.yaml" in manifest["saved"] and "provider.env" in manifest["saved"],
         "BACKUP_MEMBERS_MISSING")
 for name,expected in manifest["saved"].items():
  copy=snap/(name+".previous")
  require(copy.is_file() and not copy.is_symlink() and sha(copy)==expected,
          "BACKUP_CHECKSUM_FAILED")
 return manifest
def arm():
 old,xray=preflight()
 snap=BASE/snapshot_id()
 snap.mkdir(mode=0o700)
 saved={}
 for name in FILES:
  orig=HOME/name
  if not orig.exists():continue
  require(orig.is_file() and not orig.is_symlink(),"UNSAFE_ORIGINAL_MEMBER")
  copy=snap/(name+".previous")
  atomic(copy,orig.read_bytes())
  saved[name]=sha(copy)
 script=snap/"rescue.py"
 atomic(script,SOURCE.read_bytes(),0o700)
 require(sha(script)==sha(SOURCE),"INDEPENDENT_CODE_COPY_FAILED")
 manifest={"purpose":"Xray FIXED test-Pi independent restoration",
           "old":old,"xray":xray,"provider_sha256":sha(PROVIDER),
           "chain_sha256":sha(CHAIN),"saved":saved}
 jsonput(snap/"manifest.json",manifest)
 jsonput(snap/"state.json",{"status":"preparing","result":None})
 check_snapshot(snap)
 units=["awg-xray-auto-rescue-a-"+str(os.getpid()),
        "awg-xray-auto-rescue-b-"+str(os.getpid())]
 armed=[]
 try:
  for unit,delay in zip(units,(TIMER_A,TIMER_B)):
   r=run("systemd-run","--unit="+unit,"--on-active="+str(delay)+"s",
         "/usr/bin/python3","-B",str(script),"--recover",str(snap),timeout=16)
   require(r.returncode==0 and active(unit+".timer"),"RESCUE_TIMER_ARM_FAILED")
   armed.append(unit)
  jsonput(snap/"state.json",{"status":"armed","result":None,"rescue_units":units})
  emit("ARMED_TIMERS","180S_330S")
  emit("SNAPSHOT",str(snap))
  emit("PRODUCTION_CHANGED","NO")
  return snap
 except Exception:
  # No injected failure has occurred. Prevent partial timer from touching live.
  jsonput(snap/"state.json",{"status":"cancelled","result":None})
  for unit in armed:run("systemctl","stop",unit+".timer",timeout=10)
  raise
def controller_now():
 try:
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  with op.open("http://127.0.0.1:9090/proxies/"+GROUP,timeout=4) as r:
   return json.load(r).get("now")
 except Exception:return None
def controller_select(n):
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 req=urllib.request.Request("http://127.0.0.1:9090/proxies/"+GROUP,
  method="PUT",data=json.dumps({"name":n}).encode(),
  headers={"Content-Type":"application/json"})
 with op.open(req,timeout=5) as r:require(r.status in (200,204),"CONTROLLER_REJECTED")
def failclosed():
 ok("/usr/local/sbin/awg-transit-routing","disable",timeout=16)
 require("Transit policy rule: INACTIVE" in guard(),"FAIL_CLOSED_NOT_CONFIRMED")
def reinstate_routes():
 for _ in range(40):
  if run("ip","link","show","dev","mihomo0",timeout=5).returncode==0:break
  time.sleep(.5)
 else:raise RuntimeError("ORIGINAL_TUN_NOT_CREATED")
 for table in ("100","101"):
  r=ok("ip","-4","route","show","table",table)
  require(not r or re.fullmatch(r"default\s+dev\s+mihomo0(?:\s+.*)?",r),
          "FOREIGN_ROUTE_DURING_RECOVERY")
  if not r:ok("ip","route","replace","table",table,"default","dev","mihomo0")
def clean_monitor_optin():
 if MONITOR_OVERRIDE.exists():
  require(MONITOR_OVERRIDE.is_file() and not MONITOR_OVERRIDE.is_symlink() and
          MONITOR_OVERRIDE.read_bytes()==MONITOR_OWNED,
          "FOREIGN_SELECTION_MONITOR_OVERRIDE")
  MONITOR_OVERRIDE.unlink()
  if MONITOR_OVERRIDE.parent.is_dir() and not list(MONITOR_OVERRIDE.parent.iterdir()):
   MONITOR_OVERRIDE.parent.rmdir()
  ok("systemctl","daemon-reload",timeout=15)
  ok("systemctl","restart","awg-selection-monitor.service",timeout=20)
 require(active("awg-selection-monitor.service"),"SELECTION_MONITOR_NOT_RESTORED")

def clear_test_fault(snap):
 # Remove temporary fault before checking selected-node drift, so an
 # unrelated safe manual node change cannot strand the test-side blocker.
 # Remove ONLY a test-owned block, if a future fault injector records it;
 # reject arbitrary nft modifications rather than erasing unrelated rules.
 test_fault=snap/"fault.json"
 if test_fault.is_file():
  f=json.loads(test_fault.read_text())
  require(f=={"kind":"nft_endpoint_blackhole","table":"awg_xray_fixed_test"},
          "UNKNOWN_FAULT_INJECTION")
  rules=run("nft","list","table","inet","awg_xray_fixed_test",timeout=7)
  if rules.returncode==0:
   require("chain block_output" in rules.stdout and
           "AWG-XRAY-FIXED-TEST" in rules.stdout,
           "FAULT_TABLE_OWNERSHIP_UNVERIFIED")
   ok("nft","delete","table","inet","awg_xray_fixed_test")
  else:
   listed=run("nft","list","tables",timeout=8)
   require(listed.returncode==0 and
           "table inet awg_xray_fixed_test" not in listed.stdout,
           "FAULT_TABLE_COULD_NOT_BE_INSPECTED")

def verified_awg_backup_safe():
 """Preserve a healthy AWG transport; never force its tables onto mihomo0."""
 if not active("awg-quick@awg0.service") or not active("ssh.service") or \
    not active("dnsmasq.service"):
  return False
 try:
  if ok("/usr/local/sbin/awg-transport","get",timeout=10)!="awg" or not healthy_guard():
   return False
  for table in ("100","101"):
   lines=ok("ip","-4","route","show","table",table,timeout=7).splitlines()
   if len(lines)!=1 or not re.fullmatch(
       r"default\s+dev\s+awg0(?:\s+.*)?",lines[0].strip()):
    return False
  return True
 except (OSError,RuntimeError,subprocess.TimeoutExpired):
  return False

def restore(snap):
 manifest=check_snapshot(snap)
 with (snap/"rescue.lock").open("a") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=json.loads((snap/"state.json").read_text())
  if state.get("status")=="cancelled":return
  if state.get("result")=="PASS":return
  require(state.get("status")=="armed","RESCUE_NOT_ARMED")
  with MAINT.open("a") as maintenance:
   fcntl.flock(maintenance,fcntl.LOCK_EX)
   clear_test_fault(snap)
   clean_monitor_optin()
   # A configured AWG may legitimately win the transport fallback race.
   # Stop here: preserving an independently SAFE/ACTIVE/READY backup is safer
   # than forcibly replacing its routes with a test snapshot of mihomo0.
   if verified_awg_backup_safe():
    clean=(not active("awg-xray-vless.service") and
           not BRIDGE.exists() and not RUNTIME_BRIDGE.exists() and
           not SELECTED.exists())
    if clean:
     jsonput(snap/"state.json",dict(state,result="PASS",status="preserved_awg"))
     emit("RESULT","PASS_AWG_BACKUP_PRESERVED_NOT_HY2")
    else:
     # Keep the confirmed AWG live; report leftover Xray artifacts explicitly.
     # They must be reviewed independently, never cleaned by rerouting AWG.
     emit("RESULT","AWG_SAFE_XRAY_ARTIFACTS_REQUIRE_REVIEW")
    return
   # If no fault was injected, do not disrupt a still-healthy original.
   if (CURRENT.read_text().strip()==manifest["old"] and active("awg-mihomo.service")
       and not active("awg-xray-vless.service") and not SELECTED.exists()
       and not BRIDGE.exists() and healthy_guard() and openai()):
    jsonput(snap/"state.json",dict(state,result="PASS",status="unchanged"))
    emit("RESULT","PASS_ORIGINAL_UNCHANGED")
    return
   require(CURRENT.read_text().strip() in (manifest["old"],manifest["xray"]),
           "FOREIGN_SELECTED_NODE")
   # The local endpoint block is removed before provider drift is checked;
   # never leave a test-only outage behind after a subscription rotation.
   if sha(PROVIDER)!=manifest["provider_sha256"] or sha(CHAIN)!=manifest["chain_sha256"]:
    failclosed()
    raise RuntimeError("PROVIDER_OR_FIXED_CHANGED_KEEP_FAIL_CLOSED")
   # ALWAYS close Transit before tearing down Xray; independent SSH stays eth0.
   failclosed()
   ok("systemctl","stop","awg-mihomo.service",timeout=25)
   ok("systemctl","stop","awg-xray-vless.service",timeout=20)
   for b in (BRIDGE,RUNTIME_BRIDGE):
    if b.exists():
     require(b.is_file() and not b.is_symlink() and b.read_bytes()==OWNED_OVERRIDE,
             "FOREIGN_BRIDGE_OVERRIDE")
     b.unlink()
   SELECTED.unlink(missing_ok=True)
   ok("systemctl","disable","awg-xray-vless.service",timeout=12)
   for name in FILES:
    previous=snap/(name+".previous")
    destination=HOME/name
    if name in manifest["saved"]:atomic(destination,previous.read_bytes())
    else:destination.unlink(missing_ok=True)
   ok("systemctl","daemon-reload",timeout=15)
   ok("systemctl","start","awg-mihomo.service",timeout=40)
   reinstate_routes()
   if controller_now()!=manifest["old"]:controller_select(manifest["old"])
   # Do NOT reopen LAN Transit or announce PASS until real original TUN works.
   for _ in range(3):
    if openai():break
    time.sleep(3)
   else:raise RuntimeError("ORIGINAL_TUN_HTTPS_NOT_READY")
   proof=yaml.safe_load((snap/"config.yaml.previous").read_bytes())
   live=yaml.safe_load((HOME/"config.yaml").read_bytes())
   require(isinstance(proof,dict) and proof==live,"ORIGINAL_YAML_CHANGED")
   require(CURRENT.read_text().strip()==manifest["old"],"ORIGINAL_NODE_NOT_RESTORED")
   require(not active("awg-xray-vless.service") and not BRIDGE.exists() and
           not SELECTED.exists(),"XRAY_STILL_CONFIGURED")
   ok("/usr/local/sbin/awg-transit-routing","apply",timeout=16)
   require(healthy_guard() and openai(),"RESTORED_TRANSIT_NOT_VERIFIED")
   jsonput(snap/"state.json",dict(state,result="PASS",status="restored"))
   emit("RESULT","PASS_RESTORED_HY2")
def main():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","TEST_PI_ONLY")
 if sys.argv[1:]==["--check"]:
  old,xray=preflight()
  emit("PREFLIGHT","PASS")
  emit("RESCUE_ARMED","NO")
 elif sys.argv[1:]==["--arm"]:
  arm()
 elif len(sys.argv)==3 and sys.argv[1]=="--recover":
  try:restore(pathlib.Path(sys.argv[2]))
  except Exception:
   # An active AWG may have taken over after this rescue started. Never
   # disable its healthy Transit policy as an error-handler side effect.
   try:
    if not verified_awg_backup_safe() and \
       ok("/usr/local/sbin/awg-transport","get",timeout=9)=="mihomo":
     failclosed()
   except Exception:pass
   raise
 else:raise RuntimeError("USAGE")

if __name__=="__main__":
 try:main()
 except Exception as exc:
  emit("RESULT","FAIL_REVIEW_REQUIRED")
  emit("ERROR",str(exc) if isinstance(exc,RuntimeError) else "CHECK_FAILED")
  sys.exit(1)
