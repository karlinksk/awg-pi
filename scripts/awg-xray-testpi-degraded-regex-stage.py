#!/usr/bin/env python3
"""Test Pi only: atomically stage one verified degraded-route-regex correction.

No failover activation, node choice, route changes, service restarts, DNS or
router edits. Validates that the ONLY delta is correcting a double-escaped
regex in the previously passively installed Xray backend.
"""
import difflib,hashlib,os,pathlib,re,socket,subprocess,sys,tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/awg-xray-live-backend.py"
LIVE=pathlib.Path("/usr/local/sbin/awg-xray-live-backend")
OLD_SHA="ec4c86a9270b5a72e3f4282347311f110bdd7ed6d89b1d8b8a2cf88b679cf6c8"
BASE=pathlib.Path("/var/backups/awg-gateway")
MODE=pathlib.Path("/etc/awg-pbr/mode")

def emit(k,v):print("XRAY_ROUTE_REGEX_STAGE_"+k+"="+str(v),flush=True)
def require(flag,reason):
 if not flag:raise RuntimeError(reason)
def sha(data):return hashlib.sha256(data).hexdigest()
def run(*args,timeout=15):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,timeout=timeout)
def active(unit):return run("systemctl","is-active","--quiet",unit,timeout=5).returncode==0
def network():
 require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade","TEST_PI_ROOT_ONLY")
 require(MODE.read_text().strip()=="transit","TRANSIT_ONLY")
 require(all(active(x) for x in ("awg-mihomo.service","dnsmasq.service",
             "awg-selection-monitor.service","ssh.service")),"ORIGINAL_NOT_HEALTHY")
 require(not active("awg-xray-vless.service"),"XRAY_ALREADY_ACTIVE")
 status=run("/usr/local/sbin/awg-transit-routing","status")
 require(status.returncode==0 and all(x in status.stdout.splitlines() for x in
    ("Transit guard: SAFE","Transit policy rule: ACTIVE","Transit VPN table: READY")),
    "TRANSIT_NOT_SAFE")
 routes=[]
 for t in ("100","101"):
  r=run("ip","-4","route","show","table",t,timeout=6)
  require(r.returncode==0 and re.search(
          r"(?m)^default\s+dev\s+mihomo0(?:\s|$)",r.stdout),"ROUTE_NOT_ORIGINAL")
  routes.append(r.stdout)
 code=run("curl","-q","-4","--noproxy","*","--interface","mihomo0",
          "--connect-timeout","6","--max-time","16","-sS","-o","/dev/null",
          "-w","%{http_code}","https://api.openai.com/v1/models",timeout=22)
 require(code.returncode==0 and code.stdout=="401","TUN_NOT_401")
 require(run("systemctl","is-enabled","awg-xray-vless.service").stdout.strip()=="disabled",
         "XRAY_AUTOSTART_UNEXPECTED")
 e=run("systemctl","show","--property=Environment","awg-selection-monitor.service")
 require(e.returncode==0 and "MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1" not in e.stdout,
         "XRAY_AUTO_ALREADY_ENABLED")
 return tuple(routes)

def inspect():
 require(SOURCE.is_file() and LIVE.is_file() and not SOURCE.is_symlink()
         and not LIVE.is_symlink(),"UNTRUSTED_HELPER_PATH")
 old=LIVE.read_bytes();new=SOURCE.read_bytes()
 require(sha(old)==OLD_SHA,"UNREVIEWED_INSTALLED_EXECUTOR")
 changes=[(i,a,b) for i,(a,b) in enumerate(zip(old.splitlines(),new.splitlines()))
          if a!=b]
 require(len(changes)==1 and len(old.splitlines())==len(new.splitlines()),
         "NOT_A_SINGLE_LINE_FIX")
 _,bad,good=changes[0]
 require(b"mihomo0" in bad and b"mihomo0" in good and
         b"x.strip()" in bad and b"x.strip()" in good and
         bad.replace(bytes((92,92,115)),bytes((92,115)))==good,
         "UNEXPECTED_PATCH_CONTENT")
 r=run(sys.executable,"-B","-c","import ast,sys;ast.parse(open(sys.argv[1]).read())",
       str(SOURCE),timeout=8)
 require(r.returncode==0,"SOURCE_NOT_PYTHON")
 return old,new

def atomic(path,data):
 fd,name=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".regex-")
 try:
  os.fchmod(fd,0o755);os.fchown(fd,0,0)
  with os.fdopen(fd,"wb") as stream:
   stream.write(data);stream.flush();os.fsync(stream.fileno())
  os.replace(name,path)
 finally:
  if os.path.lexists(name):os.unlink(name)

def main():
 require(sys.argv[1:] in (["--check"],["--stage"]),"USAGE")
 prior=network();old,new=inspect()
 emit("PREFLIGHT","PASS")
 emit("AUTO_XRAY_ENABLED","NO")
 if sys.argv[1]=="--check":
  emit("INSTALLED","NO")
  return
 require(BASE.is_dir() and not BASE.is_symlink() and BASE.stat().st_uid==0,
         "BACKUP_BASE_UNTRUSTED")
 snap=pathlib.Path(tempfile.mkdtemp(prefix="xray-degraded-regex-",dir=BASE))
 snap.chmod(0o700)
 copy=snap/"xray-backend.previous"
 copy.write_bytes(old);copy.chmod(0o600)
 require(sha(copy.read_bytes())==OLD_SHA,"BACKUP_HASH_FAILED")
 try:
  atomic(LIVE,new)
  require(sha(LIVE.read_bytes())==sha(new),"INSTALLED_HASH_MISMATCH")
  require(network()==prior,"LIVE_NETWORK_CHANGED")
 except Exception:
  atomic(LIVE,old)
  emit("ROLLBACK","OLD_EXECUTOR_RESTORED")
  raise
 emit("INSTALLED","PASSIVE")
 emit("BACKUP","VERIFIED")
 emit("SERVICES_RESTARTED","NO")
 emit("ROUTES_CHANGED","NO")
 emit("AUTO_XRAY_ENABLED","NO")

if __name__=="__main__":
 try:main()
 except Exception as exc:
  emit("RESULT","FAIL_REVIEW_REQUIRED")
  emit("ERROR",str(exc) if isinstance(exc,RuntimeError) else "CHECK_FAILED")
  sys.exit(1)
