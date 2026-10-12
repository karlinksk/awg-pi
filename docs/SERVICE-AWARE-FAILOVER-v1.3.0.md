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
- Adaptive scheduling is implemented in the independent **watch** loop (degraded 30 s, stable 120 s, bounded exponential backoff to 600 s), and is shortened when a warm result approaches TTL expiry. It has **not** been deployed or activated on Pi.
- `show` filters expired cached successes and does **not** authorize routing changes; the production selector must verify live source hash/TTL and do a post-switch data-plane check.

An optional **staged** `units/awg-mihomo-standby.service` runs the independent read-only `watch` loop without depending on the main `awg-mihomo.service`. **Neither the unit nor the watcher has been installed or enabled on Pi.** Running a real scan needs explicit root permission and production-like network testing in a controlled environment.

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
# 63 tests, OK
```

Existing repository CI also now runs these tests on PRs; the external runner result must be confirmed separately. The new optional standby service file is NOT installed by `install.sh`.

## Unfinished release-blocking work

1. Secure a robust, low-cost method for authenticating actual ChatGPT and YouTube media access on varied provider nodes, without false PASS during WAF/challenge and without relying on a fixed video stream format.
2. Validate and integrate the staged **independent read-only standby systemd service** and resource limits that continue even if `awg-mihomo.service` is stopped under AWG. Its real scheduling and safety behavior remain untested on actual subscription nodes.
3. Implement a read-only service probe **through AWG** with no DIRECT fallback, and independent rapid active-node reachability checks.
4. Connect results to the **single existing selector** (and its `/run/awg-maintenance.lock`), support safe conditional failback and publish CLI/TUI diagnostics; do not allow AUTO SMART to switch anything.
5. Preflight + post-switch checks using the **actual data plane**, rollback, double-failure recovery, Selective FAIL-OPEN/Transit FAIL-CLOSED and actual MikroTik transit leakage tests without disrupting SSTP.
6. Implement bounded diagnostics and real metric retention (P50/P95 time-to-detect/recover, false switches, probe CPU/RAM/network/microSD) with sanitization, then fault-injection and controlled field trials.
7. Fix the separate failed `awg-mihomo-update.service` subscription refresh and assess provider cache freshness before acceptance.

**Never enable automatic transport/node selection using these prototypes without completing the integration and fail-closed test plan.**



## Stage 3: AWG-only service proof and passive decision adapter

New source files:

- `src/awg-service-probe.py`: read-only service checks via an explicitly named `awgN` tunnel. Outbound IPv4 TCP sockets are bound using `SO_BINDTODEVICE` **before** connecting; DNS is obtained by authenticated HTTPS requests to pinned resolver addresses over the same interface. The standard local resolver, environment HTTP proxies, production TUN selection, route updates and DIRECT fallback are never used. Only approved hosts, validated public IPv4 responses and bounded HTTPS redirects are allowed. Any unresolvable DNS, missing interface, HTTP challenge or unqualified media yields **UNKNOWN**, not a fabricated PASS. The interface allow-list rejects physical interfaces such as `eth0`.
- `src/awg-service-observer.py`: **strictly DRY_RUN_ONLY** evaluation of independent Mihomo, AWG and Hot Standby JSON evidence using the existing pure `awg-failover-policy.py`. Invalidated by TTL, sample ID replay, provider hash mismatch, wrong active node identity, missing three service checks or wrong transport; does not run `awg-transport select`, `awg-mihomo-configure`, `ip`, `systemctl` or `nft`. Current live AWG can be selected for recovery only when evidence says both required services really pass.
- Hot Standby evidence now carries independently collected `sample_id`, `identity`, `checked_at` and sanitized per-service `checks`. During active AWG service, prospective Mihomo health comes **only** from a validated *standby* node's current evidence, never from the stopped or previously active Mihomo service.
- `src/awg-mihomo-service-check.py` can output `transport=mihomo`, an explicit node `--identity` and a new per-run sample identifier, for future active-node integration.

AWG observation is deliberately conservative: DoH to the pinned resolvers may not work on every AWG provider, and the current YouTube media extraction can return UNKNOWN for signature-cipher formats. The AWG checker cannot be called a proven live health-check until tested against actual traffic under the current tunnel and service rules. **Do not deploy as a production selector**, and do not introduce a DIRECT fallback to 'make the probe pass.'

The observer currently evaluates **explicit evidence snapshots** (fixture JSON via `--snapshot`) rather than wiring itself to the existing `awg-selection-monitor`. This preserves the legacy monitor as the sole production switch owner while transaction-safe action execution, actual data-plane verification, rollback and no-leak regression are built.

### Stage 3 verification

On the Pi's temporary checkout, **91 offline Python tests** passed; the additional tests cover AWG-bound socket ordering, DNS-over-HTTPS forced through AWG, rejection of unsafe DNS/redirects, fresh service evidence identity, cache replays, AWG-active Mihomo recovery, double failure and strict Manual/FIXED policy preservation.

No real AWG node was switched and no new systemd unit was enabled. Running tests does **not** validate recovery-time P50/P95 on a real link.

Remaining blockers: controlled live read-only probe against AWG; opt-in AWG health evidence publishing in RAM; robust YouTube video confirmation; cloud-protected ChatGPT classification; action adapter attached to the existing locked selector with data-plane post-check and rollback; rigorous Transit FAIL-CLOSED/Selective FAIL-OPEN and SSTP independence tests; existing failed provider update service.


## Stage 3b: opt-in, read-only advisory hook in the legacy selector

The existing `src/awg-selection-monitor` now supports an optional observer subcycle, **disabled by default** with `AWG_ADVISORY_ENABLED=0`. It reads a separately generated evidence snapshot (default `/run/awg-pbr/service-observation.json`) only when explicitly enabled; it calls the dry-run Python observer with a short timeout, publishes the advisory result and counters **only under `/run/awg-pbr/service-advisory/`**, and never passes the advice to `awg-transport select` or the node selector.

The observer's replay/failure counters are tied to the system boot ID, provider hash, active node and transport, and selection policy. A reboot or policy/node change invalidates that state. Malformed/stale/misattributed cache evidence remains UNKNOWN. The callback is skipped while the existing maintenance lock is held. Advisor failures are isolated: the existing transport selection logic continues unchanged.

**This is not a production rollout instruction.** Neither the probe result producer nor the optional observer setting is configured on the live Pi. Do not enable this on production until service evidence workers and the end-to-end security tests are ready. The real production selector still uses the preexisting generic health-based switching.

Regression: `bash tests/test-selection-advisory.sh` proves default-disabled, advisory enabled but no switch, and failing observer with no impact on healthy current transport. The full Python suite has **94 offline tests**. GitHub CI runs both suites.

### Production integration and release criteria still pending

- A protected real evidence producer for both active Mihomo and AWG (currently proof modules are manually invokable prototypes).
- Isolated, resource-bounded live AWG/Hot Standby field tests.
- A single serialized switching executor in the legacy selector with preflight, transaction rollback and real forwarded data-plane postvalidation (not advisory-only).
- Double-outage handling in the forwarding plane, Selective FAIL-OPEN and Transit FAIL-CLOSED regression, safe MikroTik/SSTP boundaries.
- Duration P50/P95, microSD/noisy probes monitoring, paid/free subscription update failure recovery, and UI controls.
