#!/usr/bin/env python3
"""Isolated DIRECT YouTube HTTPS reachability baseline (NO zapret2).

Only creates awg-dpi-test namespace with independent randomized MAC/DHCP;
no new host nftables rules or changes to main routing, MikroTik, AWG, SSTP,
production Mihomo. An independent systemd recovery timer is started first.
"""
import ipaddress
import os
import secrets
import socket
import subprocess
import sys
import urllib.parse
from pathlib import Path

HOME = Path("/home/karlinks")
sys.path.insert(0, str(HOME))
import importlib.util

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

base = load("awg_dpi_baseline", HOME / "awg-dpi-vless-baseline.py")
sandbox = base.sandbox

SITES = (
    ("YOUTUBE_204", "www.youtube.com", "/generate_204"),
    ("YOUTUBE_HOME", "www.youtube.com", "/"),
    ("YTIMG_THUMB", "i.ytimg.com", "/vi/dQw4w9WgXcQ/hqdefault.jpg"),
)

def resolve(host):
    addresses = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    for entry in addresses:
        addr = entry[4][0]
        if ipaddress.ip_address(addr).is_global:
            return addr
    raise RuntimeError("no_public_ipv4_for_"+host)

def probe(label, host, path, addr):
    route = subprocess.run(["ip", "-n", sandbox.NS, "route", "get", addr],
                           capture_output=True, text=True, timeout=4)
    if route.returncode != 0 or f"dev {sandbox.IF}" not in route.stdout:
        raise RuntimeError("namespace_not_using_direct_router")
    p = subprocess.run(
        ["ip","netns","exec",sandbox.NS,"curl",
         "-4","--http1.1","--noproxy","*",
         "--connect-timeout","4","--max-time","12",
         "-sS","-o","/dev/null",
         "-w","code=%{http_code} bytes=%{size_download} speed=%{speed_download} total=%{time_total}",
         "--resolve",host+":443:"+addr, "https://"+host+path],
        text=True,capture_output=True,timeout=15
    )
    print("DIRECT_YOUTUBE",label,"exit=",p.returncode,p.stdout.strip()[:170],flush=True)

def main():
    if os.geteuid():
        raise RuntimeError("root_required")
    if sandbox.MARKER.exists() or sandbox.ns_exists() or sandbox.host_interface_exists():
        raise RuntimeError("sandbox_residue_present")
    sites = [(label,host,path,resolve(host)) for label,host,path in SITES]
    token = secrets.token_hex(12)
    unit = base.arm_timer(token, 100)
    os.environ["AWG_DPI_RUN_ID"] = token
    try:
        sandbox.create()
        lease = sandbox.dhcp()
        print("ISOLATED_DHCP=PASS",flush=True)
        control = sandbox.https_check()
        print("ISOLATED_GENERIC_IPV4=",control,flush=True)
        if control != "same_wan_public_ip":
            raise RuntimeError("independent_path_control_failed")
        print("CAUTION=namespace_uses_MikroTik_next_hop;_MikroTik_upstream_policy_unverified",flush=True)
        for site in sites:
            probe(*site)
    finally:
        sandbox.cleanup()
        base.unit_stop_timer(unit)
        print("TEST_RESOURCES_REMOVED=",not sandbox.ns_exists() and not sandbox.host_interface_exists(),flush=True)

if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as e:
        print("YOUTUBE_CONTROL_ABORT=",type(e).__name__,str(e).split(":")[0],file=sys.stderr)
        raise SystemExit(2)
