#!/usr/bin/env python3
"""TEMPORARY, OWNER-TOKEN-scoped YouTube HTTPS zapret2 A/B, 2026-10.

Changes to MikroTik limited to ONE src+dst+tcp/443 mangle accept rule,
with a router-local 3-minute one-shot cleanup scheduler INSTALLED FIRST.
The existing SSTP/RouteOS routes/services are never disabled or replaced.
An independent Pi systemd timer cleans namespace and PID after 145s.
All test files are root-only /run or token-scoped executable /dev/shm.
Operator may interrupt; all normal teardown stays in finally.
"""
from __future__ import annotations
import datetime
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time

HOME = Path("/home/karlinks")
TARGET = "142.251.157.4"
PORT = "443"
QUEUE = "239"
SITES = (("YOUTUBE_204", "/generate_204"), ("YOUTUBE_HOME", "/"))
UPSTREAM = Path("/run/user/1000/awg-zapret2-official-v1.0.5.2/zapret2-v1.0.5.2")
BIN = UPSTREAM / "binaries/linux-arm64/nfqws2"
LIB = UPSTREAM / "lua/zapret-lib.lua"
ANTIDPI = UPSTREAM / "lua/zapret-antidpi.lua"
EXPECTED_SHA = "8788877cd4b3140357dd10524832ca508d47055efae072bc426b887bfea253a7"

def import_module(name,path):
    sp = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod

base = import_module("awg_yt_base", HOME / "awg-dpi-vless-baseline.py")
sandbox = base.sandbox

def cmd(argv, timeout=8, check=True):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError("command_failed_" + Path(argv[0]).name)
    return p

def ros(command, check=True):
    # Root cannot read the user's SSH identity. Key-scoped gpt-ops has only
    # ssh/read/write/test permissions, and the RouterOS management port 8384
    # remains reachable over Pi's unchanged 192.168.112.34 LAN address.
    p = cmd(["runuser","-u","karlinks","--","ssh",
             "-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
             "-o","ConnectTimeout=4","mikrotik-gpt",command],
            timeout=11,check=check)
    if check and p.stdout.strip().lower().startswith("failure"):
        raise RuntimeError("routeros_command_failure")
    return p.stdout.replace("\r","")

def router_count(kind, item):
    if kind == "rule":
        command = f'/ip firewall mangle print count-only where comment={item}'
    else:
        command = f'/system scheduler print count-only where name={item}'
    output = ros(command).strip()
    return int(output)

def router_guard(comment, schedule):
    if router_count("rule", comment) or router_count("schedule", schedule):
        raise RuntimeError("existing_test_guard_or_rule")
    # Router's own clock is synchronized with Pi. Router-local guard survives
    # Pi SSH failure, Pi script SIGKILL and expiry of the Pi recovery timer.
    event = (f"/ip firewall mangle remove [find where comment={comment}]; "
             f"/system scheduler remove [find where name={schedule}]")
    statement = (f'/system scheduler add name={schedule} '
                 'start-date=[/system clock get date] '
                 'start-time=([/system clock get time] + 00:03:00) '
                 f'interval=0s policy=read,write,test on-event="{event}"')
    ros(statement)
    if router_count("schedule", schedule) != 1:
        raise RuntimeError("router_guard_not_confirmed")
    detail = ros(f"/system scheduler print detail where name={schedule}")
    if "next-run=" not in detail or "run-count=0" not in detail:
        raise RuntimeError("router_guard_no_next_run")
    print("ROUTER_ROLLBACK_GUARD=ARMED approx_3_minutes",flush=True)

def router_insert_rule(src, comment, schedule):
    if router_count("schedule", schedule) != 1:
        raise RuntimeError("router_guard_missing_before_rule")
    host_ip = str(__import__("ipaddress").IPv4Address(src))
    # RouterOS transit marking is done in prerouting for in-interface bridge.
    # The exact single-test source & target & port match precedes DNSAUTO
    # and causes routing to use main ISP WAN, not r_to_vpn/SSTP.
    rule = ("/ip firewall mangle add chain=prerouting action=accept "
            f"src-address={host_ip}/32 dst-address={TARGET}/32 "
            "protocol=tcp dst-port=443 in-interface=bridge "
            f"comment={comment} place-before=[find where comment=DNSAUTO-TO-VPN]")
    ros(rule)
    if router_count("rule",comment)!=1:
        raise RuntimeError("router_rule_not_confirmed")
    detail = ros(f"/ip firewall mangle print detail where comment={comment}")
    if (f"src-address={host_ip}" not in detail or
        f"dst-address={TARGET}" not in detail or
        "action=accept" not in detail or "dst-port=443" not in detail):
        raise RuntimeError("router_rule_metadata_mismatch")
    print("ROUTER_TEST_DIRECT=ACTIVE single_source_single_destination_tcp443",flush=True)

