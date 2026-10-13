# Mihomo Service Eligibility — ChatGPT + YouTube (focused change)

**Scope:** complete the original node-selection request, not replace AWG Pi's working routing or add a recovery system. Code remains **opt-in** until independent live tests. MikroTik and NAS are independent immutable devices. MikroTik already sends marked traffic through SSTP while available, and via Pi when SSTP is down. Pi must preserve Transit FAIL-CLOSED.

## What constitutes a qualifying Mihomo node

A plain Mihomo latency/health result is NOT sufficient. AUTO SMART uses a separate, loopback-only, TUN-disabled Mihomo instance in RAM to test candidate nodes; neither the selected live proxy nor its route is switched by the measurement.

The service checker requires three network-level signs, all via **the same selected shadow proxy**:

1. OpenAI API responds without an `unsupported_country_region_territory` restriction; an unauthenticated 401 is accepted as evidence that the endpoint is reached, not as proof a real chat works.
2. `chatgpt.com` presents recognizable non-challenge ChatGPT HTML, rejecting Cloudflare challenges and unknown redirects.
3. A YouTube watch page provides a trusted Googlevideo HTTPS stream URL and an actual 206 media byte-range responds. A watch-page HTTP 200 alone is insufficient.

This is network-level eligibility, **not a full browser login/chat exchange or a confirmed decoded YouTube playback test**. Those require separate real user acceptance before calling the entire experience proven.

All three must be PASS; any FAIL/UNKNOWN makes the node **ineligible** for automatic choice. Do not upgrade UNKNOWN into PASS.

## Two missing links now implemented, but not yet activated

1. `awg-mihomo-service-eligibility.py` checks a private root-owned AUTO SMART report, exact node name (unique), current provider SHA-256, <30 min freshness, `service_ok`, three PASS results and independently confirmed candidate throughput. Stale, missing or tampered data always denies an automatic candidate. A max one-hour TTL is a hard ceiling.
2. `awg-mihomo-node-policy` checks candidate eligibility before `node select-auto` in both FIXED and AUTO. AUTO skips an ineligible node and searches another allowed candidate. FIXED preserves the explicit forward-only list. If none qualifies, the existing AWG transport fallback policy may take over; there is never an unapproved DIRECT exception.
3. `awg-selection-monitor` now also detects degradation **of ChatGPT/YouTube when the proxy transport remains otherwise healthy**. This is opt-in and rate limited: checks at most once per 60 seconds through the existing live loopback proxy. Two independent failing observations are required before the existing transport/node failure counter begins advancing. No filesystem writes are added for monitoring beyond the existing /run state.
4. `install.sh` includes the already developed AUTO SMART shadow engine, its limit module, service checker and read-only eligibility helper; none is enabled by installation. No new root access is granted.

The gate is **OFF by default**. The same root-owned file `/etc/awg-pbr/transports/mihomo/service-eligibility.mode` can later hold `require`, activating both current-node service monitoring and strict candidate eligibility after supervised testing; `off` reverts immediately after the monitor is restarted. This file is not created or changed in the current work.

No CI result, shadow recommendation or network HTTP probe may be described as a completed *interactive* ChatGPT + YouTube playback test.

## Actual Pi observations, 2026-10-13

The current production node is `shadowsocks-696792830`, proxy egress `194.38.11.86`. A read-only probe through `127.0.0.1:7890` returned OpenAI unsupported region (FAIL), ChatGPT HTTP 403 (UNKNOWN), YouTube URL error (UNKNOWN). Therefore the current node does not qualify as PASS, despite generic transport health being healthy.

An existing installed AUTO SMART scan considered 10 candidates and ranked `hysteria2-335173174` fastest on measured throughput. The installed old script version did not publish validated per-service PASS details; its speed recommendation is **not evidence of eligibility**. The current version in this branch must first be installed and run in SHADOW_ONLY to populate a fresh service-qualified report. No automatic switching occurred.

## Tests and release gates

Tests cover region restriction, ChatGPT/Cloudflare uncertainty, YouTube media range, redirects and forced loopback proxy despite NO_PROXY=*, absent/corrupt provider-bound reports, stale/duplicate node names, confirmed throughput requirement, and two independent service failures before a live node is treated as degraded.

Production rollout gates:
- Install the new code in an approved Pi maintenance window, without touching MikroTik or NAS.
- Run **one new shadow scan** with real service checks; validate at least two independently qualifying nodes, both endpoints routed DIRECT with no recursion.
- Verify ChatGPT chat interaction and actual YouTube playback through the selected test nodes (user acceptance or an authorized browser/video test).
- Confirm backup of Pi configuration, fail-closed nftables, and AWG transport fallback.
- Enable service gate explicitly, run staged negative tests: YouTube-only failure, ChatGPT-only failure, unknown, all candidates failed; ensure no leaks and stable hysteresis.
- Retain the off-by-default guard and revert gate mode if any failure appears.

This scope does not require any new persistent recovery layer or change to SSTP, MikroTik, NAS, Selective mode or working transport routes.
