# Stage39 — single-owner transaction + independent restore (fixture only)

**Date:** 2026-10-13. **State: experimental local code only; no production activation.**

## Immutable boundaries

MikroTik and NAS remain independent, immutable appliances. Existing MikroTik policy routes marked traffic via SSTP while available and via the Raspberry Pi when SSTP is unavailable. This code operates only in private mock directories on the Pi; it never queries or configures MikroTik/NAS, SSTP, live Mihomo/AWG, nftables or policy routes.

## Integration of Stages36–38

Stage36 provides a SHA-256/READY snapshot of a fixed 11-file state list. Stage37 provides the same nonblocking maintenance lock used by other Pi Gateway components. Stage38 provides byte- and metadata-exact, restartable file restoration while leaving the mock forwarding guard active. Stage39 composes all three, holding **one** shared fixture maintenance lock over every step, rather than deadlocking by reacquiring it through separate CLI processes.

The only accepted target is a user-owned 0700 `awg-stage36-*` fixture directory directly below /tmp or HOME. All test source files are synthetic and the writes cannot reach actual `/etc/awg-pbr`, `/var/lib/awg-pbr`, RouterOS or NAS paths.

### Transaction

1. `--start` checks a synthetic healthy-state marker, a synthetic candidate, absence of any previous transaction/backup and acquires maintenance lock.
2. It creates and verifies a private READY backup before publishing the persistent transaction journal.
3. It then writes a **synthetic** lockdown marker, modifies the synthetic candidate config and leaves the journal `pending`. No new VPN transport is actually started.
4. `--confirm` requires the synthetic guard, good backup, simulated health and an unchanged candidate before writing a `confirmed` journal, then deletes mock backup/journal. It **does not remove** the mock lockdown marker or automatically reopen traffic.
5. `--recover`, launched as an independent process, creates/refreshes the mock lockdown marker *first*, verifies all snapshot entries and restores the original fixture files through Stage38 while retaining both journal and backup for inspection. Subsequent recoveries are idempotent.
6. A missing journal but existing READY backup is considered an incomplete transaction; it is quarantined. Invalid journal or corrupted backup is also quarantined. The tool refuses any recovery beyond the mock fixture.
7. A `confirmed` journal denotes a committed transaction; recovery completes interrupted cleanup without undoing the accepted candidate.

### Tests

- 12 focused Stage39 tests passed: transaction, confirm, separate recovery, five injected crash windows, resuming after interrupted restore, corrupted backup/journal, invalid preflight, candidate mismatch, lock contention, hard path guard, confirmed cleanup and synthetic external device invariance.
- A disposable **real ext4** mock-fixture test on the authorized Pi: injected process crash after test config replacement (exit 42), independently restarted recovery, original fake config restored, simulated lockdown retained, backup/journal still present for audit inside the test and temporary folder removed at completion.
- Production `awg-gpt` read-only checks showed active healthy Mihomo and `table 100 = default dev mihomo0`.
- A full Python regression pass and GitHub CI are tracked separately.

## Limitations and next steps

This is **NOT a production coordinator, watchdog or boot unit**. Its guard is only a text marker, not verified nftables FAIL-CLOSED. Its health is synthetic, no candidate DIRECT probing occurs, no live service or route state is mutated, and it is not installed by `install.sh`. It does not implement a bounded live confirmation lease or early boot replay.

Before production, a separately reviewed privileged coordinator must (a) own the real `awg-maintenance.lock` for the entire transaction, (b) take the private local root-owned recovery snapshot, (c) positively enforce and verify nftables Transit lockdown and safe policy rules before touching config, (d) perform atomic real service/config switching, (e) verify HTTPS, DIRECT underlays, transport ownership, policy route and non-leakage, and (f) confirm or roll back within a bounded interval. An independently started **real** systemd recovery unit must run before Pi forwarding after reboot. Only after disposable namespace/VM tests and approved supervised reboot may native fallback be enabled.

**Do not merge Stage39 alone, enable native fallback, or interrupt production SSTP.**
