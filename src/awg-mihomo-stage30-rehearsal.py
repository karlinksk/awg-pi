#!/usr/bin/env python3
"""Stage30 backup/preflight/rollback rehearsal only. No apply/install path."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

CONFIG_FILES = (
    "/etc/awg-pbr/transports/mihomo/config.yaml",
    "/var/lib/awg-pbr/mihomo/providers/subscription.yaml",
    "/etc/awg-pbr/transports/mihomo/provider.env",
    "/etc/awg-pbr/transports/mihomo/node-name",
    "/etc/awg-pbr/transports/mihomo/endpoint-ip",
    "/etc/awg-pbr/transports/mihomo/node-policy.mode",
    "/etc/awg-pbr/transports/mihomo/native-fallback.mode",
    "/etc/awg-pbr/selection.env",
    "/etc/awg-pbr/mode",
)
CORE_REQUIRED = CONFIG_FILES[:2]
VALIDATOR = Path(__file__).with_name("awg-mihomo-fallback-preview.py")


def load_preview():
    spec = importlib.util.spec_from_file_location("stage30_preview", VALIDATOR)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def invoke(args, timeout=12):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"read-only check failed: {args[0]} command")
    return p.stdout


def tmpfs_required():
    kind = invoke(["findmnt", "-n", "-o", "FSTYPE", "-T", "/tmp"]).strip()
    if kind != "tmpfs":
        raise ValueError("refuse backup of credentials outside tmpfs")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def secure_snapshot(sources, root, required=()):
    """Read-only secure source copy to RAM; rejects symlinks and nonregular files."""
    records = []
    dest = root / "snapshot"
    dest.mkdir(mode=0o700)
    for idx, source in enumerate(sources):
        source = Path(source)
        try:
            st = source.lstat()
        except FileNotFoundError:
            if str(source) in required:
                raise
            records.append((source, None, None))
            continue
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("source must be a regular non-symlink file")
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            actual = os.fstat(fd)
            if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (st.st_dev, st.st_ino):
                raise ValueError("source changed during snapshot")
            dst = dest / f"{idx:02d}.snapshot"
            out = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "rb") as fi, os.fdopen(out, "wb") as fo:
                    fd = -1
                    shutil.copyfileobj(fi, fo)
            finally:
                if fd >= 0:
                    os.close(fd)
        except Exception:
            if fd >= 0:
                os.close(fd)
            raise
        records.append((source, dst, digest(dst)))
    return records


def assert_sources_unchanged(records):
    for source, snapshot, oldhash in records:
        if snapshot is None:
            if source.exists() or source.is_symlink():
                raise RuntimeError("previously absent file appeared")
        elif digest(source) != oldhash:
            raise RuntimeError("source changed during rehearsal")


def rehearse_rollback(records, root):
    """Only mutates an isolated replica, never any source path."""
    replica = root / "replica"
    replica.mkdir(mode=0o700)
    for idx, (_, snapshot, _) in enumerate(records):
        if snapshot:
            shutil.copyfile(snapshot, replica / f"{idx:02d}.replica")
    copied = [(idx, snap, sha) for idx, (_, snap, sha) in enumerate(records) if snap]
    if not copied:
        raise RuntimeError("no snapshot data")
    index, original, sha = copied[0]
    altered = replica / f"{index:02d}.replica"
    altered.write_bytes(b"fault-injection-isolated-only")
    if digest(altered) == sha:
        raise RuntimeError("fault injection was not applied")
    # Restore all private replica files, including one corrupted by the test.
    for idx, (_, snapshot, _) in enumerate(records):
        dst = replica / f"{idx:02d}.replica"
        if snapshot:
            shutil.copyfile(snapshot, dst)
        elif dst.exists():
            dst.unlink()
    for idx, (_, snapshot, sha) in enumerate(records):
        dst = replica / f"{idx:02d}.replica"
        if snapshot and digest(dst) != sha:
            raise RuntimeError("rollback replica mismatch")
        if snapshot is None and dst.exists():
            raise RuntimeError("unexpected file survived rollback")
    return len(copied)


def service_snapshot():
    names=("awg-mihomo.service", "awg-selection-monitor.service", "awg-quick@awg0.service", "awg-pbr-health.service")
    states={}
    for name in names:
        result=subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        states[name]=(result.returncode, result.stdout.strip())
    return states


def preflight(node_names, iface, router, root):
    before_route = invoke(["ip", "-4", "route", "show", "table", "100"])
    before_rule = invoke(["ip", "-4", "rule", "show"])
    before_guard = invoke(["nft", "list", "chain", "inet", "awg_pbr", "forward_guard"])
    before_transport = invoke(["awg-transport", "status"])
    before_services = service_snapshot()
    if "Transport ID: mihomo" not in before_transport or "Transport health: healthy" not in before_transport:
        raise ValueError("production Mihomo is not healthy")
    if "policy drop;" not in before_guard:
        raise ValueError("Transit forward guard lacks default drop")
    if "default dev mihomo0" not in before_route:
        raise ValueError("unexpected active table 100")

    preview = load_preview()
    base = yaml.safe_load(Path(CONFIG_FILES[0]).read_text())
    provider = yaml.safe_load(Path(CONFIG_FILES[1]).read_text())
    nodes = preview.choose_nodes(provider, node_names)
    preview.check_routes(nodes, iface, router)
    staged = preview.candidate(base, nodes)
    staged["tun"]["enable"] = True
    staged["tun"]["auto-route"] = False
    staged["tun"]["auto-redirect"] = False
    candidate_file = root / "production-shape-validation-only.yaml"
    preview.save_ram_private(candidate_file, staged)
    try:
        invoke(["/usr/local/bin/mihomo", "-t", "-d", str(root), "-f", str(candidate_file)], timeout=20)
    finally:
        candidate_file.unlink(missing_ok=True)

    return (before_route, before_rule, before_guard, before_transport, len(nodes), before_services)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--node", action="append", required=True)
    p.add_argument("--iface", required=True)
    p.add_argument("--router", required=True)
    args = p.parse_args()
    try:
        tmpfs_required()
        oldmask = os.umask(0o077)
        root = Path(tempfile.mkdtemp(prefix="awg-stage30-rehearsal-", dir="/tmp"))
        os.umask(oldmask)
        try:
            root.chmod(0o700)
            records = secure_snapshot(CONFIG_FILES, root, CORE_REQUIRED)
            baseline = preflight(args.node, args.iface, args.router, root)
            rolled = rehearse_rollback(records, root)
            assert_sources_unchanged(records)
            if service_snapshot() != baseline[5]:
                raise RuntimeError("service state changed during rehearsal")
            for command, previous in (
                (["ip", "-4", "route", "show", "table", "100"], baseline[0]),
                (["ip", "-4", "rule", "show"], baseline[1]),
                (["nft", "list", "chain", "inet", "awg_pbr", "forward_guard"], baseline[2]),
                (["awg-transport", "status"], baseline[3]),
            ):
                if invoke(command) != previous:
                    raise RuntimeError("runtime state changed during rehearsal")
            print(f"STAGE30_PREFLIGHT=PASS nodes={baseline[4]} routes=DIRECT config=MihomoValidated")
            print(f"STAGE30_SNAPSHOT=RAM_ONLY entries={rolled}")
            print("STAGE30_ROLLBACK_REPLICA=PASS")
            print("STAGE30_PRODUCTION_MODIFIED=false")
        finally:
            shutil.rmtree(root)
    except Exception as exc:
        # No secret-bearing values from inputs or configuration must be echoed.
        print(f"STAGE30_REJECTED={type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
