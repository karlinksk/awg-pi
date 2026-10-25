#!/usr/bin/env python3
"""Test Pi only: passively stage opt-in FIXED Xray transaction dispatcher.

Keeps the experimental integration DISABLED by default. No service restarts,
no change to FIXED policy, active node, routes, DNS, SSH, or MikroTik.
Restores previous helper if any write/postcheck fails.
"""
import hashlib
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-mihomo-node-policy"
LIVE=Path("/usr/local/sbin/awg-mihomo-node-policy")
OLD_SHA="47f007a489d610bb4ab13e6c3a98837fbb11dae96468c100ca9feb9ad5301175"
MODE=Path("/etc/awg-pbr/mode")
POLICY_MODE=Path("/etc/awg-pbr/transports/mihomo/node-policy.mode")
CURRENT=Path("/etc/awg-pbr/transports/mihomo/node-name")
CHAIN=Path("/etc/awg-pbr/transports/mihomo/node-policy.nodes")
SELECTED=Path("/var/lib/awg-pbr/xray-vless/selected.json")
BACKUPS=Path("/var/backups/awg-gateway")
LOCK=Path("/run/awg-maintenance.lock")
BRIDGES=(
 Path("/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
 Path("/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf"),
 Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf"),
)

def result(k,v):print("XRAY_FIXED_DISPATCH_STAGE_"+k+"="+str(v),flush=True)
def require(x,message):
 if not x:raise RuntimeError(message)
def sha(data):return hashlib.sha256(data).hexdigest()
def run(*args,secs=12):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
           stderr=subprocess.DEVNULL,text=True,timeout=secs)
def active(unit):return run("systemctl","is-active","--quiet",unit,secs=5).returncode==0
def state():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","ROOT_TEST_PI_ONLY")
 require(MODE.read_text().strip()=="transit" and
         POLICY_MODE.read_text().strip()=="fixed","TRANSIT_FIXED_REQUIRED")
 require(active("awg-mihomo.service") and active("dnsmasq.service")
         and active("awg-selection-monitor.service") and active("ssh.service"),
         "LIVE_SERVICES_NOT_ACTIVE")
 require(not active("awg-xray-vless.service"),"XRAY_SERVICE_ALREADY_STARTED")
 require(not SELECTED.exists() and not any(x.exists() or x.is_symlink() for x in BRIDGES),
         "CROSS_CORE_ALREADY_STAGED")
 safety=run("/usr/local/sbin/awg-transit-routing","status",secs=12)
 require(safety.returncode==0 and
         all(k in safety.stdout.splitlines() for k in
         ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
         "TRANSIT_GUARD_UNSAFE")
 routes=[]
 for t in ("100","101"):
  route=run("ip","-4","route","show","table",t)
  require(route.returncode==0 and
     re.search(r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",route.stdout),
     "ROUTING_CHANGED")
  routes.append(route.stdout)
 validate=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
   "--connect-timeout","6","--max-time","17","-sS","-o","/dev/null",
   "-w","%{http_code}","https://api.openai.com/v1/models",secs=23)
 require(validate.returncode==0 and validate.stdout=="401","TUN_NOT_HEALTHY")
 return (tuple(routes),sha(CURRENT.read_bytes()),sha(CHAIN.read_bytes()),
         sha(POLICY_MODE.read_bytes()))

def atomic_install(path,data):
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".xray-")
 try:
  os.fchmod(fd,0o755);os.fchown(fd,0,0)
  with os.fdopen(fd,"wb") as f:
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.lexists(tmp):os.unlink(tmp)

def main():
 require(sys.argv[1:] in (["--check"],["--stage"]),"USAGE")
 before=state()
 require(SOURCE.is_file() and not SOURCE.is_symlink() and
         LIVE.is_file() and not LIVE.is_symlink(),"MISSING_SOURCE_OR_LIVE_POLICY")
 old=LIVE.read_bytes()
 require(sha(old)==OLD_SHA,"UNREVIEWED_INSTALLED_POLICY")
 updated=SOURCE.read_bytes()
 require(b'MIHOMO_XRAY_FIXED_FAILOVER_CANARY' in updated and
         b'XRAY_TRANSACTION_ABORTED_REVIEW_REQUIRED' in updated,
         "MISSING_EXPERIMENTAL_GUARD")
 check=run("bash","-n",str(SOURCE),secs=8)
 require(check.returncode==0,"SHELL_SYNTAX_BAD")
 # The Xray opt-in must be absent from the running selection-monitor unit.
 env=run("systemctl","show","--property=Environment","awg-selection-monitor.service")
 require(env.returncode==0 and "MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1" not in env.stdout,
         "LIVE_EXPERIMENTAL_OPTIN_ALREADY_ENABLED")
 result("PREFLIGHT","PASS")
 result("OPTIN_DEFAULT","OFF")
 if sys.argv[1]=="--check":
  result("INSTALLED","NO")
  return
 require(BACKUPS.is_dir() and not BACKUPS.is_symlink() and
         BACKUPS.stat().st_uid==0,"BACKUP_ROOT_REQUIRED")
 snap=Path(tempfile.mkdtemp(dir=BACKUPS,prefix="xray-fixed-dispatch-"))
 snap.chmod(0o700)
 saved=snap/"node-policy.previous"
 saved.write_bytes(old);saved.chmod(0o600)
 require(sha(saved.read_bytes())==OLD_SHA,"BACKUP_HASH_BAD")
 try:
  atomic_install(LIVE,updated)
  require(sha(LIVE.read_bytes())==sha(updated),"INSTALLED_HASH_BAD")
  require(state()==before,"LIVE_STATE_CHANGED")
 except Exception:
  atomic_install(LIVE,old)
  result("ROLLBACK","OLD_POLICY_RESTORED")
  raise
 result("INSTALLED","PASSIVE")
 result("SNAPSHOT","VERIFIED")
 result("NODE_POLICY_CHANGED","NO")
 result("SERVICES_RESTARTED","NO")
 result("ROUTES_CHANGED","NO")
 result("AUTO_XRAY_ENABLED","NO")

if __name__=="__main__":
 try:main()
 except Exception as err:
  result("ERROR",str(err) if isinstance(err,RuntimeError) else "PRECHECK_FAILED")
  sys.exit(1)
