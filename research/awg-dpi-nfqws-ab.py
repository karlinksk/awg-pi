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
        # The nft command contains only static rule names, queue, IP and port.
        # Keep limited stderr so one failed attempt is actionable.
        print("ISOLATED_NFT_ERROR=", p.stderr.strip().replace("\\n", " ")[:320],
              "exit=", p.returncode, flush=True)
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
    # /run is mounted noexec by Debian; /dev/shm is a separate tmpfs
    # which permits executing this already verified official ARM64 binary.
    run_id = (sandbox.MARKER / "run-id").read_text().strip()
    execution_root = sandbox.sandbox_exec_dir(run_id)
    execution_root.mkdir(mode=0o755)
    execution_root.chmod(0o755)
    copy = execution_root / "nfqws2"
    shutil.copyfile(BIN, copy)
    copy.chmod(0o755)
    if hashlib.sha256(copy.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("copied_official_binary_sha_mismatch")
    # Root-owned snapshot of the two scripts; readable by the dropped UID.
    local_lib = execution_root / "zapret-lib.lua"
    local_antidpi = execution_root / "zapret-antidpi.lua"
    for original, destination in ((LIB, local_lib), (ANTIDPI, local_antidpi)):
        shutil.copyfile(original, destination)
        destination.chmod(0o644)
    cmd = [
        "ip", "netns", "exec", sandbox.NS, str(copy),
        "--qnum=" + QUEUE,
        "--fwmark=" + FWMARK, "--uid=1000",
        "--lua-init=@" + str(local_lib),
        "--lua-init=@" + str(local_antidpi),
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
    exit_code = proc.poll()
    if exit_code is not None:
        print("NFQWS_EXIT_CODE=", exit_code, flush=True)
        try:
            # The log is stored only in the ephemeral, root-owned sandbox.
            # Print bounded *startup diagnostics* BEFORE sandbox cleanup
            # deletes it; redact potentially sensitive parameter values.
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            if not lines:
                print("NFQWS_STARTUP_LOG=EMPTY", flush=True)
            for line in lines[-18:]:
                line = re.sub(r"(?i)\b(uuid|token|password|secret|private.?key|public.?key|sni|servername)\s*[:=]\s*\S+", r"\1=<redacted>", line)
                line = re.sub(r"(?i)\b(?:[a-f0-9]{48,}|[a-z0-9+/]{64,}={0,2})\b", "<redacted>", line)
                print("NFQWS_STARTUP_LOG=", line[:240], flush=True)
        except OSError:
            print("NFQWS_STARTUP_LOG=UNREADABLE", flush=True)
        raise RuntimeError("nfqws_early_exit")
    # A successful startup does not expose the log or packet contents.
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
    # Fail rather than attempting execution on a noexec filesystem.
    flags = subprocess.run(["findmnt", "-T", "/dev/shm", "-n", "-o", "OPTIONS"],
                           capture_output=True, text=True, timeout=4)
    if flags.returncode or "noexec" in flags.stdout.split(","):
        raise RuntimeError("execution_tmpfs_unavailable_or_noexec")
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
