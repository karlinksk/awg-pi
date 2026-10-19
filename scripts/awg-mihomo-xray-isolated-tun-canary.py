#!/usr/bin/env python3
"""ISOLATED Mihomo TUN + HY2 -> Xray/VLESS -> HY2 canary.
No live unit change, no routes, no MikroTik or policy changes.
All provider material exists only in private tmpfs and is deleted.
"""
import copy, importlib.util, json, os, pathlib, signal, socket, subprocess, tempfile, time, urllib.request, sys
from importlib.machinery import SourceFileLoader
import yaml

ROOT=pathlib.Path(__file__).resolve().parents[1]
XRAY=pathlib.Path("/usr/local/bin/awg-xray-vless-core")
MIHOMO=pathlib.Path("/usr/local/bin/mihomo")
PROVIDER=pathlib.Path("/var/lib/awg-pbr/mihomo/providers/subscription.yaml")
TUN="awgxtun0"
URL="https://api.openai.com/v1/models"
def run(args,timeout=10):
    return subprocess.run(args,timeout=timeout,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
def output(args):
    p=run(args)
    if p.returncode:raise RuntimeError("PREFLIGHT_FAILED")
    return p.stdout.strip()
def available_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]
def http(port,via_proxy=True,tun=None):
    cmd=["curl","-4","-sS","--noproxy","", "-o","/dev/null",
         "--connect-timeout","8","--max-time","22","-w","%{http_code}"]
    if via_proxy:cmd += ["--proxy",f"http://127.0.0.1:{port}"]
    if tun is not None:
        cmd+=["--interface",tun]
        cmd[cmd.index("--noproxy")+1]="*"
    cmd +=[URL]
    p=run(cmd,timeout=25)
    return "PASS_401" if p.returncode==0 and p.stdout=="401" else "UNVERIFIED"
def wait_port(proc,port):
    for _ in range(55):
        if proc.poll() is not None:return False
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=.10):return True
        except OSError:time.sleep(.12)
    return False
def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
def interface_bytes():
    p=run(["ip","-s","-j","link","show",TUN])
    if p.returncode:return 0
    a=json.loads(p.stdout)[0].get("stats64",{}) or json.loads(p.stdout)[0].get("stats",{})
    return int(a.get("rx",{}).get("bytes",0))+int(a.get("tx",{}).get("bytes",0))
def selector(ctrl,which):
    url=f"http://127.0.0.1:{ctrl}/proxies/AWG-ISOLATED-OUTBOUND"
    request=urllib.request.Request(url,method="PUT",data=json.dumps({"name":which}).encode(),
                                   headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=4) as resp:
        if resp.status not in (200,204):raise RuntimeError("SELECT_FAILED")
    with urllib.request.urlopen(url,timeout=4) as resp:current=json.load(resp).get("now")
    if current!=which:raise RuntimeError("SELECT_UNVERIFIED")
