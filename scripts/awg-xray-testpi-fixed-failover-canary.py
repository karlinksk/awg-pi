#!/usr/bin/env python3
"""Controlled REAL Mihomo-underlay loss -> automatic FIXED Xray handoff.

TEST PI ONLY. No RouterOS/MikroTik change. Blocks only the 3 explicitly
configured Mihomo candidate endpoints on the test Pi with nft, keeping the
Xray endpoint unblocked. Test-only independent rescue timers remove the nft
fault and verify original HY2 recovery. Do not install in production.

The test is PASS only if the selection monitor autonomously selects the Xray
VLESS candidate and both actual TUN HTTPS and independent recovery pass.
"""
import importlib.util,ipaddress,json,os,pathlib,re,socket,subprocess,sys,time
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
RESCUE_SOURCE=ROOT/"scripts/awg-xray-testpi-fixed-failover-rescue.py"
spec=importlib.util.spec_from_file_location("awg_xray_fixed_test_rescue",RESCUE_SOURCE)
rescue=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rescue)
TABLE="awg_xray_fixed_test"
COMMENT="AWG-XRAY-FIXED-TEST"
XRAY_INDEX=1

def emit(k,v):print("XRAY_FIXED_FAILOVER_TEST_"+k+"="+str(v),flush=True)
def require(p,code):
 if not p:raise RuntimeError(code)
def call(*args,timeout=16):
 return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,text=True,timeout=timeout)
def try_run(*args,timeout=16):
 r=call(*args,timeout=timeout)
 require(r.returncode==0,"COMMAND_FAILED_"+pathlib.Path(args[0]).name)
 return r.stdout.strip()
