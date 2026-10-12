# Service-Aware AUTO SMART / Hot Standby — staged implementation (v1.3.0)

**Tracking:** #83, draft PR #84. **Experimental: NO production install, auto-switches or background timer are activated.**

**Accepted routing-policy decision (2026-10-12):** [Event-driven router path verification ADR](ADR-EVENT-DRIVEN-ROUTER-ATTESTATION-v1.3.0.md). **EVENT_DRIVEN is the default**: verify the router on initial setup/material network changes and when a proposed switch lacks a fresh, exact-endpoint proof. No constant MikroTik SSH polling; RouterOS is an optional adapter. A 30-second endpoint proof TTL is **not** a 30-second scan period. The ADR supersedes any earlier wording interpreted as mandatory unconditional SSH per candidate or every fixed interval. Not deployed.


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


## Stage 4: read-only evidence producer (staged, disabled)

`src/awg-service-evidence.py` now creates a **sanitized evidence snapshot** for the existing optional advisory hook; it does not change transport, node, route, nftables, DNS or systemd. It reads the protected runtime selection + node policy, verifies the provider digest against the pool snapshot and performs bounded, individually attributed service checks:

- When main = Mihomo, probe the current node via the localhost Mihomo proxy using its exact node identity.
- Always probe `awg0` via the interface-bound AWG HTTPS checker **if awg0 exists**, independently of the current production transport.
- When main = AWG, **do not connect to the stopped production Mihomo**; use the independent Hot Standby cache, subject to provider identity/freshness checks by the observer.
- If evidence cannot be read or the check times out, emit `UNKNOWN`, never a fabricated PASS. Invalid response bodies, claimed PASS contradicted by per-service checks, misattributed node names, old sample IDs and raw secret fields are stripped or rejected.
- Only an atomic mode-0600 JSON file `/run/awg-pbr/service-evidence/snapshot.json` is written. Console summary exposes service statuses only, not provider URLs, tokens or private keys.

`units/awg-service-evidence.service` and `units/awg-service-evidence.timer` are **staged files only**: bounded execution time, CPU/RAM limits and a restricted writable `/run/awg-pbr/service-evidence/` directory. The timer is never persistent and is **not deployed/enabled**. The old monitor's optional advisory snapshot path has been updated to match the dedicated RAM directory; `AWG_ADVISORY_ENABLED` continues defaulting to `0`. No automatic failover executor is installed.

**Live, read-only probes, 2026-10-12:** while production `mihomo0` remained active, `awg0` handshake was fresh and direct interface binding routed DNS and TLS through AWG. OpenAI API on AWG returned expected unauthenticated HTTP 401 (API reachable), ChatGPT website responded HTTP 403 (WAF/region cannot be distinguished by this probe), and YouTube watch endpoint responded but the probe could not verify video media bytes. Final AWG service eligibility = `UNKNOWN`. Separately the current production Mihomo exit returned OpenAI `unsupported_country_region_territory` (service `FAIL`), despite generic Mihomo transport health = healthy. **Do not activate failover based on these incomplete proofs.**

Local offline testing increased to **109 Python tests** plus three advisory shell regression checks; a simulated two-probe Mihomo FAIL with AWG PASS produced an advisory recommendation to switch, but an AWG FAIL caused `NO_WORKING_TRANSPORT`. These are recommendations only, with no switching capability.

### Outstanding safety and release gates

1. Ensure stable, low-overhead playback-capable YouTube check and ChatGPT browser-vs-WAF interpretation; treat ambiguous checks as UNKNOWN without turning them into a global outage.
2. Validate actual standby worker on real subscription nodes under resource/sandbox limits before enabling the staged systemd units.
3. Add deployment/rollback only after validating observer evidence producer and existing selector lock semantics on isolated fault-injection rigs.
4. Build and test the transaction-safe single-owner switch executor with correct endpoint DIRECT exceptions, data-plane postflight, precise rollback and no-leak semantics for both Transit/Selective.
5. Fix the separate provider updater service failure, then confirm full pipeline and P50/P95 recovery without touching MikroTik's primary SSTP.


## Stage 5: fast active-region sensor and fail-closed transaction model

**No production switch functionality was enabled or deployed.** The files below are staging-only and not in the current Pi installer.

### Lightweight event detection (no heavyweight speed test)

`src/awg-fast-service.py` checks only the OpenAI region/API response through the **already selected** Mihomo loopback HTTP proxy, retaining each probe's node identity and unique sample id. `REGION_BLOCKED` is emitted for the explicit API country-block error; `API_REGION_OK` for the unauthenticated 401; all other responses are UNKNOWN. **API_REGION_OK is NOT ChatGPT+YouTube service eligibility.**

