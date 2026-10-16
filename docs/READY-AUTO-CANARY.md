# READY-priority AUTO canary (v1.3.0 — review only)

This is an opt-in prototype, **not enabled by installation**. The active AUTO / Mihomo / AWG / MikroTik / SSTP setup is unchanged.

## Safety contract

- `MIHOMO_READY_AUTO_CANARY=0` is the default; existing failover output and order are preserved.
- When set to `1`, a READY candidate from the continuity Hot Pool is considered before ordinary health-pool fallback.
- An archived/staged profile is **not** selectable just because it is READY. The exact node name must exist uniquely in the live provider and **all transport parameters (including credentials)** must equal the union provider entry.
- Existing isolated ChatGPT/OpenAI plus YouTube video service-scan remains required (`balanced` or `require` mode); no browser-level ChatGPT success is claimed.
- Post-activation checker must be configured and executable, otherwise canary refuses to act.
- Confirmed failed READY activation/post-check quarantines the shared endpoint (including aliases). A failed post-check attempts a return to the previous node. A failed rollback stops attempts and reports failure to the transport monitor so AWG/FAIL-CLOSED policies remain responsible.
- Emit exactly `MIHOMO_NODE_FAILOVER=OLD->NEW` on stdout when successful; monitor depends on this exact contract.

## Read-only postcheck limitations

`awg-mihomo-ready-postcheck-tun` checks node identity, interface UP, table 100, marked route, public IPv4 egress using `curl --interface mihomo0`, and OpenAI API HTTP 401 (unauthorized, not region denial).

**This checks Pi-bound TUN traffic, not a LAN client's forwarded TUN dataplane.** A controlled real-client end-to-end canary, transport fallback and independent rollback are required before production enablement. It does not redo the 24-frame YouTube decode; isolated candidate service-scan provides that evidence. The historic HTTP-only YouTube precheck is not restored.

## Validation performed on Pi, 2026-10-16

- 11 isolated selector/identity tests PASS, including default-off behavior, READY priority, missing READY, changed credentials, activation failure, quarantine, postcheck failure, rollback failure and exact selection-monitor stdout.
- 6 mock route/TUN postcheck tests PASS; one real read-only run on current Mihomo node PASS for Pi-bound TUN and API HTTP 401.
- Pre-existing Hot Pool and provider-continuity tests passed separately.
- Production binaries, services, routes and RouterOS were not modified by this canary.

## Open acceptance gates

1. Validate service test before/after change and confirmed client-forwarded TUN path through a controlled LAN client.
2. Failure injection: same-endpoint alias quarantine, primary rollback, AWG fallback and FAIL-CLOSED while SSTP management stays reachable.
3. Installer integration, unprivileged mocks on CI, reboot, migration and documentation review.
4. Merge dependencies (especially service-eligibility PR #106, Hot Pool PRs #108/#110 and safe periodic update PR #109).

Do not activate unattended AUTO based on this draft.

[executed on device: awg-upgrade (7ff7c792-9f11-48ea-9b09-8734178c247a)]