def preflight():
 old,xray=rescue.preflight()
 installed=[
   (ROOT/"src/awg-mihomo-node-policy",pathlib.Path("/usr/local/sbin/awg-mihomo-node-policy")),
   (ROOT/"src/awg-xray-live-backend.py",pathlib.Path("/usr/local/sbin/awg-xray-live-backend"))]
 for src,dst in installed:
  require(src.is_file() and dst.is_file() and rescue.sha(src)==rescue.sha(dst),
          "INSTALLED_HELPER_HASH_MISMATCH")
 require(not rescue.active("awg-xray-vless.service"),"XRAY_NOT_PASSIVE")
 mode=pathlib.Path("/etc/awg-pbr/transports/mihomo/service-eligibility.mode")
 ready=pathlib.Path("/etc/awg-pbr/transports/mihomo/ready-auto.mode")
 # This canary makes no exception to user-selected service readiness policy.
 # Any required ChatGPT/YouTube 24-frame READY screening must be tested
 # independently. This test covers the deliberately disabled paid-provider mode.
 require((mode.read_text().strip() if mode.exists() else "off")=="off" and
         (ready.read_text().strip() if ready.exists() else "0") in ("0","off"),
         "SERVICE_READY_POLICY_MUST_BE_DISABLED_BY_USER")
 # Never enable opt-in persistently or in selection-monitor systemd unit.
 env=call("systemctl","show","--property=Environment","awg-selection-monitor.service",timeout=9)
 require(env.returncode==0 and
         "MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1" not in env.stdout,
         "PERMANENT_AUTO_XRAY_FORBIDDEN")
 chain=[n.strip() for n in rescue.CHAIN.read_text().splitlines() if n.strip()]
 require(len(chain)==4 and chain[0]==old and chain[-1]==xray,
         "EXPECTED_FOUR_NODE_CHAIN")
 doc=yaml.safe_load(rescue.PROVIDER.read_bytes())
 nodes=doc.get("proxies") if isinstance(doc,dict) else None
 require(isinstance(nodes,list),"PROVIDER_INVALID")
 by_name={}
 for n in nodes:
  if isinstance(n,dict) and isinstance(n.get("name"),str):
   by_name.setdefault(n["name"],[]).append(n)
 candidates=[]
 for name in chain:
  matches=by_name.get(name,[])
  require(len(matches)==1,"DUPLICATE_OR_MISSING_CURRENT_NODE")
  node=matches[0]
  if name==xray:
   require(node.get("type")=="vless" and
       node.get("network") in ("xhttp","grpc"),"NOT_XRAY_LAST")
  else:
   require(node.get("type") in ("hysteria2","ss","vless","vmess","trojan"),
           "UNSUPPORTED_MIHOMO_TEST_NODE")
  host=node.get("server");port=node.get("port")
  require(isinstance(host,str) and len(host)<254 and
          type(port)==int and 1<=port<=65535,"ENDPOINT_INVALID")
  addresses=set()
  for entry in socket.getaddrinfo(host,port,family=socket.AF_INET,
                                  type=socket.SOCK_STREAM):
   addr=ipaddress.ip_address(entry[4][0])
   require(addr.is_global,"PRIVATE_ENDPOINT_WOULD_BLOCK_LAN")
   addresses.add(str(addr))
  require(addresses and len(addresses)<=8,"ENDPOINT_RESOLUTION_AMBIGUOUS")
  candidates.append((name,port,addresses))
 endpoint_xray=(candidates[-1][1],candidates[-1][2])
 for _,port,ips in candidates[:-1]:
  require(not (port==endpoint_xray[0] and bool(ips&endpoint_xray[1])),
          "SAME_ENDPOINT_AS_XRAY_FORBIDDEN")
 # Exact candidate identity from current provider, not merely an old index.
 result=try_run("/usr/local/sbin/awg-mihomo-unified-nodes","resolve",xray)
 fields=dict(v.split("=",1) for v in result.splitlines() if "=" in v)
 require(fields.get("NODE_ENGINE")=="XRAY" and
         fields.get("NODE_BASIC_NETWORK")=="NETWORK_OK" and
         fields.get("NODE_INDEX") and fields["NODE_INDEX"].isdigit(),
         "XRAY_NETWORK_CACHE_NOT_FRESH")
 require(fields.get("NODE_PROVIDER_SHA256")==rescue.sha(rescue.PROVIDER),
         "XRAY_PROVIDER_ROTATED")
 require(call("nft","list","table","inet",TABLE,timeout=7).returncode!=0,
         "TEST_FAULT_TABLE_ALREADY_EXISTS")
 require(call("systemctl","is-enabled","--quiet","awg-xray-vless.service").returncode!=0,
         "XRAY_ALREADY_AUTOSTART_ENABLED")
 return old,xray,candidates

def build_nft(candidates):
 rules=[f"table inet {TABLE} {{",
        " chain block_output {",
        "  type filter hook output priority -145; policy accept;"]
 seen=set()
 for name,port,ips in candidates[:-1]:
  for ip in sorted(ips):
   for protocol in ("udp","tcp"):
    key=(ip,port,protocol)
    if key in seen:continue
    seen.add(key)
    rules.append(f'  ip daddr {ip} {protocol} dport {port} counter drop comment "{COMMENT}"')
 require(0<len(seen)<=48,"INVALID_RULE_COUNT")
 rules+=[" }","}"]
 return "\n".join(rules)+"\n"

def install_fault(snap,candidates):
 rescue.jsonput(snap/"fault.json",
                {"kind":"nft_endpoint_blackhole","table":TABLE})
 nft_script=snap/"fault.nft"
 rescue.atomic(nft_script,build_nft(candidates).encode())
 # The independent rescue knows the marker BEFORE any nft mutation.
 rc=call("nft","-f",str(nft_script),timeout=12)
 require(rc.returncode==0,"NFT_TEST_FAULT_INSTALL_FAILED")
 proof=call("nft","list","table","inet",TABLE,timeout=8)
 require(proof.returncode==0 and COMMENT in proof.stdout and
         "chain block_output" in proof.stdout,
         "TEST_FAULT_NOT_VERIFIED")

def proof_xray(name):
 if rescue.CURRENT.read_text().strip()!=name or not rescue.active(
       "awg-xray-vless.service") or not rescue.active("awg-mihomo.service"):
  return False
 if not rescue.healthy_guard() or not rescue.openai():return False
 try:
  return rescue.controller_now()==rescue.LOCAL and all(
      "default dev mihomo0" in s for s in rescue.routes())
 except Exception:return False

