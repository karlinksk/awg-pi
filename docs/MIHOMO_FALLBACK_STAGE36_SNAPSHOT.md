# Stage36 — Root-only local snapshot primitive, uninstalled

**Status:** 13 October 2026: code and tests complete; real root-owned production snapshot **not invoked**. No live boot recovery or native fallback installation.

## Fixed network and device boundary

MikroTik and NAS are independent appliances whose configuration MUST remain unchanged. MikroTik's existing routing is fixed: **marked traffic uses SSTP while available; when SSTP is absent/down, that marked traffic is routed to Raspberry Pi**. Pi's Transit policy remains FAIL-CLOSED if Mihomo and AWG are unavailable. No code in this stage logs into MikroTik/NAS, reads their data, uses their API or modifies their state.

## New snapshot primitive

`src/awg-mihomo-stage36-snapshot.py` introduces an intentionally **one-shot** snapshot/verify engine, not an installer and not a recovery executor.

It captures a fixed whitelist of up to 11 files:
- `/etc/awg-pbr/transports/mihomo/config.yaml`
- `/var/lib/awg-pbr/mihomo/providers/subscription.yaml`
- `/etc/awg-pbr/transports/mihomo/provider.env`
- `/etc/awg-pbr/transports/mihomo/node-name`
- `/etc/awg-pbr/transports/mihomo/endpoint-ip`, `expected-egress-ip`
- `/etc/awg-pbr/transports/mihomo/node-policy.mode`, `native-fallback.mode`
- `/etc/awg-pbr/selection.env`, `/etc/awg-pbr/transport`, `/etc/awg-pbr/mode`

The first two entries are required; other files are explicitly marked absent/present. No wildcard scan includes keys or unrelated secrets.

### Security and durability controls

- Optional **production** capture requires root, a fixed destination `/var/lib/awg-pbr/native-fallback-recovery`, and an explicit extra acknowledgement flag. The source tree must have trusted root ownership. **The production command has never been executed and this helper is NOT installed by install.sh.** Other code can later validate the snapshot, but no production restore service exists yet.
- Private destination 0700, backup payloads 0600; reject symlink files and suspicious directories. Keep the backed-up bytes out of logs and GitHub.
- Every source is read once through `O_NOFOLLOW`, bounded to 16 MiB per file, and recorded with a SHA-256 digest, original owner/group/mode and present/absent state.
- Use temporary files, file `fsync`, atomic rename and directory `fsync`. Publish manifest before the `READY` marker; READY is published last.
- Independent verification checks exact whitelist membership, metadata, digest and payload set. Invalid/incomplete snapshots are rejected. A repeated capture cannot overwrite a previous snapshot.
- A separate lock forbids concurrent backup writers. **Stage37 additionally integrates the existing `/run/awg-maintenance.lock` for the snapshot operation; full production cutover must still hold that lock across snapshot, configuration replacement and confirmation.**
- There is deliberately **no** systemctl, ip, nft, RouterOS, NAS, recovery write-back or network operation in this module. It cannot activate or replace a transport.

### Fixture and actual ext4 validation

In safe fixture mode, input files are synthetic and rooted in a private `awg-stage36-*` directory directly under /tmp or the invoking user's HOME; writes never touch /etc or /var. 15 dedicated regression tests passed (required/optional sources, missing READY, tampering, extras, symlinks, locks, group/world-writable directory, root-mode denial).

A separate **real ext4 test** on the Pi's microSD used synthetic config/provider contents under a private disposable HOME subdirectory. Snapshot created READY and the independent verify process accepted the digest manifest. Both commands exited successfully and the test directory was removed.

No physical power-loss or reboot was performed; ext4 testing demonstrates one-process-to-another persistence and checksums, not hardware power-fail survival.

### Next gates — NOT production ready

1. Implement a root-owned **transaction coordinator** that holds the existing `awg-maintenance.lock`, obtains and verifies an immutable snapshot with known-good health/guard, and then carries out a bounded, explicitly approved config change.
2. Implement the **actual privileged boot recovery**: read journal and READY before forwarding, install nftables Transit lockdown first, restore real source paths atomically, validate Mihomo/AWG and DIRECT routes and only then allow safe Transit; if anything fails, lockdown remains.
3. Implement early systemd ordering for `awg-pbr-setup.service`, `awg-mihomo.service` and `awg-selection-monitor.service`. Stage34 examples are deliberately disabled (ExecStart=/usr/bin/false), and must not be installed as if functional.
4. Test restoration of real services/network state in an isolated namespace/VM or disposable stand, and supervise a real Pi reboot only when independent recovery and known-good backups are proven.
5. Reduce microSD writes: take protected persistent backups **only before a deliberately approved production change**; health checks, recent handshakes and heartbeat markers remain in RAM.
6. Keep MikroTik/NAS untouched and never use their services as a condition for Pi boot recovery.

Do not merge this PR or activate native fallback solely because the snapshot tests and GitHub CI succeed.
