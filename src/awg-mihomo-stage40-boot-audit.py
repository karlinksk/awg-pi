#!/usr/bin/env python3
"""Stage40 boot readiness AUDIT (read only).

No root elevation, service modification, network changes, secret file reads,
MikroTik or NAS communication. Exit 2 if boot rollback is NOT production ready.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

RECOVERY = "awg-native-fallback-recovery.service"
PERSISTENT = Path("/var/lib/awg-pbr/native-fallback-recovery")
PROTECTED = (
    "awg-pbr-setup.service",
    "awg-mihomo.service",
    "awg-selection-monitor.service",
    "awg-pbr-health.service",
    "awg-quick@awg0.service",
)
# Each protected unit must positively start and order after the recovery unit;
# Before= in recovery unit alone does not cause it to run.
DEPENDENCY_FIELDS = ("Requires", "After")

def run(*argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=6, check=False)
    return result.returncode, result.stdout.strip()

def audit(command=run, is_dir=None):
    # Explicit injectable read-only probes for unit testing.
    if is_dir is None:
        is_dir = lambda p: p.is_dir() and not p.is_symlink()
    blockers = []
    units = {}
    rc, root_fs = command("findmnt", "-n", "-o", "FSTYPE", "-T", str(PERSISTENT.parent))
    if rc != 0 or root_fs not in ("ext4", "btrfs", "xfs", "f2fs"):
        blockers.append("NO_LOCAL_PERSISTENT_FILESYSTEM")
    if not is_dir(PERSISTENT):
        blockers.append("NO_DURABLE_ROOT_RECOVERY")
    rc, recovery_path = command("systemctl", "show", RECOVERY, "-p", "FragmentPath", "--value")
    if rc != 0 or not recovery_path or recovery_path == "/dev/null":
        blockers.append("RECOVERY_UNIT_NOT_INSTALLED")
    elif not recovery_path.startswith("/etc/systemd/system/"):
        blockers.append("RECOVERY_UNIT_NOT_LOCAL_ADMIN_OWNED")
    for service in PROTECTED:
        rc, fragment = command("systemctl", "show", service, "-p", "FragmentPath", "--value")
        if rc != 0 or not fragment or fragment == "/dev/null":
            blockers.append("MISSING_PROTECTED_UNIT:" + service)
            continue
        fields = {}
        for field in DEPENDENCY_FIELDS:
            ret, raw = command("systemctl", "show", service, "-p", field, "--value")
            fields[field] = raw.split() if ret == 0 else []
            if RECOVERY not in fields[field]:
                blockers.append("UNORDERED:" + service + ":" + field)
        units[service] = {"recovery_requires": RECOVERY in fields["Requires"],
                          "recovery_after": RECOVERY in fields["After"]}
    # Additional guard: successful dependency ordering is insufficient if
    # the sample nonworking ExecStart=/usr/bin/false is mistakenly installed.
    if "RECOVERY_UNIT_NOT_INSTALLED" not in blockers:
        rc, start = command("systemctl", "show", RECOVERY, "-p", "ExecStart", "--value")
        if rc or not start or "/usr/bin/false" in start:
            blockers.append("RECOVERY_EXECUTOR_UNVERIFIED")
    return {"ready": len(blockers) == 0, "blockers": blockers, "protected_units": units,
            "notes": "Read-only metadata audit; no live rollback or SSTP/NAS verification."}

def main():
    ap = argparse.ArgumentParser(description="Pi-only read-only boot recovery readiness audit")
    ap.add_argument("--json", action="store_true")
    options = ap.parse_args()
    try:
        result = audit()
        if options.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print("STAGE40_BOOT_READY=" + ("YES" if result["ready"] else "NO"))
            for name in result["blockers"]:
                print("STAGE40_BLOCKER=" + name)
        return 0 if result["ready"] else 2
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("STAGE40_AUDIT_ERROR=" + type(exc).__name__, file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
