# Stage38 — Exact-file rollback engine in a guarded isolated fixture

Status: 13 October 2026, **uninstalled synthetic fixture only**. Stage36–37 backup data format is now exercised by a separate restore engine. No actual Pi configuration restoration or service restart has occurred.

## Responsibilities and hard boundaries

MikroTik and NAS remain independent fixed devices. Existing MikroTik policy routes marked traffic through SSTP when available, otherwise to Pi. Pi handles Mihomo → AWG fallback and maintains Transit FAIL-CLOSED on transport failure. No Stage38 code accesses RouterOS, SSTP, NAS or the production Pi's network interfaces.

## Restoration algorithm

`src/awg-mihomo-stage38-restore-fixture.py` loads the Stage36 backup library but exposes **only** a private `awg-stage36-*` fixture root. It has no production mode and cannot target /etc or /var. An explicit synthetic 0600 `fixture-lockdown.guard` marker is required for restoration; merely verifying a backup does not need this marker. The marker represents (does not implement) an nftables FAIL-CLOSED guard.

1. Acquire the same private maintenance lock used by Stage36–37 fixture snapshots.
2. Verify the complete READY manifest, all 11 expected slots, SHA-256 digests, metadata and zero unexpected payloads **before** writing a single restore target.
3. Preflight every intended fake filesystem destination: refuse symlinked/untrusted ancestor directories, symlink targets or nonregular files.
4. Restore each present file using a private 0600 temporary file, original recorded owner/group/mode, file `fsync`, atomic rename and parent directory `fsync`.
5. For paths recorded as absent, remove any mock file unexpectedly created during the failed transaction.
6. Recompare restored bytes and metadata with the published backup. Leave the backup and synthetic lockdown guard present; **this tool deliberately does not reopen Transit**.
7. Interrupted partial restoration is restartable: repeated execution uses the original immutable snapshot, not already-restored files.

### Tests

- 11 Stage38 fixture tests passed: complete restore, idempotent replay, optional absence, no/malformed lockdown guard, corrupt snapshot, malicious symlink, maintenance lock contention and process crash/retry at multiple file indices.
- An actual ext4 microSD **synthetic** test used disposable fake config/provider files under the user's HOME. Stage36 snapshot was saved, the mock config was altered, and a separately invoked Stage38 process restored the original bytes while keeping the mock guard and READY intact. The fixture was deleted.
- Production Mihomo stayed healthy and route table 100 remained `default dev mihomo0`.

## Critical missing production safety

This restores only **fake files**, not live service state, routes or nftables. A guard marker cannot prove nftables FAIL-CLOSED. Before installing a privileged version, a real coordinator must acquire `awg-maintenance.lock` across the entire cutover, independently establish the actual forwarding block, safely stop affected services, validate the complete root-owned snapshot, restore files and source metadata, enforce health + endpoint DIRECT checks, and only then release protected traffic. A root-owned early-boot systemd service and known-good rollback path must be tested on a disposable environment prior to any production changes.

No production cutover, native fallback activation, Pi reboot, physical power-loss, MikroTik change or NAS operation is authorized or performed by this Stage38 fixture.
