#!/usr/bin/env python3
"""A/B experiment of one pinned zapret2 strategy for one VLESS endpoint.

- Production routes/nft/transport never touched; all netfilter rules exist
  exclusively inside awg-dpi-test namespace.
- Independent systemd watchdog is armed BEFORE namespace creation.
- No system-wide zapret2 installation; official checksummed ARM64 binary
  copied to root-owned /run/awg-dpi-test-owner per experiment.
- One site at 10s + independent second site. A -> B -> A sequence.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import secrets
import signal

ROOT = Path("/home/karlinks")
RELEASE = Path("/run/user/1000/awg-zapret2-official-v1.0.5.2/zapret2-v1.0.5.2")
BIN = RELEASE / "binaries/linux-arm64/nfqws2"
LIB = RELEASE / "lua/zapret-lib.lua"
ANTIDPI = RELEASE / "lua/zapret-antidpi.lua"
EXPECTED_SHA256 = "8788877cd4b3140357dd10524832ca508d47055efae072bc426b887bfea253a7"
QUEUE = "237"
FWMARK = "0x40000000"
TARGET = "159.89.87.21"
PORT = "28190"

def import_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

base = import_module("awg_guarded_baseline", ROOT / "awg-dpi-vless-baseline.py")
sandbox = base.sandbox

def nft(args, check=True):
    p = subprocess.run(["ip", "netns", "exec", sandbox.NS, "nft", *args],
                       capture_output=True, text=True, timeout=6)
    if check and p.returncode:
        raise RuntimeError("isolated_nft_command_failed")
    return p

def isolate_nft_rule():
    config = sandbox.MARKER / "nfqueue.nft"
    config.write_text("""table inet awg_dpi_probe {
  chain test_output {
    type filter hook output priority mangle; policy accept;
    ip daddr 159.89.87.21 tcp dport 28190 meta mark & 0x40000000 == 0 counter queue num 237 bypass
  }
}
""")
    config.chmod(0o600)
    # Dry-run parser in target namespace, then apply there only.
    a = nft(["-c", "-f", str(config)])
    b = nft(["-f", str(config)])
    return True

def remove_nft_rules():
    # Exactly one test-named table in the temporary netns. Never host nft.
    nft(["delete", "table", "inet", "awg_dpi_probe"], check=False)

def observed_queue_packets():
    p = nft(["list", "chain", "inet", "awg_dpi_probe", "test_output"], check=False)
    hits = re.search(r"\bpackets (\d+)\b", p.stdout)
    return int(hits.group(1)) if hits else None

def launch_nfqws():
    import hashlib
    got = hashlib.sha256(BIN.read_bytes()).hexdigest()
    if got != EXPECTED_SHA256:
        raise RuntimeError("nfqws_official_sha_mismatch")
    copy = sandbox.MARKER / "nfqws2"
    shutil.copyfile(BIN, copy)
    copy.chmod(0o700)
    cmd = [
        "ip", "netns", "exec", sandbox.NS, str(copy),
        "--qnum=" + QUEUE,
        "--fwmark=" + FWMARK, "--uid=1000",
        "--lua-init=@" + str(LIB),
        "--lua-init=@" + str(ANTIDPI),
        "--filter-tcp=" + PORT,
        "--ipset-ip=" + TARGET,
        "--in-range=x",
        "--payload=tls_client_hello",
        "--lua-desync=fake:blob=fake_default_tls:badsum",
    ]
    log = sandbox.MARKER / "nfqws.log"
    fd = log.open("w")
    log.chmod(0o600)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=fd, stderr=subprocess.STDOUT)
    finally:
        fd.close()
    time.sleep(1.1)
    if proc.poll() is not None:
        raise RuntimeError("nfqws_early_exit")
    # Do not print this log; it may include endpoint or TLS details.
    return proc

def result_snapshot(label, proxy):
    statuses = []
    for i, u in enumerate(base.URLS, 1):
        import urllib.parse
        query = urllib.parse.urlencode({"url": u, "timeout": 10000})
        statuses.append(base.netns_request("/proxies/AWG-DPI-NATIVE-VLESS/delay?" + query))
    print(label, "target1=", statuses[0], "target2=", statuses[1], flush=True)
    return statuses

def offline_preflight():
    """Read-only preparation check; never creates a namespace or nft rule."""
    import hashlib
    if sandbox.MARKER.exists() or sandbox.ns_exists() or sandbox.host_interface_exists():
        raise RuntimeError("sandbox_residue_abort")
    if not BIN.is_file() or hashlib.sha256(BIN.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("official_arm64_binary_missing_or_sha_mismatch")
    if not LIB.is_file() or not ANTIDPI.is_file():
        raise RuntimeError("official_lua_files_missing")
    if not (ROOT / "awg-dpi-guardian.py").is_file():
        raise RuntimeError("guardian_script_missing")
    if subprocess.run(["systemctl", "is-active", "--quiet", "awg-mihomo.service"]).returncode:
        raise RuntimeError("production_mihomo_not_active")
    print("PRECHECK=PASS", "official_binary_sha256=PASS",
          "test_namespace_absent=YES", "live_mihomo_active=YES", flush=True)

def main():
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt("operator_interrupted_test")
    signal.signal(signal.SIGTERM, interrupted)
    if os.geteuid():
        raise RuntimeError("root_required")
    if len(sys.argv) == 2 and sys.argv[1] == "--preflight":
        offline_preflight()
        return
    if len(sys.argv) != 1:
        raise RuntimeError("use_no_args_to_test_or_preflight_flag")
    offline_preflight()
    if sandbox.MARKER.exists() or sandbox.ns_exists() or sandbox.host_interface_exists():
        raise RuntimeError("existing_namespace_or_interface_abort")
    profile = base.picked_profile()
    run_id = secrets.token_hex(12)
    unit = base.arm_timer(run_id, 130)
    os.environ["AWG_DPI_RUN_ID"] = run_id
    print("NFQWS_AB_TIMER=ARMED", flush=True)
    proc = None
    nfq = None
    try:
        sandbox.create()
        sandbox.dhcp()
        if sandbox.https_check() != "same_wan_public_ip":
            raise RuntimeError("isolated_path_not_confirmed_direct")
        route = sandbox.call(["ip", "-n", sandbox.NS, "-4", "route", "get", TARGET]).stdout
        if "dev "+sandbox.IF not in route:
            raise RuntimeError("wrong_namespace_endpoint_route")
        proc = base.spawn_mihomo(profile)
        print("NAMESPACE_VLESS_READY", flush=True)
        result_snapshot("A1_NO_ZAPRET2", proc)
        nfq = launch_nfqws()
        isolate_nft_rule()
        print("NAMESPACE_NFQUEUE_ACTIVE", flush=True)
        result_snapshot("B1_WITH_FAKE_TLS", proc)
        print("NAMESPACE_NFQUEUE_PACKET_HITS=", observed_queue_packets(), flush=True)
        remove_nft_rules()
        base.terminate(nfq)
        nfq = None
        result_snapshot("A2_NO_ZAPRET2", proc)
        print("NFQWS_AB_COMPLETED", flush=True)
    finally:
        remove_nft_rules() if sandbox.ns_exists() else None
        base.terminate(nfq)
        base.terminate(proc)
        sandbox.cleanup()
        base.unit_stop_timer(unit)
        print("SANDBOX_CLEAN=", not sandbox.ns_exists() and not sandbox.host_interface_exists(), flush=True)

if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as e:
        print("NFQWS_AB_ABORT=", type(e).__name__, str(e).split(":")[0], file=sys.stderr)
        raise SystemExit(2)
