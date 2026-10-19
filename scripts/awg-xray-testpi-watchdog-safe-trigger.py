#!/usr/bin/env python3
"""Root-only test-Pi watchdog timer test: actual systemd trigger, no network mutation.

Uses the pending state (timer should mark expired_before_mutation without
stopping Mihomo); NOT a forced FAIL-CLOSED or automatic failover PASS.
"""
import fcntl,hashlib,json,os,pathlib,re,socket,subprocess,sys,tempfile,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
SRC=ROOT/"src/awg-xray-live-backend.py"
EXEC=pathlib.Path("/usr/local/sbin/awg-xray-live-backend")
BASE=pathlib.Path("/var/backups/awg-gateway")
LOCK=pathlib.Path("/run/awg-maintenance.lock")
SELECTED=pathlib.Path("/var/lib/awg-pbr/xray-vless/selected.json")
BRIDGES=[
 pathlib.Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
 pathlib.Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf")]
NODE=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-name")
FIXED=pathlib.Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
def show(k,v):print("XRAY_WATCHDOG_TEST_"+k+"="+str(v),flush=True)
def require(check,err):
 if not check:raise RuntimeError(err)
def run(*args,t=12):
 return subprocess.run(args,stdin=subprocess.DEVNULL,
   stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=t)
def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def active(unit):return run("systemctl","is-active","--quiet",unit,t=5).returncode==0
def baseline():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","TEST_PI_ROOT_REQUIRED")
 require(pathlib.Path("/etc/awg-pbr/mode").read_text().strip()=="transit","TRANSIT_REQUIRED")
 require(EXEC.is_file() and not EXEC.is_symlink() and sha(EXEC)==sha(SRC),"EXECUTOR_UPDATE_REQUIRED")
 require(active("awg-mihomo.service") and active("dnsmasq.service") and
   active("awg-selection-monitor.service"),"CORE_NOT_ACTIVE")
 require(not active("awg-xray-vless.service"),"XRAY_ALREADY_ACTIVE")
 require(not SELECTED.exists() and not any(p.exists() for p in BRIDGES),"XRAY_STAGED")
 timers=run("systemctl","list-timers","--all","--no-pager")
 require(timers.returncode==0 and not any("awg-xray-failover-" in l
   or "awg-xray-live-rollback-" in l for l in timers.stdout.splitlines()),
   "OLD_WATCHDOG_TIMER")
 guard=run("/usr/local/sbin/awg-transit-routing","status")
 require(guard.returncode==0 and all(s in guard.stdout.splitlines()
   for s in ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
   "TRANSIT_GUARD_UNSAFE")
 routes=[]
 for table in ("100","101"):
  r=run("ip","route","show","table",table,t=6)
  require(r.returncode==0 and re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",r.stdout),
    "BAD_POLICY_ROUTE")
  routes.append(r.stdout)
 code=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
   "--connect-timeout","6","--max-time","17","-sS","-o","/dev/null","-w","%{http_code}",
   "https://api.openai.com/v1/models",t=23)
 require(code.returncode==0 and code.stdout=="401","MIHOMO_TUN_NOT_401")
 return (tuple(routes),sha(NODE),sha(FIXED))
def main():
 require(sys.argv[1:] in (["--check"],["--trigger-safe"]),"USAGE")
 with LOCK.open("a") as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  before=baseline()
  show("PREFLIGHT","PASS")
  if sys.argv[1]=="--check":
   show("TRIGGER","NOT_STARTED");return
  require(BASE.is_dir() and BASE.stat().st_uid==0,"BACKUP_DIRECTORY_UNSAFE")
  folder=pathlib.Path(tempfile.mkdtemp(prefix="xray-failover-",dir=BASE))
  folder.chmod(0o700)
  state=folder/"state.json"
  state.write_text(json.dumps({"state":"pending","test_only":True}))
  state.chmod(0o600)
  unit="awg-xray-safe-watchdog-"+str(os.getpid())
  try:
   result=run("systemd-run","--unit="+unit,"--on-active=5s",
       str(EXEC),"watchdog",str(folder),t=14)
   require(result.returncode==0,"TIMER_SCHEDULING_FAILED")
   end=time.monotonic()+35
   while time.monotonic()<end:
    current=json.loads(state.read_text()).get("state")
    if current=="expired_before_mutation":break
    require(current=="pending","UNEXPECTED_WATCHDOG_STATE")
    time.sleep(.5)
   require(json.loads(state.read_text()).get("state")=="expired_before_mutation",
       "TIMER_NOT_TRIGGERED")
   require(baseline()==before,"NETWORK_OR_NODE_CHANGED")
   show("TRIGGER","FIRED_IN_SYSTEMD")
   show("STATE","EXPIRED_BEFORE_MUTATION")
   show("LIVE_NETWORK_CHANGED","NO")
   show("FAIL_CLOSED_PATH","NOT_TESTED")
   show("RESULT","PASS_SAFE_TRIGGER")
  finally:
   # In case a timer never fired, prevent any later executable action.
   with (folder/"watchdog-state.lock").open("a") as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    payload=json.loads(state.read_text())
    if payload.get("state")=="pending":
     payload["state"]="cancelled"
     state.write_text(json.dumps(payload))
   run("systemctl","stop",unit+".timer",t=10)
if __name__=="__main__":
 try:main()
 except Exception:
  show("RESULT","FAIL_REVIEW_REQUIRED")
  sys.exit(1)
