#!/usr/bin/python3 -I
"""Allowlisted, read-only root diagnostics for explicitly authorised Desktop Commander."""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

CACHE = Path("/var/lib/awg-pbr/stage18-runtime")
PINNED = {
    "node": ("fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5", "v22.16.0"),
    "yt-dlp": ("1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6", "2026.08.19"),
}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
UNITS = (
    "ssh.service", "dnsmasq.service", "awg-pbr-setup.service",
    "awg-pbr-health.service", "awg-selection-monitor.service",
    "awg-mihomo.service", "awg-quick@awg0.service",
    "awg-xray-vless.service", "awg-mihomo-hot-pool.timer",
    "awg-mihomo-stage18-ram-runtime.path",
    "awg-mihomo-stage18-ram-runtime.timer",
)

def command(argv, timeout=8):
    """Fixed argv, clean environment, no shell, bounded and sanitized output."""
    try:
        r = subprocess.run(argv, env=ENV, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, timeout=timeout)
        if r.returncode:
            return "unavailable"
        line = (r.stdout.splitlines() or ["unavailable"])[0]
        return re.sub(r"[^A-Za-z0-9 _./:+@()=-]", "?", line[:160])
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"

def stage18():
    try:
        d = CACHE.lstat()
        if not stat.S_ISDIR(d.st_mode) or d.st_uid != 0 or d.st_mode & 0o077:
            raise ValueError("unsafe cache")
        for name, (expected_hash, expected_version) in PINNED.items():
            path = CACHE / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("unsafe binary")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError("hash mismatch")
            if command([str(path), "--version"]) != expected_version:
                raise ValueError("version mismatch")
            print("AWG_DC_ADMIN_" + name.upper().replace("-", "_") + "=VERIFIED")
        print("AWG_DC_ADMIN_STAGE18=PASS")
        return 0
    except (OSError, ValueError):
        print("AWG_DC_ADMIN_STAGE18=FAIL")
        return 1

def services():
    for unit in UNITS:
        a = command(["/usr/bin/systemctl", "is-active", unit])
        e = command(["/usr/bin/systemctl", "is-enabled", unit])
        print(f"AWG_DC_ADMIN_UNIT={unit} active={a} enabled={e}")
    return 0

def network():
    for name, argv in (
        ("RULES", ["/usr/sbin/ip", "-4", "rule", "show"]),
        ("DEFAULT", ["/usr/sbin/ip", "-4", "route", "show", "default"]),
        ("TABLE100", ["/usr/sbin/ip", "-4", "route", "show", "table", "100"]),
        ("TABLE101", ["/usr/sbin/ip", "-4", "route", "show", "table", "101"]),
    ):
        print("AWG_DC_ADMIN_" + name + "=" + command(argv))
    return 0

def versions():
    for name, argv in (
        ("AWG", ["/usr/bin/awg", "--version"]),
        ("MIHOMO", ["/usr/local/bin/mihomo", "-v"]),
        ("XRAY", ["/usr/local/bin/awg-xray-vless-core", "version"]),
        ("FFMPEG", ["/usr/bin/ffmpeg", "-version"]),
        ("NODE", ["/usr/local/bin/node", "--version"]),
    ):
        print("AWG_DC_ADMIN_" + name + "=" + command(argv))
    return 0

def status():
    print("AWG_DC_ADMIN_SCOPE=READ_ONLY")
    try:
        version = Path("/usr/share/awg-pbr/version").read_text().strip()
    except OSError:
        version = ""
    print("AWG_DC_ADMIN_GATEWAY_VERSION=" +
          (version if re.fullmatch(r"[0-9.]+", version) else "unavailable"))
    for path, name in (
        ("/etc/amnezia/amneziawg/awg0.conf", "AWG_PROFILE"),
        ("/var/lib/awg-pbr/mihomo/providers/subscription.yaml", "MIHOMO_PROVIDER"),
    ):
        print("AWG_DC_ADMIN_" + name + "=" +
              ("PRESENT" if Path(path).is_file() else "ABSENT"))
    return 0

HANDLERS = {"status": status, "stage18": stage18, "services": services,
            "network": network, "versions": versions}

def main(args=None):
    args = sys.argv[1:] if args is None else args
    if os.geteuid() != 0:
        print("AWG_DC_ADMIN_ERROR=ROOT_REQUIRED", file=sys.stderr)
        return 2
    if len(args) != 1 or args[0] not in HANDLERS:
        print("AWG_DC_ADMIN_ERROR=UNKNOWN_ACTION", file=sys.stderr)
        return 2
    return HANDLERS[args[0]]()

if __name__ == "__main__":
    sys.exit(main())