def router_hits(comment):
    p = ros(f"/ip firewall mangle print stats where comment={comment}",check=False)
    # Print only the count if single exact rule; avoid RouterOS command output.
    m = re.search(r"(\d[\d ]*)\s+(\d[\d ]*)\s*$", p.strip())
    if m:
        return int(m.group(2).replace(" ",""))
    return "unparsed"

def router_cleanup(comment,schedule):
    # Never remove a scheduler while its matching traffic rule survives.
    try:
        ros(f"/ip firewall mangle remove [find where comment={comment}]")
        if router_count("rule",comment) != 0:
            print("ROUTER_ROLLBACK=GUARD_STILL_ARMED rule_remains",flush=True)
            return False
        ros(f"/system scheduler remove [find where name={schedule}]")
        print("ROUTER_ROLLBACK=CONFIRMED",flush=True)
        return True
    except Exception as exc:
        print("ROUTER_ROLLBACK=GUARD_PENDING error="+type(exc).__name__,flush=True)
        return False

def ns_nft(args,check=True):
    p=cmd(["ip","netns","exec",sandbox.NS,"nft",*args],timeout=6,check=False)
    if check and p.returncode:
        print("NAMESPACE_NFT_SYNTAX_ERROR=",p.stderr.strip()[:280],flush=True)
        raise RuntimeError("namespace_nft_failed")
    return p.stdout

def nft_create():
    cfg=sandbox.MARKER/"youtube-queue.nft"
    cfg.write_text("""table inet awg_dpi_youtube {
  chain probe_output {
    type filter hook output priority mangle; policy accept;
    ip daddr 142.251.157.4 tcp dport 443 meta mark & 0x40000000 == 0 counter queue num 239 bypass
  }
}
""")
    cfg.chmod(0o600)
    ns_nft(["-c","-f",str(cfg)])
    ns_nft(["-f",str(cfg)])

def nft_remove():
    if sandbox.ns_exists():
        ns_nft(["delete","table","inet","awg_dpi_youtube"],check=False)

def nfq_start(token,strategy):
    exec_root=sandbox.sandbox_exec_dir(token)
    exec_root.mkdir(mode=0o755)
    exec_root.chmod(0o755)
    executable=exec_root/"nfqws2"
    shutil.copyfile(BIN,executable)
    executable.chmod(0o755)
    if hashlib.sha256(executable.read_bytes()).hexdigest()!=EXPECTED_SHA:
        raise RuntimeError("copied_nfqws_checksum_mismatch")
    for original,name in [(LIB,"zapret-lib.lua"),(ANTIDPI,"zapret-antidpi.lua")]:
        dest=exec_root/name
        shutil.copyfile(original,dest)
        dest.chmod(0o644)
    argv=["ip","netns","exec",sandbox.NS,str(executable),
          "--qnum="+QUEUE,"--fwmark=0x40000000","--uid=1000",
          "--debug=1",
          "--lua-init=@"+str(exec_root/"zapret-lib.lua"),
          "--lua-init=@"+str(exec_root/"zapret-antidpi.lua"),
          "--filter-tcp="+PORT,"--ipset-ip="+TARGET,"--in-range=x",
          "--payload=tls_client_hello",
          "--lua-desync="+("fake:blob=fake_default_tls:badsum" if strategy=="fake_tls" else "multidisorder:pos=2")]
    logfile=sandbox.MARKER/"nfqws.log"
    with logfile.open("w") as f:
        proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,
                              stdout=f,stderr=subprocess.STDOUT)
    logfile.chmod(0o600)
    time.sleep(1)
    if proc.poll() is not None:
        # Print no raw log; error details must be inspected locally if needed.
        print("NFQWS_EARLY_EXIT=",proc.returncode,flush=True)
        raise RuntimeError("nfqws_early_exit")
    return proc,logfile

