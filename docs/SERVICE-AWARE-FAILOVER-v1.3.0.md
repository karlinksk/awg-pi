# Service-Aware AUTO SMART / Hot Standby — staged implementation (v1.3.0)

**Tracking:** #83, draft PR #84. **Experimental: NO production install, auto-switches or background timer are activated.**

## Shared eligibility and limits

`src/awg-mihomo-limits.py` is the single source for **10 shortlisted candidates → up to 3 sustained-speed finalists → up to 2 confirmations**. Both AUTO SMART and Hot Standby import these caps.

The previously Pi-local AUTO SMART is versioned as `src/awg-mihomo-smart`. It creates a short-lived, isolated, loopback-only Mihomo (no TUN and no route changes). Service eligibility is verified **before** expensive speed tests and recommendations.

`src/awg-mihomo-service-check.py` checks through the specifically selected loopback proxy:
- OpenAI API: unauthed HTTP 401 suggests the API responds from that IP; `unsupported_country_region_territory` is a definite failure.
- ChatGPT web: constrained HTTPS origin, HTML and challenge detection. HTTP 403 / unrecognizable content is **UNKNOWN**, not success.
- YouTube: actual watch page **and byte-range video data from a validated `*.googlevideo.com` HTTPS destination**. Homepage alone is insufficient. An unsupported player cipher yields UNKNOWN.
- Only all-PASS qualifies. Network errors, anti-bot challenges and ambiguous results stay UNKNOWN. Proxy bypass with `NO_PROXY=*` is blocked. Redirects to non-whitelisted hosts are rejected *before* connection, not only after they happen.

These are conservative probes, **not a guarantee that a logged-in browser session will function**. Testing actual client browsing is still necessary.

## Stage 2: read-only rolling Hot Standby

`src/awg-mihomo-standby.py` builds rolling windows of up to ten unique healthy candidates from the existing pool and reads provider nodes only inside its isolated probe process. It *never* calls live node selection, transport selection, routing or systemctl.

- Candidate windows advance beyond the first ten; up to two previous PASS-qualified warm candidates remain prioritized.
- No traffic benchmark is performed in these cycles; sustained throughput tests remain a separate, infrequent AUTO SMART activity.
- State is written atomically, mode 0600, to `/run/awg-pbr/mihomo-standby/state.json` (RAM on Debian). Cache entries carry endpoint+protocol+egress fingerprint, provider checksum, effective region/protocol policy, checked_at and reason codes. Invalid/stale/UNKNOWN entries are never offered as warm.
- Single-writer file lock prevents simultaneous scans; short-lived probe config with credentials lives in `/dev/shm` with 0600 permissions.
- Adaptive scan interval is **suggested only** (degraded 30 s, stable 120 s, bounded exponential backoff to 600 s), not currently scheduled.
- `show` filters expired cached successes and does **not** authorize routing changes; the production selector must verify live source hash/TTL and do a post-switch data-plane check.

**No standby timer/systemd integration is installed or enabled yet.** Running `scan` against actual credentials needs explicit root permission and production-like network testing in a controlled environment.

## Stage 2: pure failover decision model

`src/awg-failover-policy.py` has a side-effect-free state machine, with tests covering Mihomo main → hot spare → AWG backup, AWG → Mihomo auto-failback, double outage `NO_WORKING_TRANSPORT`, strict Manual/FIXED preservation, confirmed failure vs UNKNOWN, and no fictitious repeated confirmations from one cached probe result.

- Two **distinct** confirmed failures trigger emergency recovery. A single UNKNOWN or stale result cannot trigger global failover.
- AWG is usable as a fallback only when independently service-qualified for ChatGPT and YouTube.
- Auto-failback to priority Mihomo requires two **new** PASS observations plus 120 s dwell (tunable once integrated). Emergency recovery ignores plan-switch dwell.
- `NO_WORKING_TRANSPORT` remains **supervisor state**, never a new value in the existing `AWG_TRANSPORT_FILE`.
- The model tracks monotonic detection and recovery durations; **time-to-recover has not been measured in real-world failover**.
- **IMPORTANT:** `evaluate()` returns *suggested actions only*. No switch is executed. A future adapter must recheck TTL, route, client DNS and safety preflight, serialize operations with the existing maintenance lock, and commit with rollback.

## Offline verification

In a fresh GitHub branch checkout on Pi RAM, 2026-10-12:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -q
# 60 tests, OK
```

Existing repository CI also now runs these tests on PRs; the external runner result must be confirmed separately.

## Unfinished release-blocking work

1. Secure a robust, low-cost method for authenticating actual ChatGPT and YouTube media access on varied provider nodes, without false PASS during WAF/challenge and without relying on a fixed video stream format.
2. Wire a **separate, opt-in, resource-bounded service probe timer** that continues even if `awg-mihomo.service` is stopped under AWG, validates candidate endpoints and refreshes RAM.
3. Implement a read-only service probe **through AWG** with no DIRECT fallback, and independent rapid active-node reachability checks.
4. Connect results to the **single existing selector** (and its `/run/awg-maintenance.lock`), support safe conditional failback and publish CLI/TUI diagnostics; do not allow AUTO SMART to switch anything.
5. Preflight + post-switch checks using the **actual data plane**, rollback, double-failure recovery, Selective FAIL-OPEN/Transit FAIL-CLOSED and actual MikroTik transit leakage tests without disrupting SSTP.
6. Implement bounded diagnostics and real metric retention (P50/P95 time-to-detect/recover, false switches, probe CPU/RAM/network/microSD) with sanitization, then fault-injection and controlled field trials.
7. Fix the separate failed `awg-mihomo-update.service` subscription refresh and assess provider cache freshness before acceptance.

**Never enable automatic transport/node selection using these prototypes without completing the integration and fail-closed test plan.**
