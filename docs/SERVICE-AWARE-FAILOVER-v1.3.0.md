# Service-aware AUTO SMART — stage 1 (v1.3.0)

Status: **experimental / SHADOW_ONLY**. Tracks #83. Not installed or enabled by default.

## Change

The existing AUTO SMART research prototype, previously only on Raspberry Pi, is now versioned in `src/awg-mihomo-smart`. It benchmarks using a short-lived, isolated, loopback-only Mihomo instance (not production TUN).

The new `src/awg-mihomo-service-check.py` checks *through the selected proxy*:
- OpenAI API: region rejection `unsupported_country_region_territory` is FAIL; unauthenticated HTTP 401 without region rejection is API-access PASS.
- ChatGPT web: HTTP 200 with a nonempty response is tentative PASS; HTTP 403 can mean a Cloudflare challenge and is UNKNOWN, not automatically a region rejection.
- YouTube: watch page **plus real video bytes** (HTTP 206 from an extracted `*.googlevideo.com` media URL). A reachable homepage alone does not qualify.

All checks must PASS. FAIL and UNKNOWN never become unconditional success. To prevent an accidental DIRECT bypass, the probe uses a forced localhost proxy even when NO_PROXY is set.

AUTO SMART's **10 → up to 3 → up to 2** screen/sustained/confirm pipeline now filters by actual service eligibility **before** expensive speed benchmarks and recommendations. Existing bandwidth caps, ranking logic and SHADOW_ONLY behavior remain.

## Local no-network tests

```sh
python3 tests/test_mihomo_service_check.py -q
python3 tests/test_auto_smart_calibration.py -q
python3 tests/test_auto_smart_history.py -q
```

24 tests passed in the Pi temporary RAM clone on 2026-10-12, without making any production switches. One read-only live test through the current Mihomo proxy correctly returned FAIL for OpenAI region with web and YouTube UNKNOWN.

## Limitations — DO NOT deploy to production yet

1. ChatGPT pages can respond with bot challenges even on otherwise eligible IPs. HTML content validation and challenge differentiation require additional live testing.
2. YouTube may use signature-only streams that this prototype cannot resolve; the result stays UNKNOWN rather than becoming false PASS. A tested media extractor/strategy suitable for ARM64 is needed before relying on this in production.
3. There is **no continuous standby scheduler** in this stage and no active backup selection while AWG runs. A one-shot SHADOW benchmark does not provide hot standby.
4. No integration with `awg-selection-monitor`, automatic node failover, transport fallback, or auto-failback yet. Existing production behavior remains unchanged.
5. Do not activate automatic decisions until bounds, global upstream outages, TTL, per-node isolation, cooldown, safety/rollback and Transit FAIL-CLOSED are tested end-to-end. Keep MikroTik/SSTP untouched.

## Next implementation steps (#83)

- Continuously prequalify the same 10 candidates, maintain 2 RAM-cached standby nodes and test while AWG is active. Add configurable short TTL, test interval and resource limits.
- Integrate shared eligibility into AUTO SMART and failover, with direct-request protection and real per-node post-check.
- Add independently configurable primary transport and auto-failback, anti-flapping, bounded recovery and safe rollback.
- Verify on an isolated setup, then controlled production trials, before deciding on a release.