def nfq_counters(logfile,offset):
    with logfile.open("rb") as f:
        f.seek(offset)
        data=f.read(300_000).decode("utf-8",errors="replace")
    return {
        "multidisorder_invocations":data.count("multidisorder: split pos:"),
        "multidisorder_parts_attempted":data.count("multidisorder: sending part"),
        "tls_hello_mentions":data.count("tls_client_hello"),
        "fake_tls_debug_actions":data.count("fake: "),
    }

def nft_hits():
    text=ns_nft(["list","chain","inet","awg_dpi_youtube","probe_output"])
    found=re.search(r"\bpackets (\d+)\b",text)
    return int(found.group(1)) if found else -1

def probe(label):
    for site,path in SITES:
        output=cmd([
            "ip","netns","exec",sandbox.NS,"curl",
            "-4","--http1.1","--noproxy","*","--connect-timeout","3",
            "--max-time","9","--silent","--show-error","-o","/dev/null",
            "-w","status=%{http_code} bytes=%{size_download} duration=%{time_total}",
            "--resolve","www.youtube.com:443:"+TARGET,
            "https://www.youtube.com"+path
        ],timeout=12,check=False)
        print(label,site,"exit=",output.returncode,output.stdout.strip()[:130],flush=True)

def main():
    def on_sigterm(_sig, _frame):
        raise KeyboardInterrupt("operator_sigterm")
    signal.signal(signal.SIGTERM, on_sigterm)
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    if len(sys.argv)>2 or (len(sys.argv)==2 and sys.argv[1]!="--strategy=fake_tls"):
        raise RuntimeError("unsupported_arguments")
    strategy="fake_tls" if len(sys.argv)==2 else "multidisorder"
    print("YOUTUBE_TEST_STRATEGY=",strategy,flush=True)
    if sandbox.MARKER.exists() or sandbox.ns_exists() or sandbox.host_interface_exists():
        raise RuntimeError("old_test_residue_refuse")
    if not BIN.is_file() or hashlib.sha256(BIN.read_bytes()).hexdigest()!=EXPECTED_SHA:
        raise RuntimeError("upstream_binary_checksum_failed")
    if not LIB.is_file() or not ANTIDPI.is_file():
        raise RuntimeError("upstream_lua_missing")
    runid=secrets.token_hex(12)
    comment="AWG-DPI-YT-TEMP-"+runid
    schedule="AWG-DPI-YT-GUARD-"+runid
    unit=base.arm_timer(runid,145)
    os.environ["AWG_DPI_RUN_ID"]=runid
    print("PI_SANDBOX_WATCHDOG=ARMED",flush=True)
    nfq=None
    rule_attempted=False
    guard_attempted=False
    finished=False
    try:
        sandbox.create()
        ip=sandbox.dhcp()
        if sandbox.https_check()!="same_wan_public_ip":
            raise RuntimeError("independent_egress_control_failed")
        route=sandbox.call(["ip","-n",sandbox.NS,"route","get",TARGET]).stdout
        if "dev "+sandbox.IF not in route:
            raise RuntimeError("test_namespace_route_is_not_macvlan")
        print("ISOLATED_DHCP=PASS",flush=True)
        guard_attempted=True
        router_guard(comment,schedule)
        rule_attempted=True
        router_insert_rule(ip,comment,schedule)
        probe("A1_TRUE_ISP_DIRECT")
        nfq,log=nfq_start(runid,strategy)
        nft_create()
        print("ISOLATED_NFQUEUE=ACTIVE",flush=True)
        offset=log.stat().st_size
        probe("B1_YOUTUBE_"+strategy.upper())
        print("ISOLATED_NFQUEUE_HITS=",nft_hits(),flush=True)
        print("NFQWS_SAFE_COUNTS=",nfq_counters(log,offset),flush=True)
        nft_remove()
        base.terminate(nfq)
        nfq=None
        probe("A2_TRUE_ISP_DIRECT")
        print("YOUTUBE_ISP_DIRECT_AB_COMPLETED",flush=True)
        finished=True
    finally:
        nft_remove()
        base.terminate(nfq)
        if rule_attempted or guard_attempted:
            router_cleanup(comment,schedule)
        try:
            sandbox.cleanup()
            print("SANDBOX_CLEAN=",not sandbox.ns_exists() and not sandbox.host_interface_exists(),flush=True)
        finally:
            base.unit_stop_timer(unit)

if __name__=="__main__":
    try:
        main()
    except (Exception,KeyboardInterrupt) as exc:
        print("YOUTUBE_AB_ABORT=",type(exc).__name__,str(exc).split(":")[0],file=sys.stderr)
        sys.exit(2)
