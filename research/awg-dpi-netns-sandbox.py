#!/usr/bin/env python3
"""AWG Pi isolated network-namespace lifecycle research; does NOT install zapret2.

Creates a dedicated network namespace and temporary macvlan interface on eth0,
without editing production routes, nftables, rules or transport configuration.
Lifecycle modes:
  status         read-only check
  lifecycle      exercise creation and normal automatic rollback; no networking
  rollback       inject an exception after creation; verify automatic rollback
  dhcp-smoke     request separate DHCP lease via a custom no-hook udhcpc script,
                 test isolated IPv4 HTTPS, and clean up
  cleanup        remove ONLY resources bearing this tool's /run ownership marker
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

NS = "awg-dpi-test"
IF = "awdpi0"
PARENT = "eth0"
LAN = ipaddress.IPv4Network("192.168.112.0/24")
GATEWAY = ipaddress.IPv4Address("192.168.112.1")
MARKER = Path("/run/awg-dpi-test-owner")
LEASE = MARKER / "lease"
SCRIPT = MARKER / "dhcp-hook.sh"
CONTROL_URL = "https://api.ipify.org"


def call(args, *, required=True, timeout=12):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if required and p.returncode != 0:
        raise RuntimeError("command_failed:" + " ".join(args[:3]))
    return p


def owned():
    return MARKER.is_dir() and (MARKER / "owner").is_file() and (
        (MARKER / "owner").read_text() == f"{NS}\n{IF}\n{PARENT}\n"
    )


def ns_exists():
    p = call(["ip", "netns", "list"], required=False)
    return any(line.split()[0] == NS for line in p.stdout.splitlines() if line.strip())


def host_interface_exists():
    return call(["ip", "link", "show", "dev", IF], required=False).returncode == 0


def cleanup():
    if not owned():
        if ns_exists() or host_interface_exists():
            raise RuntimeError("unsafe_leftover_without_ownership_marker")
        return
    # If child process still has the ns open, stop it only if it is a DHCP
    # process launched by the audit. Our -q udhcpc exits on lease acquisition.
    if ns_exists():
        pids = call(["ip", "netns", "pids", NS], required=False)
        if pids.stdout.strip():
            raise RuntimeError("namespace_still_has_processes_no_force_kill")
        call(["ip", "-n", NS, "link", "del", IF], required=False)
        call(["ip", "netns", "del", NS])
    if host_interface_exists():
        details = call(["ip", "-d", "link", "show", "dev", IF])
        if "macvlan" not in details.stdout:
            raise RuntimeError("unrecognized_host_interface")
        call(["ip", "link", "del", "dev", IF])
    shutil.rmtree(MARKER)


def create():
    if os.geteuid() != 0:
        raise RuntimeError("root_required")
    if MARKER.exists() or ns_exists() or host_interface_exists():
        raise RuntimeError("existing_sandbox_or_marker_abort_no_overwrite")
    MARKER.mkdir(mode=0o700)
    (MARKER / "owner").write_text(f"{NS}\n{IF}\n{PARENT}\n")
    (MARKER / "owner").chmod(0o600)
    session = os.environ.get("AWG_DPI_RUN_ID", "")
    if session:
        if len(session) != 24 or not all(x in "0123456789abcdef" for x in session):
            raise RuntimeError("invalid_watchdog_session_token")
        (MARKER / "run-id").write_text(session + "\n")
        (MARKER / "run-id").chmod(0o600)
    call(["ip", "netns", "add", NS])
    # A separate L2 MAC means no host NAT/nft or veth host routing needed.
    call(["ip", "link", "add", "link", PARENT, "name", IF,
          "type", "macvlan", "mode", "bridge"])
    call(["ip", "link", "set", "dev", IF, "netns", NS])
    mac = bytearray(os.urandom(6))
    mac[0] = (mac[0] | 2) & 0xFE  # locally administered, unicast
    call(["ip", "-n", NS, "link", "set", "dev", IF,
          "address", ":".join(f"{b:02x}" for b in mac)])
    call(["ip", "-n", NS, "link", "set", "dev", "lo", "up"])
    call(["ip", "-n", NS, "link", "set", "dev", IF, "up"])
    # Netfilter tables are independent per netns; never touch host nft.
    scoped_tables = call(["ip", "netns", "exec", NS, "nft", "list", "tables"])
    if scoped_tables.stdout.strip():
        raise RuntimeError("sandbox_nft_tables_not_empty")
    scoped_routes = call(["ip", "-n", NS, "-4", "route", "show"])
    if scoped_routes.stdout.strip():
        raise RuntimeError("sandbox_has_unexpected_ipv4_route")
    print("SANDBOX_ISOLATION=PASS empty_netns_nft_and_routes=true", flush=True)


def dhcp():
    # BusyBox udhcpc works on this Pi and receives a distinct DHCP lease.
    # Its custom event hook is not invoked in this environment; use a
    # no-op hook, parse the standard lease confirmation, and configure
    # the address only inside the temporary namespace.
    result = call(
        ["ip", "netns", "exec", NS, "busybox", "udhcpc",
         "-i", IF, "-f", "-n", "-q", "-t", "4", "-T", "2",
         "-s", "/bin/true"],
        required=False, timeout=20
    )
    if result.returncode != 0:
        raise RuntimeError("dhcp_no_lease")
    import re
    match = re.search(
        r"lease of (\d{1,3}(?:\.\d{1,3}){3}) obtained from "
        r"(\d{1,3}(?:\.\d{1,3}){3})",
        result.stdout + "\n" + result.stderr
    )
    if match is None:
        raise RuntimeError("dhcp_lease_confirmation_missing")
    ip = ipaddress.IPv4Address(match.group(1))
    dhcp_server = ipaddress.IPv4Address(match.group(2))
    if ip not in LAN or ip == ipaddress.IPv4Address("192.168.112.34"):
        raise RuntimeError("wrong_lease_subnet_or_production_ip")
    if dhcp_server != GATEWAY:
        raise RuntimeError("unexpected_dhcp_server")
    # The LAN is independently verified /24 on Pi and MikroTik.
    call(["ip", "-n", NS, "addr", "add", f"{ip}/24", "dev", IF])
    call(["ip", "-n", NS, "route", "add", "default", "via", str(GATEWAY), "dev", IF])
    return str(ip)

def https_check():
    # DNS lookups occur in the parent host, *not* via a new DNS config.
    addresses = socket.getaddrinfo("api.ipify.org", 443, socket.AF_INET, socket.SOCK_STREAM)
    destination = next(
        (addr[4][0] for addr in addresses
         if ipaddress.IPv4Address(addr[4][0]).is_global), None
    )
    if not destination:
        raise RuntimeError("control_hostname_unresolved")
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl_missing")
    cmd = [curl, "--ipv4", "--fail", "--silent", "--show-error",
           "--noproxy", "*", "--connect-timeout", "4", "--max-time", "12",
           "--resolve", f"api.ipify.org:443:{destination}", CONTROL_URL]
    isolated = call(["ip", "netns", "exec", NS, *cmd], required=False, timeout=15)
    host = call(cmd, required=False, timeout=15)
    try:
        isolated_ip = ipaddress.IPv4Address(isolated.stdout.strip())
        host_ip = ipaddress.IPv4Address(host.stdout.strip())
    except ValueError:
        return "connectivity_or_response_failed"
    if isolated.returncode or host.returncode or not isolated_ip.is_global or not host_ip.is_global:
        return "connectivity_or_response_failed"
    return "same_wan_public_ip" if isolated_ip == host_ip else "different_public_ip_check_router_policy"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["status", "lifecycle", "hold", "rollback", "dhcp-smoke", "cleanup"])
    args = p.parse_args()
    if args.mode == "status":
        print("AWG_DPI_SANDBOX_STATUS", "owned=", owned(),
              "namespace=", ns_exists(), "host_iface=", host_interface_exists())
        return 0
    if os.geteuid() != 0:
        raise RuntimeError("requires_root")
    if args.mode == "cleanup":
        cleanup()
        print("CLEANUP_DONE", "namespace=", ns_exists(), "host_iface=", host_interface_exists())
        return 0
    cleanup_state = "not_attempted"
    def sigterm(_sig, _frame):
        raise KeyboardInterrupt("received_SIGTERM")
    signal.signal(signal.SIGTERM, sigterm)
    try:
        create()
        print("SANDBOX_CREATED namespace=", NS, "interface=", IF, flush=True)
        if args.mode == "rollback":
            raise RuntimeError("intentional_failure_to_test_rollback")
        if args.mode == "hold":
            print("SANDBOX_HOLD_FOR_SIGNAL_TEST", flush=True)
            time.sleep(10)
        if args.mode == "dhcp-smoke":
            addr = dhcp()
            print("SANDBOX_DHCP_LEASE_RECEIVED", "lease_is_distinct_from_production=true",
                  "ns_default_gateway=", str(GATEWAY), flush=True)
            result = https_check()
            print("SANDBOX_HTTPS_RESULT=", result, flush=True)
        else:
            print("SANDBOX_LINK_ONLY_READY no_network_calls=true", flush=True)
    finally:
        cleanup()
        print("SANDBOX_CLEANUP=OK", "ns_exists=", ns_exists(),
              "host_interface_exists=", host_interface_exists(), flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        # Keep internal command-line output out of stdout; credentials are never
        # part of command-line arguments or logs in this experiment.
        print("SANDBOX_EXIT_ERROR=", str(exc).split(":")[0], file=sys.stderr)
        raise SystemExit(2)
