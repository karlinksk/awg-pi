# ADR — Event-driven router path verification (AWG Pi Gateway v1.3.0)

**Status:** ACCEPTED design decision, 2026-10-12. **Implementation:** PLANNED, not enabled in production.  
**Tracking:** [Issue #83](https://github.com/karlinksk/awg-pi/issues/83), [draft PR #84](https://github.com/karlinksk/awg-pi/pull/84).  
**Scope:** Selective Gateway / MikroTik Transit / Backup VPN, AUTO SMART, Mihomo Hot Standby, AWG fallback and later router adapters.  
**Decision:** **EVENT_DRIVEN** is the default router-attestation policy. RouterOS is optional; the gateway must not depend on a continuously connected RouterOS SSH session.

## 1. Why change from continuous / per-node router audit?

The Pi's `ip route get` only proves the local hop toward the router. The current hAP ax² was audited over existing pinned SSH: a first Pi-specific mangle accept rule and main WAN route give direct egress for tested endpoint IP/port/protocol combinations, notwithstanding a separate SSTP routing table. This policy is comparatively stable; polling the complete RouterOS firewall and route tables every 10–30 seconds would add SSH handshakes, unnecessary CPU/network load and a MikroTik-specific runtime dependency. Those results also cannot replace the *actual service tests* performed through each Mihomo exit.

The prior Stage 8 `30-second` value is an **endpoint attestation freshness limit**, not a proposed SSH polling interval.

## 2. Accepted policy

- `router_verification_mode = event_driven` (default): establish an optional **baseline policy audit** at initial setup, at authorized network reconfiguration, or after a material change; then do **local** Pi route and service checks while idle. No repeating full RouterOS polls for every candidate.
- `router_verification_mode = strict` (opt-in): re-attest the exact node endpoint at every proposed automatic switch; never imply that even strict snapshots prove future RouterOS policy changes impossible.
- `router_verification_mode = unmanaged` (portable fallback): there is no router API/SSH dependency. A Pi-local check may show `DIRECT_LOCAL_UNVERIFIED`. Administrators may explicitly allow *assumed* local/direct underlay, labelled `ADMIN_TRUSTED_UNVERIFIED`, but the software must **never** represent this as `router_verified=True` or assert end-to-end guaranteed DIRECT. Unmanaged deployments need a separate explicit risk acceptance before automatic promotion when router bypass is required.

**MikroTik is an adapter, NOT a core requirement.** Support other router-specific adapters later, and allow generic routers without configuring RouterOS at all. Installer should offer event-driven verification if an appropriate adapter/credentials exist, otherwise explain the portable/trust policy. No new SSH users or broader permissions are automatically created.

## 3. Distinct levels of evidence

1. **Baseline router policy**, e.g. accepted ingress rule order, main FIB/WAN, relevant NAT, rule/VRF/IPsec constraints. Bound to boot identity/router identity, LAN config, effective policy fingerprint and an epoch; keep state in `/run` where practical. It is **not** a time-independent authorization for a particular node or proof that off-box rules never change.
2. **Local candidate route**: `ip -4 route get`, interface, source IP, gateway and actual dialled `endpoint IP + TCP/UDP port`. Cheap local query, before/after candidate qualification; never confuse `eth0 -> router` with verified direct WAN.
3. **Service qualification**: actual independent Mihomo exit check, with explicit ChatGPT+YouTube result and freshness; proxy transit may be DIRECT or ASSISTED and must be identified. API reachability and YouTube SABR metadata alone do not qualify playback.
4. **Short-lived endpoint attestation**: read-only router-adapter proof for the *actual* candidate tuple and source/routing class, with 30-second TTL initially and independently rechecked by the single switching owner when needed. An unsigned JSON cache/digest is **not** trustworthy switch authorization.

Each item has its own provenance, timestamp, validity and invalidation reason. Do not silently promote a local or administrative assumption to a verified RouterOS proof.

## 4. Event triggers and invalidation

A policy-verification event is generated for:
- installation or explicit change of gateway mode / router adapter, LAN interface, Pi address, netmask, gateway, or route configuration;
- Pi or router **known** reboot / link, network, DHCP or default-route change; loss/restoration of the LAN gateway; change in Pi interface/route or policy-routing state relevant to endpoints;
- detected RouterOS policy/configuration epoch or fingerprint change, if supported by a future read-only event subscription/push mechanism;
- active candidate's *actual dialled IP, TCP/UDP port or provider content hash* changing, node-protocol/chain policy changed, or new previously unseen endpoint;
- an automatic switch request when a required proof is absent, mismatched, invalidated, or expired;
- manual `verify-now` / troubleshooting / suspected leak incident.

**Important limitation:** Out-of-band RouterOS edits cannot necessarily be detected from Pi without a notification mechanism or fresh SSH audit. Accordingly EVENT_DRIVEN never claims permanent proof. Before a critical auto-switch requiring verified DIRECT, a cached baseline alone is insufficient: perform the short read-only attestation if no **currently valid exact-endpoint proof** is available. This may be one SSH connection per *rare switching event*, not one per 10-second health-check. Optional infrequent auditing, e.g. daily, may be user-configured for earlier drift detection but is **OFF by default**, not a requirement.

An endpoint observation is discarded immediately on relevant source/route change even if its 30-second TTL has not elapsed. A known router reboot/config drift invalidates all dependent proofs.

## 5. Event-driven control flow

```text
INSTALL / RECONFIGURE / NETWORK EVENT
  -> validate local LAN and adapter availability
  -> optional read-only router baseline audit, cache result in RAM
  -> invalidate affected endpoint proofs

IDLE / EVERYDAY MONITORING
  -> local route + small active-service checks only
  -> Hot Standby probes only via each isolated Mihomo candidate
  -> no regular SSH connection to MikroTik

SUGGESTED AUTOMATIC NODE / TRANSPORT SWITCH
  -> sole existing selector holds separate action gate
  -> confirm AUTO policy and fresh required ChatGPT+YouTube evidence
  -> match actual dialled endpoint (IPv4 + port + TCP/UDP + chain)
  -> verify Pi local route and endpoint identity
  -> if DIRECT proof required AND exact-endpoint attestation missing/stale:
       trigger one bounded read-only router adapter audit immediately
  -> if attestation unequivocally passes: proceed to transport preflight
  -> otherwise: block unverified automatic promotion; preserve guard
  -> apply only via existing transaction owner, check real data plane
  -> postflight or rollback; Transit must remain FAIL-CLOSED

MANUAL MODE
  -> do not override manually selected transport/node
```

The new adapter MUST NOT hold `/run/awg-maintenance.lock` while calling `awg-transport select`, because that command acquires the lock itself. The existing transport selector remains the only writer. The router verification component never executes changes on MikroTik.

## 6. Failure behavior

- No SSH credentials, unsupported router, network outage or timeout: emit `UNKNOWN` / `ROUTER_UNAVAILABLE`, not fabricated DIRECT; continue non-routing service diagnostics. Generic mode is usable without a router adapter with transparently reduced confidence.
- Strict or event-driven verified-DIRECT requirement unmet during proposed promotion: **block the new candidate**, do not send protected Transit traffic DIRECT, and do not disrupt the priority SSTP management path.
- No working, qualified transport: record `NO_WORKING_TRANSPORT` **as supervisor state**, not as an AWG transport ID; retain required Transit FAIL-CLOSED protection. Preserve Selective FAIL-OPEN semantics where configured.
- Router event processing must be debounced, bounded with timeouts, have non-durable RAM counters, and never hammer SSH during outages. Provider API keys, SSH identities, subscription contents and private configuration must never enter logs/PR.
- If the user explicitly elects a portable router-unverified policy, mark results distinctly, document the weaker leakage guarantees, and do not silently weaken an existing strict/verified-DIRECT installation.

## 7. Resource budget and acceptance tests

- Idle RouterOS SSH queries: **zero**. No periodic RouterOS timer is required.
- Local `ip route get`: per inspected candidate and pre/post switch as needed; cheap local operation.
- RouterOS SSH: on initialization/material event, and at most one bounded, batched audit per group of candidates when genuinely required. A group may include up to 20 IP/port/protocol tuples, per existing Stage 8 attestor.
- Implement a short event coalescing interval and bounded retry/backoff; avoid accumulating microSD writes (RAM snapshots and logs).
- Verify RouterOS primary SSTP remains untouched, current gateway unaffected, and no DNS/DIRECT leak across transitions.
- Tests required: boot, LAN move, router policy drift, stale baseline, candidate IP change, hostname-to-new-IP, port/protocol change, successful cached proof, event-coalescing, SSH unreachable/timeout, fresh attestation at switch, manual policy, generic router, deliberate admin-trust mode, Transit FAIL-CLOSED and Selective FAIL-OPEN.

**Acceptance and implementation are distinct.** This ADR is authoritative for the rollout plan but does **not** activate a router watcher, attest candidates, install a service, or authorize automatic switching.

## 8. Revised implementation sequence

1. Record policy enum / router-adapter interface, distinguish baseline vs endpoint proofs and explicit unmanaged trust; update installer, CLI/TUI plan **without changing current working behavior**.
2. Add local event detection + deduplication, baseline cache invalidation, optional read-only RouterOS baseline adapter and batched on-demand route proof. Avoid continuous SSH polling.
3. Bind actual Mihomo socket/dialler endpoint IP+port+protocol/provider hash to proof, including FQDN updates and proxy-chain cases; prevent stale/forged evidence becoming permissions.
4. Integrate on-demand commit-time re-attestation with the existing **single** selection-monitor transaction owner; separately prove maintenance-lock order, rollback, and no DIRECT leak.
5. Validate actual ChatGPT web access / YouTube SABR media playback and Hot Standby on real nodes; run controlled outage/flap/double-failure/return trials with time-to-recover P50/P95 and Pi CPU/RAM/traffic/microSD measurements.
6. Confirm across MikroTik and a router-agnostic test fixture, repair Mihomo subscription-refresh failures, complete the v1.3.0 release gate, then separately consider merging PR #84.

**Supersedes any earlier wording that implied SSH polling every 30 seconds or mandatory per-node full RouterOS audits.**