def main():
    assert os.geteuid()==0
    if len(sys.argv)!=2 or sys.argv[1]!="--confirm-isolated":
        raise SystemExit("explicit --confirm-isolated required")
    # Do not allow this optional test to run on a different production Pi:
    # the operator must supply an expected test hostname each time.
    expected=os.environ.get("AWG_ISOLATED_EXPECT_HOST","")
    if not expected or expected!=output(["hostname"]):
        raise SystemExit("AWG_ISOLATED_EXPECT_HOST must match test Pi")
    mode=output(["/usr/local/sbin/awg-route","mode","status"])
    assert "Mode ID: selective" in mode or "Mode ID: transit" in mode
    assert run(["systemctl","is-active","--quiet","awg-mihomo.service"]).returncode==0
    assert run(["systemctl","is-active","--quiet","awg-selection-monitor.service"]).returncode==0
    assert run(["systemctl","is-active","--quiet","awg-xray-vless.service"]).returncode!=0
    assert run(["ip","link","show",TUN]).returncode!=0
    assert "default dev mihomo0" in output(["ip","route","show","table","100"])
    assert "default dev mihomo0" in output(["ip","route","show","table","101"])
    before100=output(["ip","route","show","table","100"])
    before101=output(["ip","route","show","table","101"])
    beforepolicy=output(["/usr/local/sbin/awg-mihomo-node-policy","auto-strategy","status"])
    # Use provider only in RAM from root-protected existing imported source.
    provider=yaml.safe_load(PROVIDER.read_bytes())["proxies"]
    vless=next(n for n in provider if n.get("type")=="vless" and n.get("network")=="xhttp")
    hy2=next(n for n in provider if n.get("type")=="hysteria2")
    import_name="awg_bridge_adaptor_canary"
    spec=importlib.util.spec_from_loader(import_name,SourceFileLoader(import_name,str(ROOT/"src/awg-xray-vless.py")))
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    name="awg_unified_lib_canary"
    spec=importlib.util.spec_from_loader(name,SourceFileLoader(name,str(ROOT/"src/awg-mihomo-unified-nodes.py")))
    uni=importlib.util.module_from_spec(spec);spec.loader.exec_module(uni)
    xray=None; mihomo=None
    with tempfile.TemporaryDirectory(prefix="awg-hy2-xray-tun-",dir="/dev/shm") as t:
        root=pathlib.Path(t);root.chmod(0o700)
        xp=available_port();mp=available_port();cp=available_port()
        # The normal adapter pins the direct physical uplink interface.
        xcfg=uni.build_xray(adapter,vless,xp)
        adapter.atomic_json(root/"xray.json",xcfg)
        # Compare source HY2 contents unchanged, including transport fields.
        native=copy.deepcopy(hy2)
        native["name"]="AWG-ISOLATED-HY2"
        mcfg={
         "mixed-port":mp,"allow-lan":False,"bind-address":"127.0.0.1",
         "mode":"rule","log-level":"silent","ipv6":False,
         "external-controller":f"127.0.0.1:{cp}",
         "profile":{"store-selected":False,"store-fake-ip":False},
         "proxies":[native,{"name":"AWG-ISOLATED-XRAY","type":"socks5",
                             "server":"127.0.0.1","port":xp,"udp":False}],
         "proxy-groups":[{"name":"AWG-ISOLATED-OUTBOUND","type":"select",
                          "proxies":["AWG-ISOLATED-HY2","AWG-ISOLATED-XRAY"]}],
         "rules":["MATCH,AWG-ISOLATED-OUTBOUND"],
         "tun":{"enable":True,"device":TUN,"stack":"mips",
                "auto-route":False,"auto-redirect":False,"auto-detect-interface":True}}
        (root/"mihomo.yaml").write_text(yaml.safe_dump(mcfg,sort_keys=False,allow_unicode=True))
        (root/"mihomo.yaml").chmod(0o600)
        state=root/"mihomo-state";state.mkdir(mode=0o700)
        try:
            a=run([str(XRAY),"run","-test","-c",str(root/"xray.json")])
            assert a.returncode==0,"XRAY_CONFIG_INVALID"
            a=run([str(MIHOMO),"-t","-d",str(state),"-f",str(root/"mihomo.yaml")],timeout=13)
            assert a.returncode==0,"ISOLATED_MIHOMO_CONFIG_INVALID"
            with (root/"xray.log").open("wb") as xl,(root/"mihomo.log").open("wb") as ml:
                xray=subprocess.Popen([str(XRAY),"run","-c",str(root/"xray.json")],
                                      stdin=subprocess.DEVNULL,stdout=xl,stderr=subprocess.STDOUT)
                assert wait_port(xray,xp),"XRAY_START_FAILED"
                mihomo=subprocess.Popen([str(MIHOMO),"-d",str(state),"-f",str(root/"mihomo.yaml")],
                                        stdin=subprocess.DEVNULL,stdout=ml,stderr=subprocess.STDOUT)
                assert wait_port(mihomo,mp),"ISOLATED_MIHOMO_START_FAILED"
                for _ in range(25):
                    if run(["ip","link","show",TUN]).returncode==0:break
                    time.sleep(.12)
                else:raise RuntimeError("ISOLATED_TUN_NOT_CREATED")
                print("ISOLATED_TUN_CREATED=PASS",flush=True)
                for label,selected in (("HY2_BEFORE","AWG-ISOLATED-HY2"),
                                       ("XRAY_VLESS","AWG-ISOLATED-XRAY"),
                                       ("HY2_RESTORED","AWG-ISOLATED-HY2")):
                    selector(cp,selected)
                    prox=http(mp)
                    before=interface_bytes()
                    through_tun=http(mp,via_proxy=False,tun=TUN)
                    moved=interface_bytes()>before
                    print(label+"_MIHOMO_PROXY="+prox,flush=True)
                    print(label+"_TUN_HTTPS="+through_tun,flush=True)
                    print(label+"_TUN_PACKETS="+("OBSERVED" if moved else "NOT_OBSERVED"),flush=True)
        finally:
            stop(mihomo);stop(xray)
            if run(["ip","link","show",TUN]).returncode==0:
                run(["ip","link","del",TUN])
    after100=output(["ip","route","show","table","100"])
    after101=output(["ip","route","show","table","101"])
    afterpolicy=output(["/usr/local/sbin/awg-mihomo-node-policy","auto-strategy","status"])
    assert before100==after100 and before101==after101
    assert beforepolicy==afterpolicy
    assert run(["systemctl","is-active","--quiet","awg-mihomo.service"]).returncode==0
    assert run(["systemctl","is-active","--quiet","awg-selection-monitor.service"]).returncode==0
    print("LIVE_PI_TRANSPORT_AND_ROUTES_UNMODIFIED=PASS",flush=True)
    print("ACTUAL_LAN_CLIENT_TEST=NOT_PERFORMED",flush=True)
if __name__=="__main__":main()
