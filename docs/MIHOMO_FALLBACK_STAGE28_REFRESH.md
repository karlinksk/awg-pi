# Stage28 — native fallback subscription refresh safety

**Status:** code review and shadow-only proof; NOT production activation.

## Why this is necessary

The legacy `awg-mihomo-configure provider auto-refresh` can stage and automatically promote a candidate provider, then rebuild Mihomo's configuration using its original single-node `select` group. If used unchanged while the **native** `AWG-MIHOMO` fallback group is running, it would remove the standby chain. Changing a subscription's endpoint or credentials could also bypass the approved DIRECT path.

This patch makes the periodic refresh **stage-only** while native fallback is detected. It does not disable provider fetching and does not replace a running transport. The previously installed config, selected node, live provider, service state and transit routes remain unchanged.

## Refresh gate behavior

After `awg-mihomo-update --stage-only` returns a new candidate, `awg-mihomo-fallback-refresh-guard.py` checks the installed group's type and optional marker file `/etc/awg-pbr/transports/mihomo/native-fallback.mode`:

- Valid legacy `select` with no marker (or explicitly set `legacy` marker): preserve existing periodic promotion path.
- Native `fallback` group, or an explicit `native` marker: print `MIHOMO_PROVIDER_AUTO_REFRESH=STAGED_NATIVE_FALLBACK_REVIEW` and `LIVE_PROVIDER=UNCHANGED`; do NOT invoke candidate commit or restart Mihomo.
- Unknown/malformed or unreadable state, invalid marker, or missing guard: `STAGED_REFRESH_GUARD_UNKNOWN`; also do **not** promote.
- Even a `legacy` marker cannot override an actual parsed `fallback` group.
- An explicitly trusted `legacy` marker permits the old legacy path even if the mocked config cannot be parsed. Do not use this marker to silence an actual configuration error.

A separate **read-only** `--audit-direct --iface eth0 --gateway 192.168.112.1` call validates every explicitly selected IPv4 Shadowsocks endpoint with fresh unmarked `ip -4 route get` checks. Exit `10` means native mode with DIRECT pass and review still required; exit `20` means unknown or unsafe. The helper's return codes are **not** interchangeable with ordinary success/failure; callers should interpret the documented values. It never changes production routing.

The stage-only candidate must be reviewed for changed servers, ports, node names, and secrets before any manual promotion. A staged provider is **not** an approved fallback config.

## Verification (2026-10-13 local Raspberry Pi)

- Staged simulated update in native fallback mode retained the live provider, selected node, config and systemd state. The new candidate remained available for review.
- Unknown marker staged safely; fallback group took precedence over a contradictory `legacy` marker.
- Existing legacy AUTO promotion tests remained green; prior rollback test covers failed manual candidate commit and restoration of old config/provider.
- Read-only audit against an isolated fallback candidate with real provider nodes verified both DIRECT routes; wrong gateway was rejected and the private original preview was retained.
- New isolated unit tests cover mode detection, fail-closed unknown markers/config, explicit allowlists, and prevention of recursive routes.

## Remaining deployment gates

This PR **does not turn on native fallback** and does not automatically use an updated subscription. A safe production switch still requires: single source of truth between the selection-monitor opt-in and the native marker; bounded installer transaction with complete backup and rollback; persistent endpoint/DIRECT monitoring that can move the transport to AWG when unsafe; tests of fallback group under live provider updates; careful review and staged approval of changed node credentials and endpoints.

Do not merge this staged PR without its Stage26/27 base and passing CI. Leave MikroTik SSTP untouched.
