# Mihomo Service Eligibility — ChatGPT + YouTube (focused change)

**Scope:** complete the original node-selection request, not replace AWG Pi's working routing or add a recovery system. Code remains **opt-in** until independent live tests. MikroTik and NAS are independent immutable devices. MikroTik already sends marked traffic through SSTP while available, and via Pi when SSTP is down. Pi must preserve Transit FAIL-CLOSED.

## What constitutes a qualifying Mihomo node

A plain Mihomo latency/health result is NOT sufficient. AUTO SMART uses a separate, loopback-only, TUN-disabled Mihomo instance in RAM to test candidate nodes; neither the selected live proxy nor its route is switched by the measurement.

The service checker requires three network-level signs, all via **the same selected shadow proxy**:

1. OpenAI API responds without an `unsupported_country_region_territory` restriction; an unauthenticated 401 is accepted as evidence that the endpoint is reached, not as proof a real chat works.
2. `chatgpt.com` presents recognizable non-challenge ChatGPT HTML, rejecting Cloudflare challenges and unknown redirects.
3. A YouTube watch page provides a trusted Googlevideo HTTPS **video** stream URL and an actual 206 media byte-range responds with recognizable MP4/WebM/TS container header bytes. A watch-page HTTP 200 alone is insufficient.

This is network-level eligibility, **not a full browser login/chat exchange or a confirmed decoded YouTube playback test**. Those require separate real user acceptance before calling the entire experience proven.

All three must be PASS; any FAIL/UNKNOWN makes the node **ineligible** for automatic choice. Do not upgrade UNKNOWN into PASS.

## Two missing links now implemented, but not yet activated

1. `awg-mihomo-service-eligibility.py` checks a private root-owned AUTO SMART report, exact node name (unique), current provider SHA-256, <30 min freshness, `service_ok`, three PASS results and independently confirmed candidate throughput. Stale/missing data is **never** accepted as PASS. When cache cannot confirm, the node selector uses a *new* one-node shadow service scan before trying to switch; failure/UNKNOWN still blocks the candidate.
2. `awg-mihomo-node-policy` checks candidate eligibility before `node select-auto` in both FIXED and AUTO. First it looks for a fresh PASS cache. If unconfirmed/stale, it starts `awg-mihomo-smart service-scan --node NAME` to test **this specific node now**, without throughput downloads. That isolated scan accepts only public literal IPv4 endpoints whose Pi route matches the main ethernet gateway; DNS-name endpoints remain UNKNOWN until a separately verified safe resolver is implemented. A scan never reconfigures the active TUN. AUTO excludes ineligible nodes and tries another; FIXED preserves the user-defined forward-only chain. At most **three candidates** are examined per failover. If none qualifies, existing AWG transport fallback may take over; no unapproved DIRECT exception.
3. `awg-selection-monitor` now also detects degradation **of ChatGPT/YouTube when the proxy transport remains otherwise healthy**. This is opt-in and rate limited: checks at most once per 60 seconds through the existing live loopback proxy. Two independent failing observations are required before the existing transport/node failure counter begins advancing. No filesystem writes are added for monitoring beyond the existing /run state.
4. `install.sh` includes the already developed AUTO SMART shadow engine, its limit module, service checker and read-only eligibility helper; none is enabled by installation. No new root access is granted.

The gate is **OFF by default**. The same root-owned file `/etc/awg-pbr/transports/mihomo/service-eligibility.mode` can later hold `require`, activating both current-node service monitoring and strict candidate eligibility after supervised testing; `off` reverts immediately after the monitor is restarted. This file is not created or changed in the current work. Missing or stale evidence triggers a bounded live one-candidate recheck; no periodic high-bandwidth scan is required merely to keep a cache fresh.

No CI result, shadow recommendation or network HTTP probe may be described as a completed *interactive* ChatGPT + YouTube playback test.

## Actual Pi observations, 2026-10-13

The current production node is `shadowsocks-696792830`, proxy egress `194.38.11.86`. A read-only probe through `127.0.0.1:7890` returned OpenAI unsupported region (FAIL), ChatGPT HTTP 403 (UNKNOWN), YouTube URL error (UNKNOWN). Therefore the current node does not qualify as PASS, despite generic transport health being healthy.

An existing installed AUTO SMART scan considered 10 candidates and ranked `hysteria2-335173174` fastest on measured throughput. The installed old script version did not publish validated per-service PASS details; its speed recommendation is **not evidence of eligibility**. The current version in this branch must first be installed and run in SHADOW_ONLY to populate a fresh service-qualified report. No automatic switching occurred.

## Tests and release gates

Tests cover region restriction, ChatGPT/Cloudflare uncertainty, YouTube media range, redirects and forced loopback proxy despite NO_PROXY=*, absent/corrupt provider-bound reports, stale/duplicate node names, confirmed throughput requirement, and two independent service failures before a live node is treated as degraded.

Production rollout gates:
- Install the new code in an approved Pi maintenance window, without touching MikroTik or NAS.
- Run **one new shadow scan** with real service checks, then a live **one-node on-demand shadow scan** without changing the selected production node. Validate at least two independently qualifying nodes, both endpoint routes DIRECT on Pi without recursion. This does not independently prove MikroTik WAN underlay routing.
- Verify ChatGPT chat interaction and actual YouTube playback through the selected test nodes (user acceptance or an authorized browser/video test).
- Confirm backup of Pi configuration, fail-closed nftables, and AWG transport fallback.
- Enable service gate explicitly, run staged negative tests: YouTube-only failure, ChatGPT-only failure, unknown, all candidates failed; ensure no leaks and stable hysteresis.
- Retain the off-by-default guard and revert gate mode if any failure appears.

This scope does not require any new persistent recovery layer or change to SSTP, MikroTik, NAS, Selective mode or working transport routes.
