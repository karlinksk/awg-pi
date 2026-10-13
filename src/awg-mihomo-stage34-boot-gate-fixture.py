#!/usr/bin/env python3
"""Stage34: boot-order recovery GATE, isolated fixture only.

Writes ONLY beneath a private user-owned /tmp tmpfs fixture. It never
installs a systemd unit, manages real SSTP or opens production VPN paths.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

def load(filename,module):
    spec=importlib.util.spec_from_file_location(module,Path(__file__).with_name(filename))
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

s31=load("awg-mihomo-stage31-fixture-transaction.py","stage31_fixture")
s32=load("awg-mihomo-stage32-fixture-watchdog.py","stage32_fixture")
s33=load("awg-mihomo-stage33-durable-fixture.py","stage33_fixture")

class GateError(Exception):
    pass

def sstp_signature(root):
    # Synthetic sentinel. This test NEVER queries/modifies RouterOS or a real SSTP peer.
    marker=root/"mikrotik-sstp.fixture"
    if marker.is_symlink() or not marker.is_file():
        raise GateError("missing immutable management-channel sentinel")
    return hashlib.sha256(marker.read_bytes()).hexdigest()

def strict_root(root):
    r=s31.private_root(root)
    s33.fixture_root(r)
    return r

def pending_phase(root):
    j=root/s31.JOURNAL
    if not j.exists():return None
    if j.is_symlink():raise GateError("untrusted transaction journal")
    data=json.loads(j.read_text())
    if data.get("version")!=1 or data.get("phase") not in (*s31.PHASES,"confirmed"):
        raise GateError("invalid transaction phase")
    return data["phase"]

def state_from_validated_backup(root,meta):
    files=meta.get("files",{})
    if set(files)!=set(s31.ITEMS):
        raise GateError("incompatible backup schema")
    for key in s31.ITEMS:
        if files[key].get("present") is not True:
            raise GateError("required fixture state missing")
    vals={name:s33.read_regular(root/"recovery"/name) for name in s31.ITEMS}
    if vals["transport"].strip()!=b"mihomo":
        raise GateError("backup transport inconsistent")
    if vals["direct-state"].strip()!=b"verified":
        raise GateError("backup DIRECT not verified")
    if vals["service-state"].strip()!=b"active":
        raise GateError("backup service unhealthy")
    if vals["route-state"].strip()!=b"transit-safe":
        raise GateError("backup policy guard unsafe")
    if vals["mode"].strip()!=b"legacy":
        raise GateError("backup mode not known-good legacy")
    if not vals["config.yaml"]:
        raise GateError("missing backup config")
    return vals

def boot_reconcile(root,inject_fail_at=None):
    root=strict_root(root)
    before=sstp_signature(root)
    try:
        phase=pending_phase(root)
    except (OSError,ValueError,json.JSONDecodeError,GateError):
        # A malformed but present journal can never be treated as no work.
        # Simulated protected-client forwarding stays quarantined.
        if (root/s31.JOURNAL).exists():
            s31.atomic_bytes(root/"live"/"route-state",b"lockdown\n")
        raise
    if phase is None:
        return "NO_PENDING"
    if phase=="confirmed":
        s32.finish_confirmed_cleanup(root)
        if before!=sstp_signature(root):
            raise GateError("management sentinel changed")
        return "CONFIRMED_CLEANUP"
    # Always enter mock TRANSIT LOCKDOWN *before* reading recovery data.
    # No protected-client DIRECT bypass exists in this simulation.
    s31.atomic_bytes(root/"live"/"route-state",b"lockdown\n")
    if inject_fail_at=="quarantine":
        raise GateError("injected crash after lockdown")
    try:
        ready=s33.validate(root)
        vals=state_from_validated_backup(root,ready)
    except (OSError,ValueError,KeyError,TypeError,s33.BackupError) as exc:
        # Keep the fixture in lockdown, preserve both journals for inspection.
        raise GateError("backup invalid; lockdown retained") from exc
    if inject_fail_at=="verified":
        raise GateError("injected crash before restore")
    # Recovery is restartable. The published recovery set is immutable and
    # remains present until a later explicit operator cleanup.
    for name in s31.ITEMS:
        if name=="route-state":continue
        s33.atomic_file(root/"live",name,vals[name])
        if inject_fail_at=="restore:"+name:
            raise GateError("injected interruption during restore")
    if before!=sstp_signature(root):
        raise GateError("management sentinel changed")
    # This final step models restore of protected-client forwarding only after
    # all fixture health, DIRECT and route assertions have been checked.
    s33.atomic_file(root/"live","route-state",vals["route-state"])
    if inject_fail_at=="policy":
        raise GateError("injected crash after policy restore")
    (root/"watchdog.json").unlink(missing_ok=True)
    backup31=root/"backup"
    if backup31.exists():
        shutil.rmtree(backup31)
    (root/s31.JOURNAL).unlink()
    if before!=sstp_signature(root):
        raise GateError("management sentinel changed")
    return "RECOVERED_FAIL_CLOSED"

def main():
    p=argparse.ArgumentParser(description="isolated fixture only; NEVER production")
    p.add_argument("--fixture-root",required=True)
    p.add_argument("--inject-fail",default=None)
    args=p.parse_args()
    try:
        print("STAGE34_BOOT_GATE="+boot_reconcile(args.fixture_root,args.inject_fail))
    except (OSError,ValueError,json.JSONDecodeError,GateError,s31.TransactionError) as exc:
        print("STAGE34_BOOT_GATE_ERROR="+type(exc).__name__,file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
