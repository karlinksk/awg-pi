# Stage40 — read-only real Pi boot recovery readiness audit

Date: 2026-10-13. **Audit and static test only; no production file, systemd, VPN or MikroTik/NAS modifications.**

## Context and immutable external devices

MikroTik and NAS are independent and must not be configured by AWG Pi Gateway. Existing MikroTik policy is fixed: marked traffic uses SSTP when it is available; if SSTP is unavailable, the already installed MikroTik routing sends marked traffic to Pi. Pi must provide Mihomo → AWG backup and Transit FAIL-CLOSED for that traffic.

## Current read-only findings

The Pi root filesystem is ext4 on /dev/mmcblk0p2 (microSD), /tmp is tmpfs. All tested production services remain active and Mihomo healthy. The proposed root-owned persistent path /var/lib/awg-pbr/native-fallback-recovery is **not present**. A functioning early boot recovery unit named awg-native-fallback-recovery.service is **not installed**.

The actual startup graph includes at least five protected services, not just the three considered in Stage34's deliberately nonworking examples:

1. awg-pbr-setup.service — creates/adjusts nftables, rules and mode baseline.
2. awg-mihomo.service — starts a TUN-backed proxy backend.
3. awg-selection-monitor.service — can choose and switch transports.
4. awg-pbr-health.service — mode-aware health checks; lifecycle has a fail-open stop-post hook that must be audited for Transit behavior.
5. awg-quick@awg0.service — starts the AWG tunnel.

Each must have positive Requires= and After= dependencies on a **working** early recovery unit before unattended boot restoration could be considered. The recovery unit must itself positively enforce fail-closed behavior. Before= alone is insufficient and does not start the required recovery unit.

Read-only Stage40 audit result on the authorized Pi:

- STAGE40_BOOT_READY=NO
- NO_DURABLE_ROOT_RECOVERY
- RECOVERY_UNIT_NOT_INSTALLED
- Both Requires= and After= missing for the five protected units (10 dependency blockers)

## Implemented code and test scope

src/awg-mihomo-stage40-boot-audit.py uses only read-only systemctl show and findmnt commands plus directory metadata. It prints an unambiguous readiness result and blockers. It does **not** invoke sudo, inspect private provider credentials, perform network calls, restart services, write to /etc or /var, or access MikroTik/NAS.

The 8 dedicated tests validate missing unit, missing persistent storage, tmpfs-only storage rejection, missing dependencies, placeholder /usr/bin/false, good dependency fixture, and current host audit.

This is a **prerequisite audit, not a certification of correctness**. A green status would still need real fail-closed packet tests, permissions, reboot-safe recovery, live health, DIRECT route checks and a supervised real Pi reboot.

## Sequence to close the blockers

1. Implement root-owned persistent recovery storage and immutable snapshot/transaction journal, restricting microSD writes to approved maintenance operations.
2. Design a real **separate early boot** root recovery unit with bounded deadline and verifiable nftables FAIL-CLOSED. It must run before forwarding services; a failure should stop dependent Pi forwarding, not send marked traffic DIRECT.
3. Add dependency drop-ins for *all five* protected services, test with systemd-analyze verify and simulated failure/startup ordering before installing.
4. Integrate real shared /run/awg-maintenance.lock and a production transaction coordinator spanning snapshot, config swap, verification and confirmation.
5. Verify source backup and exact restoration, root perms/ownership, effective active transport, policy table100, HTTPS through VPN and DIRECT routes to endpoints.
6. Test failover/rollback under injected faults on a disposable stand. Only then conduct a supervised Pi reboot. At no stage modify MikroTik/NAS.

Native fallback is not enabled in production. Stage40 does not create or enable any systemd unit.
