# Stage35 — persistent filesystem recovery rehearsal (fixture-only)

**Status (13 October 2026): isolated prototype + one successful synthetic ext4 test. No production switch, install or service changes.**

## Immutable infrastructure boundaries

The MikroTik and Synology NAS are independent appliances, entirely out of scope for the AWG Pi Gateway changes. Their existing services, rules, policies, shares, addresses and credentials must not be modified.

MikroTik's pre-existing policy routes **marked traffic through SSTP whenever SSTP is available**, and **through Raspberry Pi when SSTP is absent/down**. We take this MikroTik behavior as a fixed input to the Pi project, not as new routing code to implement. Pi Transit must always remain FAIL-CLOSED for such traffic if both its transports fail.

For the full statement, see SSTP_INDEPENDENCE.md.

## Technical advance over Stages31–34

Stages31–34 modeled restore inside private tmpfs directories. Stage35 adds a self-contained data-only **fixture** that can also operate directly in a private directory under the current user's HOME. On this stand HOME is on local ext4 root on microSD, so the synthetic journal and READY backup persist **between independent processes**, unlike a RAM-only journal.

Allowed fixture roots are a direct child of /tmp or the invoking account's HOME, with exact prefix awg-stage35- and directory mode 0700. Files are mode 0600. The program cannot be pointed at /etc, /var, the actual Mihomo configuration, a NAS mount or any MikroTik resource.

The backup copies six synthetic states, saves SHA-256 digests to manifest.json, fsyncs file data and directory entries, writes READY last, and only then publishes the pending transaction journal. An interruption before the journal leaves an orphan backup; the recovery model refuses it and retains a simulated Transit lockdown.

The --arm mode simulates Transit quarantine, installation of the new fallback configuration and its service state. A different process --boot-recover restores all known-good fixture files while keeping mock Transit blocked until the final step. Crash injection may occur during journal creation, quarantine, candidate replacement, backup checking, per-file recovery, or final policy restoration. A damaged backup, bad journal, symlink or unsafe status leads to refusal and retains lockdown.

On an explicitly confirmed mock transaction, cleanup does **not** disrupt a previously validated route.

Two fake external-device sentinels (mikrotik.fixture, nas.fixture) are included in tests and remain byte-for-byte unchanged; this proves that the code does not touch those test files. It is **not** an inspection of real MikroTik SSTP state or NAS configuration.

## Evidence

- 15/15 dedicated Python tests passed, including two added hardening cases for orphan backup and symlinked manifest.
- Real ext4 fixture test on the Raspberry Pi: the isolated process exited with simulated crash code 42 after replacing the candidate configuration; the READY backup and transaction journal survived and a separately invoked process restored the original mock state. The fixture was cleaned up immediately.
- No passwords, real subscription contents, endpoint configuration or NAS data were read or written.
- The existing Mihomo remained healthy; table 100 remained default dev mihomo0. SSTP and NAS were not accessed.

The ext4 test confirms persistent filesystem **program behavior**, not survival through a power failure. It does not require a physical reboot, and cannot validate actual kernel forwarding or nftables rules.

## Next implementation gate

**Do not install a production recovery daemon based solely on this fixture.** Still required:

1. Root-only live storage under a carefully protected local ext4 path, with owner root:root, mode 0700, a protected immutable manifest and verified source/config ownership.
2. A real privileged staging command acquiring awg-maintenance.lock and a separate watchdog lease for the whole switchover.
3. Early systemd boot service that blocks client forwarding before any unconfirmed restoration, verifies both provider and config, and restores production service/transport/routing state.
4. A real, bounded health-check of actual HTTPS and DIRECT endpoint routes, nftables FAIL-CLOSED and table 100 before confirming new configuration.
5. Power-loss testing on a sacrificial stand; supervised Pi reboot on this host only after the independent rollback and known-good backup are proven.
6. No dependency on MikroTik or NAS: do not add scripts or update jobs to either device. Any NAS copy remains out of scope.

Because microSD-write minimization remains a requirement, a production implementation must write persistent recovery data **only during approved reconfigurations**, never during periodic health checks. Heartbeats and noncritical telemetry should stay in RAM.