Two separate consecutive regional blocks are required before an `urgent_service_confirmation=true` advisory is published. A change of selected node, boot ID, explicit API pass or UNKNOWN invalidates the consecutive-block streak. If production Mihomo is not active, the detector skips the request. The file is atomic and restricted to `/run/awg-pbr/service-fast/active.json`, no disk log or route modification.

The proposed watch cadence is about 10 s after a clear region-block and 20 s in an ordinary region-OK state, with bounded backoff on UNKNOWN. These are **advisory polling intervals**, not proof of 30–45 s failover. `units/awg-fast-service.service` stages an independent systemd watcher with read-only system filesystem and restricted RAM output; **the service is not installed or enabled**.

A read-only field test through the currently active local Mihomo `127.0.0.1:7890` confirmed `REGION_BLOCKED/openai_unsupported_region`; the active route remained `table 100 → mihomo0`. The sensor does not try to adjudicate browser WAF or YouTube media delivery on its own.

### Transaction design without production powers

`src/awg-switch-transaction.py` is a **pure test executor with an injected mock backend**, not an implementation that can invoke `awg-transport select`, change a selected node, or modify nftables/routing.

Its independent authorization checks:
- AUTO selection policy only, current backend/node still matching the observed state, fresh evidence snapshot, and safe current routing guard.
- Only full three-service PASS qualifies AWG as a fallback and a particular Hot Standby node as a node or Mihomo failback target. UNKNOWN is not valid for automatic promotion.
- Exact FIXED node order with no backward wrap; no manual-mode override.
- A confirmed active Mihomo service FAIL, Hot Standby preference before AWG, allowed reason and confirmation flags, and explicit user-enabled auto-failback before a planned return.

Mock transaction semantics: reject concurrent action requests; acquire a **separate action gate**; revalidate current state; prepare without changing user route; run preflight; apply; validate transport, forwarding guard and postflight; on failure attempt rollback. **If rollback cannot be verified, require FAIL-CLOSED rather than an unguarded DIRECT path.**

Critical integration caveat: the *existing* `awg-transport select` acquires `/run/awg-maintenance.lock` internally. A future single-owner production orchestrator must **not hold this same lock across its invocation**, which would deadlock. The real adapter must use a separate serialized action gate, allow the existing transport transaction to take its maintenance lock, and recheck its state immediately before and after switching. The new test executor does **not yet implement physical fail-closed enforcement, its backend is injected solely in tests**.

### Stage 5 verification and outstanding blockers

- **144 offline Python tests** PASS (109 earlier + 17 fast sensor + 18 transaction fault-injection).
- Existing 3 selector advisory mock checks PASS.
- Python syntax and staged units/CI validation checked separately.
- Real active Mihomo regional rejection observed in read-only mode; **no live transport/node switched**.

Remaining before real activation: connect the fast urgent flag to a bounded immediate full-service recheck; robust video and ChatGPT WAF qualification for actual service availability (AWG remains UNKNOWN); build and separately verify a real single-writer route action adapter with live forwarding-plane postcheck, emergency fail-closed guard and rollback; prove Selective/Transit no-leak, MikroTik SSTP independence and P50/P95 recovery; repair failing Mihomo provider auto-refresh. Draft PR #84 must not be merged or deployed as automatic switching until these pass.

Additional fast-alarm hardening: two consecutive distinct REGION_BLOCKED samples must arrive within 45 seconds; an older prior block, reboot, node change or UNKNOWN cannot resurrect a stale alarm. The read-only `show` path also suppresses any urgent indication after the age/boot limit. All timestamps and intervals remain configurable proposals until field validation.


## Stage 6 — real YouTube SABR diagnosis and stricter pre-switch proof

Read-only checks on Raspberry Pi on 2026-10-12 revealed that YouTube's current watch page via `awg0` returns HTTP 200 and `playabilityStatus=OK` with 14 adaptive format descriptors, but **none with a directly downloadable media URL**. Instead the player provides `serverAbrStreamingUrl` (SABR/UMP) and `probeUrl` (a signed `/videogoodput` CDN diagnostic). This is a player/protocol feature, **not evidence of country blocking**. No video was decoded or downloaded as actual media in this experiment.

The shared `awg-mihomo-service-check.py` now:

- Parses the player object safely, validates `playabilityStatus`, and explicitly detects SABR rather than conflating it with a missing video or broken YouTube.
- Optionally reads at most 1 KiB through the same VPN of the `/videogoodput` URL to distinguish CDN network reachability from missing media; **a goodput response is never an actual-video PASS**.
- Keeps SABR as `UNKNOWN/youtube_sabr_media_unverified` or `UNKNOWN/youtube_sabr_cdn_reachable_media_unverified` until actual media can be verified reliably.
- A single signed media URL HTTP 403/451 (expiration, playback token or one video's restrictions) is now `UNKNOWN`, not an automatic YouTube-wide FAIL. Actual HTTP 206 media bytes from a validated direct video URL can still PASS. A single `LOGIN_REQUIRED` video remains UNKNOWN (not a global outage).
- Refuses unsupported/malformed format descriptors rather than throwing or promoting any guessed URL.

The AWG-bound DNS-over-HTTPS client now validates the **echoed DNS question's hostname, A/IN class and truncation flags**, preventing a valid-looking response to an unrelated question from being accepted as current service evidence. Real AWG probe after the change still returns OpenAI API PASS, ChatGPT web 403 UNKNOWN and YouTube SABR media UNKNOWN; `table 100` remained `default dev mihomo0`.

Mock-only `awg-switch-transaction.py` was also strengthened: an independently implemented future execution backend must explicitly confirm *two distinct fresh failure observations* and requalify the target under the separate action gate; a standalone advisory JSON can never authorize itself. A failed preflight attempts to abort/restore preparatory state and, when restoration cannot be verified, returns `FAIL_CLOSED_REQUIRED`. No real fail-closed command is run by this model.

**Verification:** 152 Python tests PASS on the Pi's temporary RAM checkout after these changes, including fresh SABR/media and DNS mismatch regression tests. Production services, routes, SSTP and MikroTik have not been changed. The PR remains DRAFT and **no automatic service-aware switching is safe yet**.

**Remaining gating item:** a maintained, low-cost SABR/UMP *actual media* verification implementation or separately validated playback test. Treating SABR metadata or `/videogoodput` as media proof is prohibited. ChatGPT web HTTP 403 still requires a more reliable WAF/geo vs user-session distinction. Do not weaken the all-PASS gate merely to accelerate rollout.


## Stage 7 — underlay path provenance, DIRECT vs ASSISTED (2026-10-12)

**Problem proven on real Pi:** both inspected public Mihomo endpoint IPs have `ip -4 route get` next hop `via 192.168.112.1 dev eth0` with Pi source `192.168.112.34`. This establishes only the **Pi-to-MikroTik** hop. The hAP ax² may still mark and route onward through **SSTP** or another path. An HTTP success through a Mihomo exit does **not** prove the node can connect independently of AWG or SSTP.

New `src/awg-endpoint-provenance.py` inspects the precise candidate endpoint using **read-only `ip -4 route get`** (argument list, no shell, 2s limit). It neither resolves arbitrary provider hostnames nor sends packets nor changes ip rules, routes, nftables or RouterOS. Conservatively classified outcomes:

- `DIRECT_LOCAL_UNVERIFIED` — Pi route uses expected `eth0` and next-hop MikroTik; **not proven end-to-end DIRECT**, no automatic promotion.
- `ASSISTED_AWG` — candidate endpoint routes via an `awg*` interface, or provider explicitly requires an AWG interface; not usable as an independent DIRECT replacement.
- `ASSISTED_MIHOMO` — endpoint itself is routed through Mihomo or uses a proxy-chain/`dialer-proxy`; not independent.
- `UNKNOWN` — domain endpoint without independently verified resolution, private/unexpected IP, changed/missing route, unsupported interface or other untrusted evidence; not auto-promotable.
- `DIRECT` with `scope=END_TO_END` and `router_verified=True` is **only a future signed/independently verified RouterOS route-policy attestation contract**, used in *offline fixtures*. **The Pi-only inspector NEVER creates this state.** No such attestor has been installed.

Integrated into the read-only Hot Standby worker, AUTO SMART and the dry-run observer:

1. Each Hot Standby candidate checks underlay before and after its isolated service probe and records a sanitized `underlay` field (no endpoint address/keys). If the route changes, mark UNKNOWN. A successful ChatGPT/YouTube result alone cannot enter the two-node warm list.
2. The standby cache, observer and the mock transaction authorization reject old records missing underlay, assisted paths and Pi-local unverified paths. The future production executor must independently recheck the real endpoint and router policy **again at commit time**; a user-supplied or stale JSON claim is not authoritative.
3. AUTO SMART records the route reason but, with no end-to-end attestation, **skips expensive speed benchmarks and any promotion recommendation** for that node. This prevents spending up to ~85 MB/full run on unverified paths. The service-aware data plane and two-stage speed scoring continue to be modeled and unit-tested with explicitly *hypothetical* certified DIRECT fixtures.

**Acceptance limitation:** Because no read-only MikroTik policy attestation is currently wired, the newly hardened draft cannot produce real auto-eligible hot spares, even if Mihomo's service probe returns PASS. **This is deliberate fail-closed staging, not a completed production feature.** Never weaken `DIRECT_LOCAL_UNVERIFIED` to `DIRECT` to make tests pass. Future attestation should verify RouterOS connection/routing-mark tables, endpoint-specific bypass rules, router-side path and actual prospective production policy under the user's approved configuration, without touching existing SSTP. Explicitly decide how domain/IP-changing endpoints invalidate the proof.

Read-only smoke: `194.38.11.86` and `45.86.66.170` classified `DIRECT_LOCAL_UNVERIFIED`; `example.org` and private addresses UNKNOWN. Production table 100 stayed on `mihomo0`; Transit ACTIVE, guard SAFE.

**Verification:** **176 offline Python tests** pass in the Pi's isolated staging clone (including 14 new provenance cases, cached/assisted no-promotion, AUTO SMART no recommendation, mock transaction rejects unverified paths). CI and clean GitHub checkout will be checked separately. No live route/transport/MikroTik/SSTP changes. Draft PR #84 remains release-blocked by end-to-end DIRECT attestation, ChatGPT+SABR playback verification, real actuator and failover fault injection.

LAN reconfiguration safeguard: the read-only provenance inspector reads the installed `/etc/awg-pbr/env` keys `LAN_IF` and `ROUTER_IP` as data (never shell-sources it), instead of assuming the test-stand's `eth0` / `192.168.112.1`. If that protected configuration is unreadable, invalid or missing, results are UNKNOWN, not DIRECT. Added three regression tests for LAN changes, malicious env values and missing configuration.


## Stage 8 — MikroTik RouterOS end-to-end route audit over pinned SSH (2026-10-12)

### Real read-only findings (MikroTik hAP ax², RouterOS 7.24.2)

An existing SSH alias `mikrotik-gpt` on Pi already connects via the authorized restricted account to the LAN router (`192.168.112.1`, custom SSH port). **No new credentials or MikroTik configuration were created**.

The actual RouterOS configuration was inspected without modifying it:

- First active `/ip firewall mangle prerouting` rule `AWG-PI-TRANSPORT-DIRECT`: `action=accept src-address=192.168.112.34 in-interface=bridge`. It precedes all rules marking client traffic for `r_to_vpn`; RouterOS chain semantics stop evaluating subsequent mangle matches.
- `/routing/rule`: no configured rules. Main FIB route `0.0.0.0/0` is active via physical WAN `ether1`; `r_to_vpn` separately prefers SSTP. WAN and LAN interface-list memberships are unambiguous.
- RAW, bridge filter/NAT and hotspot: no active rules/instances. NAT intercepts TCP/UDP DNS port 53; source NAT masquerade is configured. Main VRF is the default.
- The router has dynamic **L2TP/IPsec UDP/1701** peer-specific policies; the verifier must not misinterpret these as arbitrary default IPsec tunnels. A candidate matching a scoped peer endpoint+port is refused, and unrecognized IPsec policies are refused.
- A single pinned-SSH RouterOS snapshot plus local Pi `ip -4 route get` before and after yielded **DIRECT (30s proof)** for test destinations `194.38.11.86:443/tcp`, `45.86.66.170:443/tcp`, and `45.86.66.170:51820/udp`. The same test against `45.86.66.170:53/udp` correctly returned `UNKNOWN/dns_port_intercepted` because of configured dst-NAT. These are **address/port route checks**, not proof the actual subscription node uses those test ports or that ChatGPT/YouTube playback works.

### Staged source and execution contract

`src/awg-mikrotik-route-attestor.py` uses only a fixed set of RouterOS **`print terse without-paging`** commands and `:put` section delimiters over existing pinned SSH. The SSH command uses strict host-key checking, BatchMode/no passwords, disabled agent forwarding, short timeouts, an allowlisted host alias and verifies that the alias resolves to the expected LAN router IP. No `/set`, `/add`, `/remove`, `export`, `backup`, traceroute or configuration-changing operation is used.

Checks before a positive DIRECT conclusion:
1. Specific public IPv4 endpoint, numeric port and TCP/UDP protocol are valid; **Pi local route before and after the audit** uses the expected source IP, LAN device and next-hop router.
2. All expected RouterOS data sections exist, with mangle and route tables unchanged across two reads **within the same SSH session**.
3. The first effective prerouting mangle match is an *unconditional-to-this-Pi* `action=accept`, exactly bound to its LAN ingress and IP.
4. Main FIB active **longest-prefix match** for the endpoint uniquely egresses via the sole configured physical WAN member; any more-specific SSTP route/VRF, active routing rule, ambiguous ECMP, unexpected NAT/RAW/bridge/hotspot/IPsec rule leads to UNKNOWN.
5. DNS TCP/UDP 53 is denied positive attestation on this router due to configured redirects.
6. Result is bound to exact endpoint IP, port, protocol, Pi source and router by a SHA-256 **identifier**, with 30-second freshness. **This digest is not a cryptographic signature or protection against forged cached JSON**; a future production selector must perform an independent live audit immediately before any route commit.

`attest_batch()` checks up to **20 endpoints using one SSH RouterOS snapshot**, with separate local route checks before/after each candidate; reduces Pi/MikroTik query load and minimizes disk writes (no persistent output). Results include only status, reason, timestamp and bound identifier, not raw routing/firewall rules or credentials. Literal public IPv4 only: FQDN destinations remain UNKNOWN until the actual IP dialed by Mihomo can be independently verified.

**Critical integration status:** Stage 8 implements a working **read-only attestor** and pure batch API. It is **not installed on production** and is **not yet connected to automatic Hot Standby admission or the live transport selector**. Stage 7's Pi-local-only safety gate is still in effect in the staged Hot Standby code until a secure evidence broker and mandatory commit-time re-attestation are implemented. **Do not promote a cached/direct-looking JSON assertion on its own.**

### Verification

**210 offline Python tests passed** (176 previous + 34 RouterOS route-attestor including injected negative policies, scoped IPsec, DNS redirects, VRF, active SSTP default, higher-priority VPN host route, source/SSH mismatch, stale or changing route, tampered/partial snapshots, and single-session batch scan). Three selector advisory tests passed.

Actual read-only SSH attestation was tested live on the current MikroTik, without altering a single existing rule or SSH account. Pi remains in Transit ACTIVE, guard SAFE and `table 100 -> mihomo0`. SSTP remains the priority remote management channel.

**Next:** bind *actual Mihomo dialed endpoint* (including hostname resolution and protocol/port) to this positive router snapshot, use a privilege-separated RAM-only attestation producer, enforce TTL and independent mandatory re-attestation in the single-owner action executor. Continue strict ChatGPT/WAF + SABR-media service qualification and rollback/no-DIRECT leak tests before activating any automatic failover.


## Stage 9 — event-driven optional router adapter (staged; not deployed)

The accepted [event-driven routing ADR](ADR-EVENT-DRIVEN-ROUTER-ATTESTATION-v1.3.0.md) has its first implementation in `src/awg-router-event-policy.py`. The only background *design* uses local Linux netlink notifications and a LAN-config file path trigger; **no periodic SSH or per-node RouterOS connection** is scheduled. The staged systemd files (`awg-router-events.service`, `awg-router-events-observe.service`, `awg-router-events.path`) are **not installed or enabled by the installer or on live Pi**.

An event raises the RAM-only network generation epoch; changes to boot, LAN, main routes, policy rules, source address or optional provider SHA invalidate prior evidence. The policy planner distinguishes `IDLE`, `AUDIT_ON_DEMAND`, `READY_TO_PREFLIGHT`, `BLOCKED` and `UNVERIFIED`, with no production transport switch capabilities. `READY_TO_PREFLIGHT` means only a **shadow advisory** on a precise, 30-second, fresh *in-process* attestation, never an actionable permission from unsigned saved JSON.

Real read-only Pi test: idle caused **zero SSH**; an explicit audit request for a known public IPv4 TCP/443 test endpoint used **one** pinned SSH RouterOS query and returned advisory `READY_TO_PREFLIGHT`, while main table 100 remained default `mihomo0` and Transit guard SAFE. No live source files, new unit or RouterOS rule changed. **228 Python offline tests and 3 shell shadow tests PASS** on clean checkout; staged systemd units verify.

**Next integration blockers:** prove actual dialed Mihomo endpoint binding (including hostname/transport), decide secure proof freshness and adapter privileges, wire events to Hot Standby with conservative unverified handling, implement independent pre-commit re-attestation in the single existing selector with lock-safe rollback, and qualify real ChatGPT plus SABR video. Routine static-router polls are not part of the plan.
