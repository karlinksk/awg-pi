#!/usr/bin/env python3
"""Reproduce one native VLESS+REALITY+Vision failure in isolated DIRECT namespace.

No zapret2 in this file. No changes to host routing, nftables or VPN services.
A separate token-scoped systemd one-shot timer performs cleanup after crashes.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import urllib.parse
import yaml

HOME = Path("/home/karlinks")
TARGET = "159.89.87.21"
PORT = 28190
CTRL = 19093
URLS = ["https://www.gstatic.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace"]

def import_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

sandbox = import_module("awg_research_sandbox", HOME / "awg-dpi-netns-sandbox.py")
pool = import_module("awg_research_pool", HOME / "mihomo-endpoint-reprobe.py")

def picked_profile():
    source, state, _ = pool.load_matching()
    matches = [item for item in pool.choose(source, state)
               if item["kind"] == "vless" and item["baseline"] == "failed"
               and item["host"] == TARGET and item["port"] == PORT]
    if len(matches) != 1:
        raise RuntimeError("target_not_found_or_duplicate")
    item = matches[0]
    raw = item["raw"]
    if (raw.get("tls") is not True or raw.get("flow") != "xtls-rprx-vision" or
        not raw.get("reality-opts") or raw.get("dialer-proxy")):
        raise RuntimeError("profile_not_expected_unmodified_REA​LITY")
    return dict(raw)

def arm_timer(run_id, delay_sec):
    ident = "awg-dpi-guard-" + run_id[:8]
    command = ["systemd-run", "--unit", ident, f"--on-active={delay_sec}s",
               "--collect", "/usr/bin/python3",
               str(HOME / "awg-dpi-guardian.py"), run_id]
    subprocess.run(command, capture_output=True, text=True, check=True, timeout=8)
    return ident

def unit_stop_timer(name):
    subprocess.run(["systemctl", "stop", name + ".timer"],
                   capture_output=True, timeout=4)

def netns_request(path):
    # Only this separate namespace can access its localhost controller.
    cmd = ["ip", "netns", "exec", sandbox.NS, "curl", "--noproxy", "*",
           "--silent", "--show-error", "--connect-timeout", "2",
           "--max-time", "14", "-o", "/dev/null", "-w", "%{http_code}",
           f"http://127.0.0.1:{CTRL}{path}"]
    response = subprocess.run(cmd, capture_output=True, text=True, timeout=17)
    if response.returncode != 0:
        return "no_controller_response"
    code = response.stdout.strip()
    if code == "200":
        return "ok"
    if code.isdigit():
        return "api_" + code
    return "unrecognized_response"

def spawn_mihomo(profile):
    profile["name"] = "AWG-DPI-NATIVE-VLESS"
    config = {
        "mixed-port": 0, "allow-lan": False, "ipv6": False, "mode": "rule",
        "log-level": "silent", "external-controller": f"127.0.0.1:{CTRL}",
        "profile": {"store-selected": False, "store-fake-ip": False},
        "proxies": [profile],
        "proxy-groups": [{"name": "AWG-DPI-GROUP", "type": "select",
                          "proxies": ["AWG-DPI-NATIVE-VLESS"]}],
        "rules": ["MATCH,AWG-DPI-GROUP"]
    }
    path = sandbox.MARKER / "mihomo-config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    path.chmod(0o600)
    proc = subprocess.Popen(
        ["ip", "netns", "exec", sandbox.NS, "/usr/local/bin/mihomo",
         "-d", str(sandbox.MARKER), "-f", str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("test_mihomo_early_exit")
        status = netns_request("/proxies/AWG-DPI-NATIVE-VLESS")
        if status == "ok":
            return proc
        time.sleep(.2)
    raise RuntimeError("test_mihomo_controller_not_ready")

def terminate(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try: proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)

def main():
    if os.geteuid() != 0:
        raise RuntimeError("root_required")
    if len(sys.argv) != 2 or sys.argv[1] not in ("killtest", "baseline"):
        raise RuntimeError("mode_must_be_killtest_or_baseline")
    mode = sys.argv[1]
    if sandbox.ns_exists() or sandbox.MARKER.exists():
        raise RuntimeError("sandbox_already_exists")
    proc = None
    profile = picked_profile() if mode == "baseline" else None
    run_id = secrets.token_hex(12)
    armed = arm_timer(run_id, 8 if mode == "killtest" else 105)
    # Set session marker at sandbox creation, eliminating stale timer races.
    os.environ["AWG_DPI_RUN_ID"] = run_id
    print("GUARDIAN_TIMER=ARMED", "mode="+mode, flush=True)
    try:
        sandbox.create()
        if mode == "killtest":
            print("SIMULATE_UNCATCHABLE_SIGKILL", flush=True)
            os.kill(os.getpid(), signal.SIGKILL)
        sandbox.dhcp()
        print("ISOLATED_DHCP=PASS", flush=True)
        control = sandbox.https_check()
        print("ISOLATED_EGRESS=", control, flush=True)
        if control != "same_wan_public_ip":
            raise RuntimeError("sandbox_not_same_wan_as_direct")
        if sandbox.call(["ip", "-n", sandbox.NS, "-4", "route", "get", TARGET]).stdout.find("dev "+sandbox.IF) == -1:
            raise RuntimeError("target_not_routed_on_test_interface")
        proc = spawn_mihomo(profile)
        print("NATIVE_VLESS_IN_NETNS=STARTED", flush=True)
        for n, site in enumerate(URLS):
            query = urllib.parse.urlencode({"url": site, "timeout": 10000})
            result = netns_request("/proxies/AWG-DPI-NATIVE-VLESS/delay?" + query)
            print("HTTPS_TARGET", n+1, "native_proxy_result=", result, flush=True)
        print("BASELINE_FINISHED", flush=True)
    finally:
        terminate(proc)
        sandbox.cleanup()
        print("SANDBOX_CLEANUP=", (not sandbox.ns_exists() and not sandbox.host_interface_exists()), flush=True)
        unit_stop_timer(armed)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("DIAGNOSTIC_ABORT=", type(e).__name__, str(e).split(":")[0], file=sys.stderr)
        raise SystemExit(2)
