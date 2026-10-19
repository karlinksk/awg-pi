#!/usr/bin/env python3
"""Test Pi only: passive atomic upgrade for guarded degraded FIXED→Xray.

No live service, route, selected node, FIXED chain, ssh, DNS or router changes.
Both helpers are sha-pinned against the currently installed versions.
Experimental FIXED cross-core failover remains DISABLED by default.
"""
import hashlib,os
from pathlib import Path
import re,socket,subprocess,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
FILES=(
 (ROOT/"src/awg-mihomo-node-policy",
  Path("/usr/local/sbin/awg-mihomo-node-policy"),
  "cf7badfff4c0c04c5f9d1db4115f6dc466d0294b3f277af90051f9c18392dc79"),
 (ROOT/"src/awg-xray-live-backend.py",
  Path("/usr/local/sbin/awg-xray-live-backend"),
  "30e404a57288ebde5bde38353f4c9fd5e421af3ad66998dd752b5ae2a6de1628"),
)
MODE=Path("/etc/awg-pbr/mode")
FIXED_MODE=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
FIXED_CHAIN=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
BACKUPS=Path("/var/backups/awg-gateway")

def emit(name,value):print("XRAY_DEGRADED_FIXED_STAGE_"+name+"="+str(value),flush=True)
def require(cond,tag):
 if not cond:raise RuntimeError(tag)
def digest(data):return hashlib.sha256(data).hexdigest()
def run(*args,timeout=12):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,timeout=timeout)
def active(unit):return run("systemctl","is-active","--quiet",unit,timeout=6).returncode==0

def baseline():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","TEST_PI_ROOT_REQUIRED")
 require(MODE.read_text().strip()=="transit" and
         FIXED_MODE.read_text().strip()=="fixed","TRANSIT_FIXED_REQUIRED")
 for service in ("awg-mihomo.service","dnsmasq.service",
                 "awg-selection-monitor.service","ssh.service"):
  require(active(service),"CORE_SERVICE_NOT_ACTIVE")
 require(not active("awg-xray-vless.service"),"XRAY_ALREADY_RUNNING")
 require(not Path("/var/lib/awg-pbr/xray-vless/selected.json").exists(),
         "XRAY_SELECTED")
 for overlay in (
  "/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf",
  "/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf",
  "/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf"):
  require(not Path(overlay).exists(),"XRAY_BRIDGE_PRESENT")
 status=run("/usr/local/sbin/awg-transit-routing","status")
 require(status.returncode==0 and all(x in status.stdout.splitlines() for x in
         ("Transit guard: SAFE","Transit policy rule: ACTIVE",
          "Transit VPN table: READY")),"TRANSIT_NOT_SAFE")
 routes=[]
 for table in ("100","101"):
  r=run("ip","-4","route","show","table",table)
  require(r.returncode==0 and re.search(
      r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",r.stdout),
      "POLICY_ROUTE_INVALID")
  routes.append(r.stdout)
 t=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
     "--connect-timeout","6","--max-time","18","-sS","-o","/dev/null",
     "-w","%{http_code}","https://api.openai.com/v1/models",timeout=24)
 require(t.returncode==0 and t.stdout=="401","ORIGINAL_TUN_NOT_HEALTHY")
 env=run("systemctl","show","--property=Environment","awg-selection-monitor.service")
 require(env.returncode==0 and
         "MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1" not in env.stdout,
         "LIVE_AUTO_XRAY_ALREADY_ENABLED")
 timers=run("systemctl","list-timers","--all","--no-pager")
 require(timers.returncode==0 and not any(
     x in timers.stdout for x in ("awg-xray-failover-",
                                 "awg-xray-rescue-","awg-xray-live-rollback-")),
         "PENDING_XRAY_TIMER")
 return (tuple(routes),digest(CURRENT.read_bytes()),
         digest(FIXED_CHAIN.read_bytes()),digest(FIXED_MODE.read_bytes()))

def atomic(path,data):
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".testpi-")
 try:
  os.fchmod(fd,0o755);os.fchown(fd,0,0)
  with os.fdopen(fd,"wb") as out:
   out.write(data);out.flush();os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.lexists(tmp):os.unlink(tmp)

def preflight():
 prior=[]
 for src,dest,expected in FILES:
  require(src.is_file() and dest.is_file() and
          not src.is_symlink() and not dest.is_symlink(),"HELPER_MISSING_OR_SYMLINK")
  old=dest.read_bytes()
  require(digest(old)==expected,"UNREVIEWED_INSTALLED_HELPER")
  new=src.read_bytes()
  if src.suffix==".py":
   result=run(sys.executable,"-B","-c",
       "import ast,sys;ast.parse(open(sys.argv[1]).read())",str(src))
  else:result=run("bash","-n",str(src))
  require(result.returncode==0,"SOURCE_SYNTAX_ERROR")
  prior.append((dest,old,new))
 return prior

def main():
 require(sys.argv[1:] in (["--check"],["--stage"]),"USAGE")
 before=baseline()
 items=preflight()
 emit("PREFLIGHT","PASS")
 emit("AUTO_XRAY_ENABLED","NO")
 if sys.argv[1]=="--check":
  emit("INSTALLED","NO")
  return
 require(BACKUPS.is_dir() and not BACKUPS.is_symlink() and
         BACKUPS.stat().st_uid==0,"BACKUP_LOCATION_UNSAFE")
 snap=Path(tempfile.mkdtemp(dir=BACKUPS,prefix="xray-fixed-repair-"))
 snap.chmod(0o700)
 for dest,old,new in items:
  backup=snap/(dest.name+".previous")
  backup.write_bytes(old);backup.chmod(0o600)
  require(digest(backup.read_bytes())==digest(old),"BACKUP_NOT_VERIFIED")
 done=[]
 try:
  for dest,old,new in items:
   atomic(dest,new)
   done.append((dest,old))
  require(all(digest(dest.read_bytes())==digest(new)
              for dest,old,new in items),"INSTALLED_HASH_MISMATCH")
  require(baseline()==before,"NETWORK_OR_FIXED_CHANGED")
 except Exception:
  for dest,old in reversed(done):
   atomic(dest,old)
  emit("ROLLBACK","PREVIOUS_HELPERS_RESTORED")
  raise
 emit("INSTALLED","PASSIVE")
 emit("BACKUP","VERIFIED")
 emit("FIXED_CHAIN_CHANGED","NO")
 emit("SERVICES_RESTARTED","NO")
 emit("ROUTES_CHANGED","NO")
 emit("AUTO_XRAY_ENABLED","NO")

if __name__=="__main__":
 try:main()
 except Exception as error:
  emit("ERROR",str(error) if isinstance(error,RuntimeError) else "PRECHECK_OR_STAGE_FAILED")
  sys.exit(1)
