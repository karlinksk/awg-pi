#!/usr/bin/env python3
"""Guarded real ARMING-state watchdog test with independent timed recovery.

TEST PI ONLY. The test starts a 5-second real systemd watchdog (armed snapshot),
which puts MikroTik Transit into fail-closed. TWO independently scheduled
systemd-run rescue jobs, installed BEFORE the watchdog, restore the pre-existing
healthy Mihomo. SSH remains DIRECT on eth0; no MikroTik/production changes.

DO NOT enable in installer or use as automatic node failover.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

BASE=Path("/var/backups/awg-gateway")
SOURCE=Path(__file__).resolve()
INSTALLED=Path("/usr/local/sbin/awg-xray-live-backend")
BACKEND=Path("/tmp/awg-unified-tun-release-20261019/src/awg-xray-live-backend.py")
NODE=Path("/etc/awg-pbr/transports/mihomo/node-name")
FIXED=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
MODE=Path("/etc/awg-pbr/mode")
MAINTENANCE_LOCK=Path("/run/awg-maintenance.lock")
GUARD="/usr/local/sbin/awg-transit-routing"
NAME=re.compile(r"^xray-failover-[0-9]+-[0-9]+$")
TRANSIT_LINES=("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")
RESCUE_A=60
RESCUE_B=135

def out(k,v):print("XRAY_ARMED_TEST_"+k+"="+str(v),flush=True)
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def run(*args,secs=20):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,timeout=secs)
def success(*args,secs=20):
 result=run(*args,secs=secs)
 require(result.returncode==0,"COMMAND_FAILED_"+Path(args[0]).name)
 return result.stdout
def active(service):
 return run("systemctl","is-active","--quiet",service,secs=6).returncode==0
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic(path,obj):
 tmp=path.parent/("."+path.name+".tmp-"+str(os.getpid()))
 try:
  with tmp.open("x") as f:
   os.chmod(tmp,0o600)
   json.dump(obj,f);f.write("\n");f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:tmp.unlink(missing_ok=True)
def read_state(snapshot):return json.loads((snapshot/"state.json").read_text())
def status():return success(GUARD,"status",secs=15).splitlines()
def default(table):
 return success("ip","-4","route","show","table",str(table),secs=8).strip()
def ready_route(route):
 return re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",route) is not None
def openai():
 code=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
   "--connect-timeout","7","--max-time","20","-sS","-o","/dev/null",
   "-w","%{http_code}","https://api.openai.com/v1/models",secs=27)
 return code.returncode==0 and code.stdout=="401"
def root_pi():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade",
         "ROOT_TEST_PI_ONLY")
 require(MODE.read_text().strip()=="transit","TRANSIT_ONLY")
 require(BASE.is_dir() and BASE.stat().st_uid==0 and not BASE.is_symlink(),
         "BACKUP_BASE_UNTRUSTED")
def baseline():
 root_pi()
 require(INSTALLED.is_file() and BACKEND.is_file() and
         sha(INSTALLED)==sha(BACKEND),"EXECUTOR_SHA_MISMATCH")
 require(active("ssh.service") and active("dnsmasq.service") and
         active("awg-selection-monitor.service") and active("awg-mihomo.service"),
         "CORE_OR_SSH_NOT_ACTIVE")
 require(not active("awg-xray-vless.service"),"XRAY_ACTIVE")
 require(ready_route(default(100)) and ready_route(default(101)),
         "POLICY_ROUTE_UNSAFE")
 require(all(k in status() for k in TRANSIT_LINES),"TRANSIT_UNSAFE")
 require(openai(),"OPENAI_TUN_NOT_401")
 require(NODE.is_file() and FIXED.is_file(),"NODE_POLICY_MISSING")
 for name in ("awg-xray-vless.service","awg-mihomo.service"):
  require(run("systemctl","is-enabled",name).stdout.strip() in
          (("disabled","static") if "xray" in name else ("enabled",)),
          "AUTOSTART_UNEXPECTED")
 for candidate in ("/var/lib/awg-pbr/xray-vless/selected.json",
        "/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf",
        "/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"):
  require(not Path(candidate).exists(),"XRAY_STAGED")
 timers=success("systemctl","list-timers","--all","--no-pager")
 require(not any("awg-xray-failover-" in x or "awg-xray-live-rollback-" in x
                or "awg-xray-rescue-" in x for x in timers.splitlines()),
         "WATCHDOG_OR_RESCUE_ALREADY_PENDING")
 return {"node":sha(NODE),"fixed":sha(FIXED),
         "config_sha":sha(Path("/etc/awg-pbr/transports/mihomo/config.yaml"))}

def trusted_snapshot(snapshot):
 root_pi()
 require(snapshot.parent==BASE and bool(NAME.fullmatch(snapshot.name)) and
         snapshot.is_dir() and not snapshot.is_symlink() and
         snapshot.stat().st_uid==0 and snapshot.stat().st_mode & 0o077==0,
         "UNTRUSTED_SNAPSHOT")
 manifest=json.loads((snapshot/"preflight.json").read_text())
 require(manifest.get("purpose")=="AWG_XRAY_ARMED_WATCHDOG_RECOVERY" and
         isinstance(manifest.get("node"),str) and
         isinstance(manifest.get("fixed"),str) and
         isinstance(manifest.get("config_sha"),str),"INVALID_MANIFEST")
 require((snapshot/"state.json").is_file(),"MISSING_WATCHDOG_STATE")
 return manifest

def ensure_routes():
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  if run("ip","link","show","dev","mihomo0",secs=5).returncode==0:break
  time.sleep(.6)
 else:raise RuntimeError("MIHOMO_TUN_NOT_RECREATED")
 for table in (100,101):
  route=default(table)
  require(not route or ready_route(route),"FOREIGN_ROUTE_IN_"+str(table))
  if not ready_route(route):
   success("ip","-4","route","replace","table",str(table),
           "default","dev","mihomo0",secs=8)
 require(ready_route(default(100)) and ready_route(default(101)),
         "ROUTES_NOT_RESTORED")

def recover(snapshot):
 manifest=trusted_snapshot(snapshot)
 with (snapshot/"rescue.lock").open("a") as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  history=snapshot/"recovery.json"
  if history.is_file() and json.loads(history.read_text()).get("result")=="PASS":
   return
  state=read_state(snapshot).get("state")
  require(state in ("armed","quiesced","committed"),"NO_ARMED_WATCHDOG")
  guard=status()
  observed=("Transit policy rule: INACTIVE" in guard and
            any(x in guard for x in ("Transit guard: SAFE","Transit guard: LOCKDOWN")) and
            not active("awg-mihomo.service"))
  atomic(history,{"result":"IN_PROGRESS","watchdog_state":state,
                  "fail_closed_observed":observed})
  try:
   require(sha(NODE)==manifest["node"] and sha(FIXED)==manifest["fixed"],
           "NODE_POLICY_CHANGED_DURING_TEST")
   require(active("ssh.service") and active("dnsmasq.service"),
           "MANAGEMENT_OR_DNS_DOWN")
   require(not active("awg-xray-vless.service"),"UNEXPECTED_XRAY_ACTIVE")
   success("systemctl","start","awg-mihomo.service",secs=45)
   ensure_routes()
   if "Transit policy rule: ACTIVE" not in status():
    success(GUARD,"apply",secs=20)
   require(all(x in status() for x in TRANSIT_LINES),
           "TRANSIT_NOT_RECOVERED")
   # Give freshly started TUN a bounded warm-up.
   verified=False
   for attempt in range(3):
    if openai():verified=True;break
    time.sleep(3)
   require(verified,"OPENAI_TUN_NOT_RECOVERED")
   require(sha(NODE)==manifest["node"] and sha(FIXED)==manifest["fixed"],
           "POLICY_CHANGED_AFTER_RECOVERY")
   atomic(history,{"result":"PASS","watchdog_state":state,
                   "fail_closed_observed":observed,
                   "tun_openai":401,"ssh_preserved":True})
  except Exception:
   atomic(history,{"result":"RETRY_REQUIRED","watchdog_state":state,
                   "fail_closed_observed":observed})
   raise

def arm_timer(unit,delay,snapshot):
 result=run("systemd-run","--unit="+unit,"--on-active="+str(delay)+"s",
            "/usr/bin/python3","-B",str(snapshot/"rescue.py"),"--recover",
            str(snapshot),secs=15)
 require(result.returncode==0,"RESCUE_TIMER_ARM_FAILED")
 require(active(unit+".timer"),"RESCUE_TIMER_NOT_ACTIVE")
def begin():
 before=baseline()
 out("PREFLIGHT","PASS")
 if sys.argv[1]=="--check":return
 require(sys.argv[1]=="--run","USAGE")
 stamp=str(int(time.time()))+"-"+str(os.getpid())
 snap=BASE/("xray-failover-"+stamp)
 snap.mkdir(mode=0o700)
 atomic(snap/"preflight.json",dict(before,purpose="AWG_XRAY_ARMED_WATCHDOG_RECOVERY"))
 for original,dest in ((NODE,"node.before"),(FIXED,"fixed.before")):
  copy=snap/dest
  copy.write_bytes(original.read_bytes());copy.chmod(0o600)
  require(sha(copy)==sha(original),"BACKUP_HASH_INVALID")
 # Independent rescue worker is snapshotted and will survive caller exit.
 rescued=snap/"rescue.py"
 rescued.write_bytes(SOURCE.read_bytes());rescued.chmod(0o700)
 require(sha(rescued)==sha(SOURCE),"RESCUE_CODE_COPY_INVALID")
 atomic(snap/"state.json",{"state":"armed","test_only":True})
 units=["awg-xray-rescue-a-"+str(os.getpid()),
        "awg-xray-rescue-b-"+str(os.getpid())]
 armed=[]
 try:
  arm_timer(units[0],RESCUE_A,snap);armed.append(units[0])
  arm_timer(units[1],RESCUE_B,snap);armed.append(units[1])
  # No disruptive timer is allowed to exist without BOTH independent rescue jobs.
  out("RESCUE_TIMERS","ARMED_60S_135S")
  job="awg-xray-armed-test-"+str(os.getpid())
  result=run("systemd-run","--unit="+job,"--on-active=5s",
             str(INSTALLED),"watchdog",str(snap),secs=15)
  require(result.returncode==0 and active(job+".timer"),"WATCHDOG_NOT_ARMED")
  out("WATCHDOG","ARMED_5S")
  out("BACKUP_SNAPSHOT",str(snap))
  deadline=time.monotonic()+45
  quiesced=False
  while time.monotonic()<deadline:
   state=read_state(snap).get("state")
   if state=="quiesced":quiesced=True;break
   require(state=="armed","UNEXPECTED_WATCHDOG_STATE")
   time.sleep(.5)
  if quiesced:
   guard=status()
   policy_ok=("Transit policy rule: INACTIVE" in guard)
   safe=any(x in guard for x in
       ("Transit guard: SAFE","Transit guard: LOCKDOWN"))
   stopped=not active("awg-mihomo.service")
   out("FAIL_CLOSED_OBSERVED","PASS" if all((policy_ok,safe,stopped)) else "NOT_VERIFIED")
  else:out("FAIL_CLOSED_OBSERVED","NOT_VERIFIED")
  # Recovery runs from its own systemd unit even if this session drops.
  deadline=time.monotonic()+155
  while time.monotonic()<deadline:
   artifact=snap/"recovery.json"
   if artifact.is_file():
    evidence=json.loads(artifact.read_text())
    if evidence.get("result")=="PASS":
     require(all(x in status() for x in TRANSIT_LINES),"FINAL_TRANSIT_NOT_SAFE")
     require(active("awg-mihomo.service") and openai(),"FINAL_TUN_NOT_GOOD")
     require(sha(NODE)==before["node"] and sha(FIXED)==before["fixed"],
             "FINAL_NODE_POLICY_CHANGED")
     out("RECOVERY","PASS_INDEPENDENT_TIMER")
     out("FAIL_CLOSED_AT_RESCUE","PASS" if evidence.get("fail_closed_observed") else "NOT_OBSERVED")
     out("NODE_POLICY_CHANGED","NO")
     out("OPENAI_TUN","401")
     out("RESULT","PASS" if quiesced and evidence.get("fail_closed_observed") else "INCOMPLETE")
     return
   time.sleep(1)
  raise RuntimeError("RESTORE_TIMERS_NEED_MANUAL_REVIEW")
 finally:
  # Do not disarm unneeded rescue jobs if recovery was not verified.
  recovered=(snap/"recovery.json").is_file() and json.loads(
      (snap/"recovery.json").read_text()).get("result")=="PASS"
  if recovered:
   for unit in units:
    run("systemctl","stop",unit+".timer",secs=8)

if __name__=="__main__":
 try:
  require(len(sys.argv) in (2,3),"USAGE")
  if len(sys.argv)==3 and sys.argv[1]=="--recover":
   recover(Path(sys.argv[2]))
  elif len(sys.argv)==2:
   with MAINTENANCE_LOCK.open("a") as maintenance:
    fcntl.flock(maintenance,fcntl.LOCK_EX|fcntl.LOCK_NB)
    begin()
  else:raise RuntimeError("USAGE")
 except Exception as exc:
  out("ERROR",str(exc) if isinstance(exc,RuntimeError) else "CHECK_FAILED")
  sys.exit(1)
