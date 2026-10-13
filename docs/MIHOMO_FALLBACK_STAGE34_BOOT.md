# Stage34: Early-boot recovery ordering and SSTP independence

**Date:** 2026-10-13. **STATUS: isolated fixture and systemd design examples ONLY.** This stage neither installs a production recovery daemon nor reboots the Raspberry Pi.

## 1. Architectural decision: SSTP is owned by MikroTik

The user clarified that the active SSTP link is established and maintained by MikroTik directly to the cloud MikroTik, **independently of Raspberry Pi**. This is documented as a project invariant in docs/SSTP_INDEPENDENCE.md.

Changes to Pi (Mihomo, AWG, reboot, native fallback rollback) must neither reconfigure nor disconnect the SSTP link. Failure of Pi may affect client destinations routed via Pi, but **is not itself a failure of SSTP**. Any future change to MikroTik routes should independently verify the underlay and absence of a Pi-dependent SSTP server route. Stage34 never runs commands against MikroTik.

## 2. Read-only storage inspection

The authorized Pi currently has one mounted local persistent root filesystem on **/dev/mmcblk0p2 ext4** (microSD), while /tmp is tmpfs and zram0 is RAM swap. No NAS volume was mounted on the Pi during inspection.

Implications:
- An early-boot recovery snapshot must be **local**. A NAS-only snapshot is not sufficient because NAS availability depends on network startup.
- A future protected path such as /var/lib/awg-pbr/native-fallback-recovery is a proposed root-only directory on local persistent storage, **NOT presently created or populated by this stage**.
- Minimize microSD writes: one protected snapshot and journal when a supervised activation happens; no 10-second/periodic writes to microSD. Heartbeats and counters stay in /run tmpfs.
- Secrets and provider subscription are root-owned 0600 backups in a 0700 directory; never commit or print any content.
- Real durability depends on an appropriate filesystem, correct ownership, fsync of files AND directories, and power-loss testing on a sacrificial nonproduction stand.

## 3. Stage34 fixture boot gate

The new src/awg-mihomo-stage34-boot-gate-fixture.py composes the existing Stage31 transaction journal, Stage32 pending lease, and Stage33 published READY backup. It accepts **only** a private user-owned fixture directory under /tmp tmpfs. It cannot operate on /etc, /var, root directories, actual VPN service or MikroTik.

When the mock journal indicates an unconfirmed change, the boot gate:
1. Writes the mock Transit state to lockdown before accepting/restoring any backup.
2. Requires a Stage33 backup with READY published last, full hash manifest, and known-good legacy service, transport and DIRECT assertions.
3. Restores the six mock configuration/service/routing items with atomic file+directory fsync, keeping Transit locked during configuration restoration.
4. Restores mock Transit forwarding **last**, then clears the pending journal.
5. If backup is incomplete, corrupted, missing or semantically unsafe, preserves lockdown and keeps recovery information for investigation.
6. Permits repeated recovery after simulated crashes during quarantine, validation, per-file restore and policy recovery.
7. Leaves a synthetic mikrotik-sstp.fixture sentinel byte-identical at all times. This proves **test-code noninterference only**, not actual RouterOS SSTP connectivity.

If a transaction journal is already confirmed, it completes interrupted cleanup rather than rolling back an accepted config.

## 4. Example early systemd ordering

The examples/stage34-boot-only directory provides one intentionally nonfunctional unit and three drop-ins:

- awg-stage34-boot-recovery.service has DefaultDependencies=no, After=local-fs.target, RequiresMountsFor pointing to the proposed local recovery directory, and Before=awg-pbr-setup, awg-mihomo and awg-selection-monitor.
- Each protected consumer has Requires= and After= on the recovery unit. Before= alone does not force the recovery unit to run; **the Requires= and After= dependencies are essential**.
- The sample unit has ExecStart=/usr/bin/false, no [Install] section and is NOT included in the installer. It is deliberately **not operational** to prevent mistaken production use. The sample must never be installed unmodified.

A future real root-only service must positively verify the recovery journal and nftables FAIL-CLOSED before permitting protected forwarding; failure to verify **must block dependent Pi forwarding** rather than switch clients to DIRECT. Recovery of Pi is independent of MikroTik's own SSTP connection.

## 5. Tests and remaining production gates

Stage34 runs isolated fault-injection tests: restartable early boot rollback, corrupted Stage33 backups, invalid journal quarantine, partial restore, pre-commit interruption, confirmed cleanup and unchanged SSTP sentinel. The sample unit/drop-ins are validated with systemd-analyze verify and static dependency tests.

**Not yet proven or installed:** a real root-owned persistent snapshot, actual early-boot root recovery daemon, dependency startup behavior on Pi at reboot, physical power loss, complete rollback of live nftables/route/service state, or supervised failover of real traffic.

The next gate is an independently reviewed **production-grade** recovery implementation and a supervised live validation plan. Do not conflate CI success with authorization to enable native fallback.
