# Stage33: Crash-consistent backup publication (fixture-only)

**Experimental, noninstallable.** This models a persistent-backup publication protocol but deliberately requires private /tmp fixture paths. It does not copy live production files and is not invoked by install.sh or systemd. It cannot activate Mihomo, edit nftables/routes, or modify SSTP/AWG.

## Problem addressed

A backup directory on disk is not proof of a complete recovery set. A crash may leave incomplete files, an incomplete digest manifest, or stale metadata. Stage33 performs two-phase publication: write mock snapshots and a SHA-256 manifest, sync file contents and directory entries, then publish a marker named READY **last** and fsync the parent directory.

A reader must refuse snapshots without READY, a complete manifest, valid hashes, or where a symlink/nonregular file is found. Snapshots are created with mode 0600 and directories with 0700. Existing snapshots cannot be overwritten silently.

## Fixture-only commands

The tool src/awg-mihomo-stage33-durable-fixture.py supports:

- --snapshot: copy a fixed set of mock files from a private live directory to private recovery. Per-file temp write, fsync, atomic rename and directory fsync are followed by manifest and final READY marker.
- --verify: independently check the readiness marker, exact manifest schema and SHA-256 hashes, and reject unexpected content.
- --rehearse-restore: verify before restoring to a fresh **replica** and verify again. Never writes to the source fixture.

The fixture is restricted to an owner-private /tmp path. No provider credentials are input. Since /tmp is tmpfs, this confirms correct syscall ordering and recovery logic, **not actual power-loss durability** on microSD/SSD/hardware.

## Evidence

- Eleven dedicated Stage33 tests passed on Raspberry Pi.
- Interrupted snapshot generation at selected files and manifest never publishes READY.
- Tampered snapshot or symlink input is rejected. A fully verified replica is byte-identical to the recorded content.
- The tests confirm file and directory fsync calls and private permissions.
- No production config, routing or service writes occurred.

## Required before production

1. Choose a root-owned private **persistent recovery volume** accessible at boot. Do not rely on tmpfs for a real reboot. Preserve microSD life: write one snapshot only when an authorized activation occurs; keep heartbeat/status data in /run.
2. Enforce ownership and no-symlink checks, fsync data and directories, and test storage behavior under real power loss on a sacrificial copy.
3. Create a boot-time root recovery unit ordered before all Mihomo/TUN and Transit client forwarding. An unconfirmed transaction must enter nftables FAIL-CLOSED before restoration.
4. Restore the full provider/config/transport/rules/nftables/service state, verify all DIRECT endpoints, and preserve independent MikroTik SSTP.
5. Run an actual controlled reboot or fault-injection trial with independent management connectivity before authorizing unattended activation.

Stage33 is a proof of backup publication semantics, not a production-ready rollback implementation.
