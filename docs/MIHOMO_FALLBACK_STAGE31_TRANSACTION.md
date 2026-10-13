# Stage31 — independent transaction recovery (fixture-only prototype)

Status: **EXPERIMENTAL, not installable, no production apply mode.** Depends on Stage30 and the native Mihomo fallback PR stack.

This change tests the state machine needed for an eventual safe deployment to AWG Pi Gateway. `src/awg-mihomo-stage31-fixture-transaction.py` intentionally accepts only `--fixture-root` in an owner-private (0700) directory on `/tmp` mounted as tmpfs. All mutations are inside that directory: no actual service, route, nftables, Pi config or MikroTik command exists in this program.

## Lifecycle proven in isolation

The mock live state comprises fixed fixture files named `config.yaml`, `mode`, `service-state`, `route-state`, `transport` and `direct-state`. A candidate is accepted only when it defines a TUN-enabled `AWG-MIHOMO` fallback group with two to four explicit node names.

1. Require an active fixture service, current transport Mihomo, verified DIRECT marker and Transit-safe route.
2. Acquire an exclusive nonblocking lock. Refuse symlinks and a nonprivate/non-tmpfs fixture.
3. Snapshot fixed mock state to private 0600 files. Record SHA-256 digests and the transaction phase in an atomic journal.
4. Set the fixture route to lockdown, stage the candidate fixture config and native-mode marker, and verify the new mock config. Keep the journal until the final commit.
5. On an injected fault, restore all mock files from hash-verified backups. If the process crashes after any journaled phase, a **new process** can run `--recover`, verify the backup set first and restore the original fixture state.
6. Refuse a second concurrent transaction. If the backup has been altered, stop safely and retain the recovery journal for operator inspection; never restore unverified bytes.
7. Commit removes the fixture journal/backup. Recovery without a pending journal is idempotent.

The isolated test suite runs faults and separate-process crashes at four phases: snapshot, quarantine, install and verify. It checks the initial fixture byte-for-byte after recovery.

## Test commands

```bash
python3 -B -m unittest discover -s tests -p 'test_mihomo_stage31_fixture_transaction.py' -v
python3 -B -m unittest discover -s tests -p 'test_*.py' -q
```

The fixture tests construct their own fake candidate and mock live files and automatically remove the temporary directories. They do not read or use any production provider subscription or credentials.

## Hard limits before enabling on the gateway

This prototype is **not** a production transaction or a watchdog:

- It does not perform actual `systemctl`, `ip`, `nft` or root file operations. It must never be passed a real gateway directory.
- The journal and backups are on tmpfs, so they **cannot** survive a Raspberry Pi reboot. Production recovery requires protected persistent backup, staged and hash-checked before any production mutation.
- The transaction must lock together with the live `awg-maintenance.lock` owner and prevent the selection monitor from racing the change.
- A production implementation must orchestrate verified Transit lockdown, stop/restart/health-check of the service, resynchronization of routing and guard, and safe selection ownership.
- An independent systemd rollback unit with a finite deadline must restore the original configuration when activation fails, crashes or reboots. It should neither edit MikroTik nor jeopardize SSTP.
- Real recovery must be supervised while the user has an independent management channel. Verify endpoint DIRECT routes before/after and the nftables FAIL-CLOSED behavior by real packets, not only by mock state.
- Secrets belong only in root-owned private backups; no subscription keys, URLs or passwords are permitted in PR content or CI logs.

No production activation is approved by the existence of this PR.