def execute():
 old,xray,candidates=preflight()
 emit("PREFLIGHT","PASS")
 if sys.argv[1]=="--check":
  emit("FAULT_INSTALLED","NO");return
 require(sys.argv[1]=="--run","USAGE")
 # The automatic selection monitor gets a test-only environment override.
 # It must be restarted only AFTER independent rescue timers are armed.
 snap=rescue.arm()
 emit("RESCUE","TWO_INDEPENDENT_TIMERS")
 proof=False
 try:
  install_fault(snap,candidates)
  emit("FAULT","MIHOMO_ENDPOINTS_ONLY")
  # Test-only /run unit override; independent rescue removes it even after
  # an SSH interruption. No persistent opt-in or installer change.
  unit=rescue.MONITOR_OVERRIDE
  require(not unit.exists() and not unit.is_symlink(),
          "MONITOR_OVERRIDE_ALREADY_PRESENT")
  unit.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  rescue.atomic(unit,rescue.MONITOR_OWNED)
  try_run("systemctl","daemon-reload",timeout=15)
  try_run("systemctl","restart","awg-selection-monitor.service",timeout=20)
  env=try_run("systemctl","show","--property=Environment",
              "awg-selection-monitor.service",timeout=12)
  require("MIHOMO_XRAY_FIXED_FAILOVER_CANARY=1" in env,
          "SELECTION_MONITOR_TEST_OPTIN_NOT_ACTIVE")
  emit("AUTO_SELECTION_MONITOR","TEST_ONLY_OPTIN")
  start=time.monotonic()
  max_switch=rescue.TIMER_A-25
  consecutive=0
  while time.monotonic()-start<max_switch:
   if proof_xray(xray):
    consecutive+=1
    if consecutive>=2:
     proof=True
     emit("AUTO_TUN_XRAY","PASS_401")
     break
   else:consecutive=0
   time.sleep(3)
  emit("AUTO_FAILOVER","PASS" if proof else "NOT_VERIFIED")
  # Even successful Xray is returned to the original known-good node ONLY
  # in the test stand, after the independent timer removes the induced fault.
  deadline=time.monotonic()+rescue.TIMER_B+45
  recovered=False
  while time.monotonic()<deadline:
   state=json.loads((snap/"state.json").read_text())
   if state.get("result")=="PASS":
    recovered=(state.get("status") in ("restored","unchanged"))
    break
   time.sleep(3)
  require(recovered,"INDEPENDENT_RESCUE_NOT_COMPLETE")
  final=json.loads((snap/"state.json").read_text())
  require(final.get("status")=="restored" and
          rescue.CURRENT.read_text().strip()==old and
          not rescue.active("awg-xray-vless.service") and
          rescue.active("awg-mihomo.service") and
          rescue.healthy_guard() and rescue.openai(),
          "OLD_HY2_NOT_INDEPENDENTLY_RESTORED")
  emit("INDEPENDENT_RECOVERY","PASS")
  emit("FIXED_CHAIN_CHANGED","NO")
  require(proof,"XRAY_AUTO_FAILOVER_NOT_OBSERVED")
  emit("RESULT","PASS_AUTO_FAILOVER_AND_RESTORE")
 finally:
  # Independent systemd timer remains armed if the test process exits.
  emit("RECOVERY","INDEPENDENT_TIMER_STILL_ARMED")

if __name__=="__main__":
 try:
  require(os.geteuid()==0 and socket.gethostname()=="awg-upgrade" and
          sys.argv[1:] in (["--check"],["--run"]),"ROOT_TEST_PI_ONLY")
  execute()
 except Exception as exc:
  emit("RESULT","FAIL_REVIEW_REQUIRED")
  emit("ERROR",str(exc) if isinstance(exc,RuntimeError) else "PRECHECK_FAILED")
  sys.exit(1)
