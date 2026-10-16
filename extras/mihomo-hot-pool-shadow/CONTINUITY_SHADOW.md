# AWG v1.3 — Hot Pool provider continuity (experimental SHADOW_ONLY)

## Contract

- Periodic subscription updates are **staged**, never promoted by latency-only `auto-best`. See PR #109.
- The persistent root-only vault holds at most 16 verified old transport profiles and 24 pending healthy candidate profiles, each with a 24h maximum retention without refresh.
- Every eligible profile is fingerprinted over **all settings including credentials** (but not the display name). Credential/key/transport changes cannot inherit old qualifications.
- Old profiles remain eligible for *fresh* independent service checks even when deleted from new subscription. Never claim READY from a historic profile alone.
- Only health-scanned candidate profiles are admitted into the pending queue. Eligibility still requires two fresh service PASSes at least 10 min apart and no stale evidence; each cycle checks no more than two isolated nodes.
- The union of live, archived and pending candidate profiles is stored **only in RAM**, root owned at 0600. No URLs, keys, or raw profiles may enter journald or GitHub.
- The protected vault is in `/var/lib/awg-pbr/hot-pool/continuity/vault.json`, directory 0700, file 0600. It is rewritten only when qualified profiles or pending entries change or on six-hour refresh.
- Hot Pool output remains `SHADOW_ONLY`. Neither this helper nor the wrapper installs nodes in production or changes selectors, TUN, routing, AWG or MikroTik.

## Proposed deployment (not enabled by default)

1. Copy `awg-hot-pool-continuity.py` and wrapper to `/usr/local/sbin` as root 0755. Copy updated Hot Pool scanner and engine, preserving rollback copies.
2. Create `/var/lib/awg-pbr/hot-pool/continuity` and `/run/awg-pbr/hot-pool/continuity` as root 0700. Confirm vault path is mounted and backed up securely, without cloud or GitHub exposure.
3. Modify only the existing `awg-mihomo-hot-pool.service` ExecStart to call the continuity wrapper. Because it uses `ProtectSystem=strict`, add `ReadWritePaths=/var/lib/awg-pbr/hot-pool/continuity`. Leave existing CPUQuota, MemoryMax, NoNewPrivileges, CapBoundingSet, PrivateTmp and timer unchanged.
4. Dry-run shadow against nonsecret synthetic provider fixtures, then observe controlled live subscriber rotation. Compare READY stability, old-credential accessibility, duplicate identities, CPU/RAM, archive disk-write count and routes.
5. **Do not enable automated selection from the retained archive** until a separate transactional promotion mechanism can import the exact verified profile into Mihomo without interrupting SSTP or compromising fail-closed routing. Never treat the archive as already selectable by the live node selector.

## Restart / expiry behavior

The vault survives subscription rotation and Pi reboot; **READY proofs in RAM do not**. After reboot (or proof expiry) isolated tests must earn READY again. Profiles deleted from every source and unconfirmed for 24h are pruned. The pending queue is bounded and expired scans are never reused as current proof.

## Validation

`python3 -B extras/mihomo-hot-pool-shadow/test_hot_pool_continuity.py`

Original Hot Pool tests should remain green. No network access or production service changes are needed for fixture tests.