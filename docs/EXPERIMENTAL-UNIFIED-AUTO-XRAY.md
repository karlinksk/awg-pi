# Experimental unified Mihomo / Xray AUTO (v1.3.0)

Status: **draft source / rootless tests only**. NOT enabled on the test Pi, NOT merged, installed, released, or certified for live automatic cross-core failover.

## Intended flow

1. Keep Mihomo as the gateway TUN and its standard node health-pool AUTO.
2. Resolve each candidate against the current single subscription, including changed profile counts/names and credentials.
3. Use the existing Mihomo node activation for `NODE_ENGINE=MIHOMO`.
4. For `NODE_ENGINE=XRAY` only with fresh exact `NETWORK_OK` Xray proof, delegate to the already guarded Xray activation transaction, never the legacy Mihomo selector.
5. On Xray transaction failure **abort node recovery**; selection-monitor may attempt the separate configured AWG transport. Never recycle the confirmed dead incumbent.
6. If a Xray bridge or selected Xray metadata remains after a sidecar outage, block Mihomo-only node recovery and defer to configured transport AWG, rather than restart the previous known-bad node.

## Experimental safety restrictions

`MIHOMO_XRAY_AUTO_FAILOVER_CANARY` defaults to **0** (disabled). It must **not** be exported by the installer, menu, subscription refresh or service units.

Even with this temporary test-only opt-in, cross-core AUTO dispatch refuses:

- any host other than test Pi `awg-upgrade`;
- Selective or any mode other than Transit;
- running while a healthy AWG is being repaired as Mihomo standby;
- enabled READY/Hot Pool priority (distinct media-proof contract);
- stale/missing network proof, absent Xray executor, or unsafe/corrupt Xray bridge state.

The executor itself additionally requires two failed incumbent Pi-bound HTTPS checks, exact provider credentials/identity, a locked maintenance transaction, an independent 300-second watchdog, genuine TUN HTTPS success, route validation and controlled boot wiring. Failure is not a PASS.

**Selective is explicitly NOT covered.** Its FAIL-OPEN / independent DNS semantics require a separately proven mode-aware Xray recovery; do not relax this guard to make a canary appear to pass. Do not change the active node, test Pi operating mode or MikroTik just to bypass the requirement.

No automatic performance-driven return from AWG to Mihomo/Xray. Xray→Mihomo node recovery through old selector remains blocked while the sidecar/bridge is present; unhealthy Xray delegates to AWG rather than trying unsafe live cleanup.

## Evidence and required next gates

- Source syntax and 12 new isolated dispatch tests PASS on the test Pi, existing FIXED regressions 15/15 PASS; full rootless Python test suite 569/569 PASS for initial commit (rerun against latest HEAD after any edits).
- No privileged source installation or live Xray AUTO test in this draft.
- Before activation: design/review independent recovery for Selective and safe Xray bridge cleanup; run fresh isolated Xray scans, verify current provider fingerprint and root-only preflight; test only on the isolated microSD with rollback timers prearmed.
- Prove real failed Mihomo → Xray via *Mihomo TUN* OpenAI HTTPS, monitor evidence, stable routing, SSH/DNS/SSTP, and configured AWG protection. Verify failed Xray → AWG and restoration without stale bridge or direct leaks. Test LAN-client separately if release target demands it.
- Recheck fresh install, upgrade/persistence and reboot. Keep PR Draft until acceptance, never claim this source stage as a v1.3 release gate PASS.

Related: [PROJECT_STATE](PROJECT_STATE.md), [installer-first policy](INSTALLER-CHANGE-POLICY.md), [release gate](TESTING-v1.3.0.md).
