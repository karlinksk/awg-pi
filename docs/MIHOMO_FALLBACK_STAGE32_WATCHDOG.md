# Stage32 — independent lease watchdog and recovery after reboot (fixture-only)

**Status: development-only prototype, not a production deployer, not installed in systemd.**

The Stage31 transaction fixture restores its original state when the controlling process fails, but cannot distinguish an unconfirmed activation from a confirmed one, or bound the time allowed for post-activation checks. Stage32 adds a separate watchdog/lease and mock user-systemd examples. None of these changes read live VPN keys, change the gateway, restart services, edit RouterOS, or create persistent microSD files.

## State and behavior

All commands use a **private, owned 0700 fixture under /tmp tmpfs** and the Stage31 mock network/service files only. There is no mode that accepts a real root configuration directory.

- **ARM:** refuse overlapping transactions or invalid preflight, take a SHA-256 verified fixture snapshot, write the watchdog lease *before* the first simulated disruptive step, record a boot identifier and deadline (15–600 seconds), then simulate Transit quarantine, native fallback install and health verification. Leave the transaction **PENDING** without auto-committing.
- **CHECK:** independently launched process reads the journal, checks the boot identifier, time (including backward clock changes), health/guard and DIRECT markers. If pending and safe, report `PENDING_ACK` without mutation. If unhealthy, expired, boot changed or lease missing/corrupt, restore the fixture from a verified backup. A damaged backup is refused, with the journal retained for investigation.
- **CONFIRM:** only a fresh successful check before the deadline may commit. Mark the transaction journal **confirmed before deleting the backup**. If interrupted during cleanup, another CHECK finishes cleanup, rather than attempting to roll back a partially deleted backup.
- **CANCEL:** restore the pre-activation fixture immediately, idempotently.
- **Concurrent attempts:** refuse additional transaction while the lock is held or a journal exists.

### What “reboot recovery” means in these tests

A new independently started process with a different `boot_id` triggers recovery for an unconfirmed fixture transaction. This models a reboot condition; **the Raspberry Pi was NOT rebooted**. The fixture is on tmpfs, so it would itself be erased by a genuine reboot. Thus Stage32 does **not** provide real reboot-persistent rollback or unattended production protection.

### systemd examples

`examples/stage32-fixture-systemd/` includes a demonstration **user** oneshot service and timer, not referenced from `install.sh`, with no enabling `[Install]` section. The service is conditional on a private fixture journal at `/tmp/awg-stage32-demo/transaction.json`, and its developer-only source path `%h/stage32-sandbox` is intentionally absent on production hosts. The timer demonstrates polling after boot and at 10-second intervals; it is not a root recovery unit and cannot survive a reboot of its tmpfs fixture.

On the Raspberry Pi, `systemd-analyze verify` passed on both example units. No actual user service/timer was launched: the remote noninteractive shell has no user D-Bus manager session available.

## Test evidence — 13 October 2026

- 17 dedicated Stage32 tests passed, covering crash in four phases, independent recovery, deadline expiration, altered boot identity, clock rollback, DIRECT/health failure, manual cancellation, duplicate lock, unsafe paths, corrupted lease/backup, expired confirmation, interrupted cleanup before and after backup deletion.
- Tests restore fixture state byte-for-byte, never source production configs or credentials.
- Project-wide Python regression and GitHub integration CI are tracked in the corresponding PR.
- Approved `awg-gpt` read-only status still reports working Mihomo; table 100 remains `default dev mihomo0`.

## Non-negotiable gates for a future **real** rollback service

1. Prepare a **durable root-owned, mode 0700 recovery directory** (e.g. a dedicated protected partition/volume) with key/config snapshots mode 0600, hash manifest, atomic rename and file *and directory fsync*, before any production mutation. Do not use tmpfs for reboot recovery. Never publish these backup contents. Minimize flash writes by recording one bounded transaction, not periodic status writes.
2. A root-owned systemd recovery unit must run at boot **before** any Mihomo/TUN/Transit forwarding is enabled if an unconfirmed journal exists. It must verify nftables FAIL-CLOSED before applying any route and coordinate with `awg-maintenance.lock`.
3. Lease timeout and health checks must be independent of the modifying process and reliably survive a crash. A reboot with a still-unconfirmed transaction should revert to the known-good state, not assume success.
4. Before declaring a restore successful, validate restored config and provider, service state, NAT/nftables, table100/fwmark and endpoint DIRECT routes; if validation fails, keep Transit quarantined and make failure visible to the operator. Never switch a protected client to DIRECT.
5. Verify the existing MikroTik SSTP management path independently, and preserve its route during every action. Include an actual outage, process crash and **supervised Pi reboot** only after backups, access and independent rollback are proven.
6. Audit rollback **commit-crash windows** and clock/boot changes, power-loss durability, credentials/permissions, and service ordering. Do not deploy a fixture watchdog as a production service.

Passing unit tests or CI alone must not be interpreted as readiness for production activation.
