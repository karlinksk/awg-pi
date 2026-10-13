# Stage29 — runtime native fallback ownership and Transit quarantine

Status: **draft / isolated verification only**. Nothing in this change enables native fallback on an existing gateway.

## Shared authority

The effective runtime mode derives from the **actual Mihomo `AWG-MIHOMO` proxy-group** and the existing optional `native-fallback.mode` marker, using the same read-only `awg-mihomo-fallback-refresh-guard.py` helper introduced in Stage28.

- Healthy legacy `select` is legacy. The historical `AWG_MIHOMO_NATIVE_FALLBACK=1` environment flag remains backward compatible, but conflicts with a proven legacy group are **unsafe**, not permission to switch.
- Native `fallback` must have exactly 2–4 explicitly defined Shadowsocks nodes, IPv4 endpoints, a TUN-enabled runtime configuration, and **every** unmarked endpoint route must be `via ROUTER_IP dev LAN_IF`. Shadow configurations with disabled TUN are correctly rejected by the production monitor.
- Missing/corrupt configuration, invalid marker, failed route verification, or missing helper with native mode enabled yields `NATIVE_UNSAFE`. A literal `legacy` marker cannot conceal a native group or an invalid running config.
- Legacy node failover is suppressed whenever the actual installed group is valid native. AUTO SMART remains an independent `SHADOW_ONLY` observer.

## Fail-closed runtime state machine (opt-in deployment only)

- While the active transport is Mihomo, `awg-selection-monitor` checks the helper once per selection cycle (normal interval 10 s). The result is `LEGACY`, `NATIVE_OK`, or `NATIVE_UNSAFE`.
- `NATIVE_UNSAFE` in **Transit mode**: `awg-transit-routing disable` must first verify nftables' fail-closed forward guard and remove the transport fwmark policy rule. This occurs **without waiting for three regular health failures**. On success the monitor writes a marker in `/run/awg-pbr/native-fallback-quarantine` (volatile RAM state).
- Only after lockdown does it attempt a policy-approved AWG transport selection. Failed AWG activation reasserts lockdown. If Transit lockdown cannot be verified, it does **not** attempt another transport selection.
- When AWG is active but unhealthy, Mihomo is **not** a valid activation candidate unless the guard returns `NATIVE_OK` or a proven legacy selector. This prevents AWG → unsafe Mihomo.
- If the endpoint DIRECT route later recovers while still on Mihomo, the monitor checks `awg-transport check mihomo`, the runtime mode and DIRECT state again; it then calls the existing `awg-transit-routing apply` only **if it had itself recorded a previous quarantine**. Failed reactivation leaves the marker and forwarding quarantined.
- An operator's manually disabled policy without a monitor-owned marker is **not** restored by this code. A successful change to AWG removes the obsolete Mihomo quarantine marker.

**Important timing limitation:** the system detects changes on a periodic sampling schedule. A route can change between samples. Therefore this PR does not prove instantaneous containment of every possible underlay race; a bounded live/reboot drill and root-to-router policy review are required before unattended production deployment. The current runtime monitor writes only its tiny quarantine marker under `/run`, not to microSD.

## Validation on the authorized Raspberry Pi (2026-10-13)

- Existing transport-selection regression suite plus Stage29 mocks pass: controller ownership, lockdown **before** AWG selection, lockdown reassertion on failed AWG selection, no selection on failed lockdown, manual-policy quarantine, pre-activation denial of unsafe AWG → Mihomo, recovery after safe DIRECT, failed recovery keeps lockdown, and absence of automatic restoration after a manual policy shutdown.
- 15 focused Python guard tests confirm native/legacy/malformed handling, route failures, TUN presence and reported monitor state.
- Read-only live provider preflight with a private RAM candidate: `shadowsocks-56693562` and `shadowsocks-27307` passed the DIRECT audit; intentionally wrong gateway was rejected. No actual TUN was brought up by this proof.
- The Stage26 four-network-namespace nftables packet test separately verified that forwarded client traffic does not escape DIRECT when the tunnel path fails.
- All productive SSTP, AWG, Mihomo and table 100 settings are intentionally unchanged.

## Remaining blockers before production

1. **Safe installation transaction** must snapshot service/route/nftables/selection state and preserve SSTP. It must be one-shot, bounded and independently rollback-capable.
2. Runtime native config must be generated with TUN enabled *only after explicit preflight*; the Stage27 preview itself is shadow-only with TUN disabled.
3. Validate that every selected outbound underlay stays DIRECT and that MikroTik forwards it without another VPN. Verify route and nftables recovery, especially across reboot, subscription refresh and failover.
4. Exercise a real supervised end-to-end native fallback → AWG → native fallback recovery under injected endpoint failures; do not substitute mock exit codes for live traffic.
5. Review crash/failure recovery of the monitor itself. The nftables policy and endpoint-path invariants need an independent fail-safe where possible.
6. Do not enable AUTO SMART performance-driven switching or auto-merge these stacked draft PRs before the associated CI and review gates pass.

No private credentials, provider URLs or subscription data are included.
