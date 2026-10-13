#!/usr/bin/env python3
"""Stage32: fixture-only lease watchdog and independently recoverable activation.

No production path accepted. No systemctl, nft, ip, routing or real service changes.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

def load_stage31():
    file=Path(__file__).with_name("awg-mihomo-stage31-fixture-transaction.py")
    spec=importlib.util.spec_from_file_location("stage31_fixture",file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

stage31=load_stage31()
STATE_FILE="watchdog.json"

def read_boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def record_path(root):
    return root/STATE_FILE

def state_read(root):
    path=record_path(root)
    if not path.exists() or path.is_symlink():
        raise stage31.TransactionError("lease missing or unsafe")
    lease=json.loads(path.read_text())
    if lease.get("version")!=1 or lease.get("status")!="pending":
        raise stage31.TransactionError("invalid lease state")
    if not isinstance(lease.get("boot_id"),str) or not lease["boot_id"]:
        raise stage31.TransactionError("invalid boot identity")
    if type(lease.get("deadline")) is not int or lease["deadline"]<0:
        raise stage31.TransactionError("invalid deadline")
    if type(lease.get("created_at")) is not int or not 0<=lease["created_at"]<lease["deadline"]:
        raise stage31.TransactionError("invalid lease start")
    return lease

def fixture_healthy(root):
    try:
        if (root/"live"/"transport").read_text().strip()!="mihomo":
            return False
        if (root/"live"/"direct-state").read_text().strip()!="verified":
            return False
        if (root/"live"/"service-state").read_text().strip()!="active":
            return False
        if (root/"live"/"route-state").read_text().strip()!="transit-safe":
            return False
        if (root/"live"/"mode").read_text().strip()!="native":
            return False
        data=stage31.read_fixture_candidate(root)
        active=(root/"live"/"config.yaml").read_bytes()
        return active==(root/"candidate.yaml").read_bytes() and len(data["proxy-groups"])>=1
    except (OSError,ValueError,KeyError,stage31.TransactionError):
        return False

def restore_and_clear(root):
    # Recovery integrity check happens before writing to any live fixture.
    recovered=stage31.restore(root)
    if recovered:
        record_path(root).unlink(missing_ok=True)
    return recovered

def arm(root,now,boot_id,deadline_seconds,crash_phase=None):
    if not 15<=deadline_seconds<=600:
        raise stage31.TransactionError("lease outside bounded range")
    if (root/stage31.JOURNAL).exists() or (root/"backup").exists() or record_path(root).exists():
        raise stage31.TransactionError("unfinished activation requires recovery")
    stage31.require_preflight(root)
    try:
        stage31.snapshot(root)
        # Lease is persisted before the first simulated disruptive change.
        stage31.atomic_json(record_path(root),{
            "version":1,"status":"pending","created_at":now,"deadline":now+deadline_seconds,"boot_id":boot_id
        })
        if crash_phase=="armed":
            os._exit(42)
        stage31.atomic_bytes(root/"live"/"route-state",b"lockdown\n")
        stage31.set_phase(root,"quarantine")
        if crash_phase=="quarantine":
            os._exit(42)
        stage31.atomic_bytes(root/"live"/"config.yaml",(root/"candidate.yaml").read_bytes())
        stage31.atomic_bytes(root/"live"/"mode",b"native\n")
        stage31.set_phase(root,"install")
        if crash_phase=="install":
            os._exit(42)
        stage31.atomic_bytes(root/"live"/"route-state",b"transit-safe\n")
        stage31.set_phase(root,"verify")
        if crash_phase=="verify":
            os._exit(42)
        # Deliberately remain PENDING; confirmation is a separate operation.
        if not fixture_healthy(root):
            raise stage31.TransactionError("post-activation simulated health failure")
    except Exception:
        restore_and_clear(root)
        raise

def finish_confirmed_cleanup(root):
    # Once phase=confirmed is journaled, interrupted cleanup must NOT roll
    # back a verified commit whose backup may already be partly removed.
    journal_path=root/stage31.JOURNAL
    if not journal_path.exists():
        raise stage31.TransactionError("confirmed journal missing")
    journal=json.loads(journal_path.read_text())
    if journal.get("version")!=1 or journal.get("phase")!="confirmed":
        raise stage31.TransactionError("not a confirmed journal")
    backup=root/"backup"
    if backup.exists():
        shutil.rmtree(backup)
    record_path(root).unlink(missing_ok=True)
    journal_path.unlink()


def check(root,now,boot_id):
    journal=(root/stage31.JOURNAL)
    if not journal.exists():
        if record_path(root).exists() or (root/"backup").exists():
            raise stage31.TransactionError("orphan activation files need human review")
        return "IDLE"
    try:
        phase=json.loads(journal.read_text()).get("phase")
    except (OSError,json.JSONDecodeError):
        raise stage31.TransactionError("invalid recovery journal")
    if phase=="confirmed":
        finish_confirmed_cleanup(root)
        return "COMMIT_CLEANUP"
    try:
        lease=state_read(root)
    except Exception:
        if restore_and_clear(root):
            return "ROLLBACK_INVALID_LEASE"
        raise
    if lease["boot_id"]!=boot_id:
        restore_and_clear(root)
        return "ROLLBACK_BOOT_CHANGED"
    if now<lease["created_at"]:
        restore_and_clear(root)
        return "ROLLBACK_CLOCK_ROLLBACK"
    if now>=lease["deadline"]:
        restore_and_clear(root)
        return "ROLLBACK_DEADLINE"
    if not fixture_healthy(root):
        restore_and_clear(root)
        return "ROLLBACK_HEALTH"
    return "PENDING_ACK"

def confirm(root,now,boot_id):
    lease=state_read(root)
    if lease["boot_id"]!=boot_id or now<lease["created_at"] or now>=lease["deadline"] or not fixture_healthy(root):
        restore_and_clear(root)
        raise stage31.TransactionError("confirmation preconditions not met")
    # A durable commit marker MUST precede backup deletion. An independent
    # watchdog completes garbage collection if this process crashes.
    stage31.set_phase(root,"confirmed")
    finish_confirmed_cleanup(root)
    return "CONFIRMED"

def cli():
    ap=argparse.ArgumentParser(description="PRIVATE TMPFS TEST FIXTURE ONLY")
    ap.add_argument("--fixture-root",required=True)
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--arm",action="store_true")
    mode.add_argument("--check",action="store_true")
    mode.add_argument("--confirm",action="store_true")
    mode.add_argument("--cancel",action="store_true")
    ap.add_argument("--timeout-seconds",type=int,default=60)
    ap.add_argument("--simulated-now",type=int)
    ap.add_argument("--simulated-boot-id")
    ap.add_argument("--crash-after",choices=("armed","quarantine","install","verify"))
    opts=ap.parse_args()
    try:
        root=stage31.private_root(opts.fixture_root)
        now=int(time.time()) if opts.simulated_now is None else opts.simulated_now
        boot_id=read_boot_id() if opts.simulated_boot_id is None else opts.simulated_boot_id
        if not boot_id or len(boot_id)>128 or now<0:
            raise stage31.TransactionError("invalid test clock")
        fd=os.open(root/"transaction.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if opts.arm:
                arm(root,now,boot_id,opts.timeout_seconds,opts.crash_after)
                result="ARMED_PENDING"
            elif opts.check:
                result=check(root,now,boot_id)
            elif opts.confirm:
                result=confirm(root,now,boot_id)
            else:
                result="RECOVERED" if restore_and_clear(root) else "NOT_REQUIRED"
            print("STAGE32_FIXTURE="+result)
        finally:
            os.close(fd)
    except (OSError,ValueError,stage31.TransactionError,json.JSONDecodeError) as exc:
        print("STAGE32_FIXTURE_ERROR="+type(exc).__name__,file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    raise SystemExit(cli())
