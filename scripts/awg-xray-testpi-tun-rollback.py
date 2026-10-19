#!/usr/bin/env python3
"""Root-owned autonomous rollback for one authorized live Mihomo Xray canary."""
import fcntl,hashlib,json,os,pathlib,shutil,subprocess,sys,time,urllib.request
ROOT=pathlib.Path("/var/backups/awg-gateway")
CONFIG=pathlib.Path("/etc/awg-pbr/transports/mihomo/config.yaml")
SELECTED=pathlib.Path("/var/lib/awg-pbr/xray-vless/selected.json")
RENDERER=pathlib.Path("/usr/local/sbin/awg-mihomo-config")
OVERRIDE=pathlib.Path("/run/systemd/system/awg-mihomo.service.d/90-awg-xray-live-canary.conf")
UNIT="awg-mihomo.service"
def call(args,timeout=30):
 return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
def restore(path,snapshot,pre):
 if pre:
  tmp=path.with_name(path.name+".rollback-canary")
  shutil.copy2(snapshot,tmp)
  os.chmod(tmp,0o600)
  os.replace(tmp,path)
 else:
  path.unlink(missing_ok=True)
def api_group():
 try:
  return json.load(urllib.request.urlopen("http://127.0.0.1:9090/proxies/AWG-MIHOMO",timeout=3)).get("now")
 except Exception:return None
def main():
 if os.geteuid()!=0 or len(sys.argv)!=2:raise SystemExit("ROOT_AND_SNAPSHOT_REQUIRED")
 path=pathlib.Path(sys.argv[1])
 if path.parent!=ROOT or not path.name.startswith("xray-live-switch-") or path.is_symlink():
  raise SystemExit("INVALID_SNAPSHOT_PATH")
 with (path/"state.lock").open("a") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=json.loads((path/"state.json").read_text())
  if state.get("state")=="restored":
   print("LIVE_CANARY_ROLLBACK=ALREADY_RESTORED",flush=True)
   return
  if state.get("state")!="armed":raise SystemExit("SNAPSHOT_NOT_ARMED")
  if call(["hostname"]).stdout.strip()!="awg-upgrade":raise SystemExit("WRONG_TEST_HOST")
  print("LIVE_CANARY_ROLLBACK=STARTED",flush=True)
  # Restore the actual ExecStartPre config generator and remove the canary
  # environment override BEFORE restarting. Otherwise the service would
  # immediately regenerate Xray again from the stale test-only renderer.
  original_hash=state.get("old_config_sha256")
  current_same=(hashlib.sha256(CONFIG.read_bytes()).hexdigest()==original_hash)
  restore(CONFIG,path/"config.previous",True)
  if state.get("renderer_preexisting"):
   restore(RENDERER,path/"renderer.previous",True)
   RENDERER.chmod(0o755)
  OVERRIDE.unlink(missing_ok=True)
  if OVERRIDE.parent.is_dir() and not list(OVERRIDE.parent.iterdir()):
   OVERRIDE.parent.rmdir()
  reload_ok=call(["systemctl","daemon-reload"],timeout=20).returncode==0
  if current_same and call(["systemctl","is-active","--quiet",UNIT],timeout=6).returncode==0:
   restored=reload_ok
   print("LIVE_CANARY_ROLLBACK=NO_MIHOMO_RESTART_NEEDED",flush=True)
  else:
   restored=reload_ok and call(["systemctl","restart",UNIT],timeout=28).returncode==0
  call(["systemctl","stop","awg-xray-vless.service"],timeout=15)
  restore(SELECTED,path/"selection.previous",state.get("selection_preexisting",False))
  if restored:
   # Wait for controller after daemon restart before restoring selection.
   old=state.get("previous_group")
   for _ in range(42):
    current=api_group()
    if current is not None:break
    time.sleep(.25)
   else:current=None
   if old and current!=old:
    request=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO",
     method="PUT",data=json.dumps({"name":old}).encode(),headers={"Content-Type":"application/json"})
    try:urllib.request.urlopen(request,timeout=4).close()
    except Exception:pass  # final controller state is authoritative
  # Route-table preservation is mandatory in Transit. A Mihomo restart
  # may remove kernel device routes; restore exactly the original defaults.
  r100=call(["ip","route","show","table","100"]).stdout.strip()
  r101=call(["ip","route","show","table","101"]).stdout.strip()
  for table,previous in (("100",r100),("101",r101)):
   if "default dev mihomo0" not in previous:
    fix=call(["ip","route","replace","table",table,"default","dev","mihomo0"],timeout=8)
    restored=restored and fix.returncode==0
  r100=call(["ip","route","show","table","100"]).stdout.strip()
  r101=call(["ip","route","show","table","101"]).stdout.strip()
  # Independently evaluate the *actual restored state*, not transient
  # systemctl restart/PUT exit codes during startup. A transient nonzero
  # result must not leave an armed watchdog if the gateway has recovered.
  problems=[]
  if hashlib.sha256(CONFIG.read_bytes()).hexdigest()!=original_hash:
   problems.append("CONFIG_SHA_MISMATCH")
  if (state.get("renderer_preexisting") and
      hashlib.sha256(RENDERER.read_bytes()).hexdigest()!=state.get("old_renderer_sha256")):
   problems.append("RENDERER_SHA_MISMATCH")
  if OVERRIDE.exists():problems.append("CANARY_OVERRIDE_PRESENT")
  if SELECTED.exists()!=state.get("selection_preexisting",False):
   problems.append("XRAY_SELECTION_STATE_MISMATCH")
  if call(["systemctl","is-active","--quiet","awg-xray-vless.service"],timeout=6).returncode==0:
   problems.append("XRAY_STILL_RUNNING")
  if "default dev mihomo0" not in r100 or "default dev mihomo0" not in r101:
   problems.append("ROUTE_DEFAULTS_MISSING")
  if pathlib.Path("/etc/awg-pbr/mode").read_text().strip()!=state.get("mode"):
   problems.append("MODE_CHANGED")
  if call(["systemctl","is-active","--quiet",UNIT],timeout=6).returncode!=0:
   problems.append("MIHOMO_INACTIVE")
  for _ in range(30):
   if api_group()==state.get("previous_group"):break
   time.sleep(.2)
  else:problems.append("NODE_NOT_RESTORED")
  if problems:
   for item in problems:print("LIVE_CANARY_ROLLBACK_REVIEW="+item,flush=True)
   print("LIVE_CANARY_ROLLBACK=INCOMPLETE_REVIEW_REQUIRED",flush=True)
   raise SystemExit(3)
  if not restored:
   print("LIVE_CANARY_ROLLBACK=TRANSIENT_UNIT_RESULT_OVERRIDDEN_BY_STATE_PROOF",flush=True)
  state["state"]="restored"
  state["restored_at"]=int(time.time())
  tmp=path/"state.json.tmp"
  tmp.write_text(json.dumps(state));tmp.chmod(0o600);os.replace(tmp,path/"state.json")
  print("LIVE_CANARY_ROLLBACK=RESTORED",flush=True)
  print("LIVE_CANARY_CONFIG_RESTORED=YES",flush=True)
  print("LIVE_CANARY_XRAY_STOPPED=YES",flush=True)
if __name__=="__main__":main()
