# Stage41 — Full five-service systemd boot-order contract (design-only)

Date: 2026-10-13. **NOT INSTALLED, no service restarts or productive configuration changes.**

Stage40 read-only Pi audit established that production recovery was not yet available, and that five systemd services could otherwise initialize VPN/forwarding before an unconfirmed native-fallback transaction was restored.

## Five consumer services in the proposed ordering

- awg-pbr-setup.service
- awg-mihomo.service
- awg-selection-monitor.service
- awg-pbr-health.service
- awg-quick@awg0.service

All **five** must positively depend on a verified early recovery unit through `Requires=awg-native-fallback-recovery.service` and `After=awg-native-fallback-recovery.service` before unattended recovery is installed.

The example early recovery unit is ordered after local filesystems, requires the root-owned local recovery mount, and declares Before= for the protected units. It deliberately sets `ExecStart=/usr/bin/false` and has **no enabling section**; installing this example would block the dependent services and is prohibited. It exists to validate syntax and dependency design only, not to execute rollback.

Static checks: six Stage41 focused tests cover all five required/after links, early mount/order, deliberately nonfunctional recovery executor, systemd syntax, and absence of service/network mutation commands. `systemd-analyze verify` passed.

## External appliances remain immutable

MikroTik and NAS must not be changed. MikroTik's existing fixed policy forwards marked traffic via SSTP when SSTP is available, and to Pi otherwise. Pi's responsibility is its own Mihomo → AWG failover and transit FAIL-CLOSED. The boot recovery design has **no dependency on MikroTik or NAS health**.

## Incomplete production prerequisites

Even a correct dependency graph is not proof of working rollback. A real root-owned executable must:

1. Check an unconfirmed persistent journal before clients can use Pi forwarding.
2. Positively enforce and verify a real nftables transit FAIL-CLOSED guard before reading or changing live config; errors must prevent protected service startup.
3. Validate protected READY backup and restore the full config/provider/policy/transport state under the shared awg-maintenance.lock.
4. Recover the service state, validate direct endpoint routes, authenticated HTTPS egress and active policy rules, and only then permit protected transit forwarding.
5. Hold a bounded confirmation lease independent of the initiating process, with reboot-safe journal metadata, and retain the old recovery snapshot until the new state is confirmed.
6. Be tested with real packet forwarding and supervised restart/reboot on a disposable stand before this Pi is modified.

**These gates remain unsatisfied. Do not install the Stage41 examples in systemd.**
