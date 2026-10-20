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

`MIHOMO_XRAY_AUTO_FAILOVER_CANARY` defaults to **0** (disabled). **Selective** additionally requires `MIHOMO_XRAY_SELECTIVE_CANARY=1`; the Transit test flag alone does not authorize Selective. It must **not** be exported by the installer, menu, subscription refresh or service units.

Even with this temporary test-only opt-in, cross-core AUTO dispatch refuses:

- any host other than test Pi `awg-upgrade`;
- modes other than Selective/Transit; Selective without its own second opt-in flag;
- running while a healthy AWG is being repaired as Mihomo standby;
- enabled READY/Hot Pool priority (distinct media-proof contract);
- stale/missing network proof, absent Xray executor, or unsafe/corrupt Xray bridge state.

The executor itself additionally requires two failed incumbent Pi-bound HTTPS checks, exact provider credentials/identity, a locked maintenance transaction, an independent 300-second watchdog, genuine TUN HTTPS success, route validation and controlled boot wiring. Failure is not a PASS.

**Selective source support is experimental but uninstalled.** The added backend uses the existing `awg-pbr-failopen` helper if no working VPN remains, verifies removal of mark `0x100` lookup 100, keeps SSH/DNS and avoids touching a verified healthy AWG takeover. It never uses Transit disable for Selective. These are rootless unit-test assertions, **NOT hardware FAIL-OPEN evidence**. A live selective test remains blocked pending independent rescue/watchdog race review, privileged passive scan, installation/rollback review and operator-authorized fault window. Do not change the active node, test Pi operating mode or MikroTik just to bypass the requirement.

No automatic performance-driven return from AWG to Mihomo/Xray. Xray→Mihomo node recovery through old selector remains blocked while the sidecar/bridge is present; unhealthy Xray delegates to AWG rather than trying unsafe live cleanup.

## Evidence and required next gates

- Rootless tests on Pi: initial 569/569 PASS, then 577/577 PASS after Selective safety modifications; new Selective passive scanner and its own unit tests added after that run. Latest HEAD must be tested again before reporting aggregate PASS.
- No privileged source installation or live Xray AUTO test in this draft.
- In test order: **Selective first**, then **Transit** only after Selective gates pass. The bounded test-Pi `scripts/awg-xray-selective-auto-preflight.py --check|--scan` verifies exact Selective baseline; `--scan` runs at most two 4-candidate isolated Xray HTTPS batches and writes only the credential-fingerprinted network cache. No service/route change. Its real root run remains pending.
- Before activation: verify independent recovery and watchdog/transport concurrency for Selective; review safe Xray bridge cleanup; scan fresh Xray profiles, ensure credential identity and root-only preflight; test only on isolated microSD with watchdog/rescue timers armed.
- Prove real failed Mihomo → Xray via *Mihomo TUN* OpenAI HTTPS, monitor evidence, stable routing, SSH/DNS/SSTP, and configured AWG protection. Verify failed Xray → AWG and restoration without stale bridge or direct leaks. Test LAN-client separately if release target demands it.
- Recheck fresh install, upgrade/persistence and reboot. Keep PR Draft until acceptance, never claim this source stage as a v1.3 release gate PASS.

Related: [PROJECT_STATE](PROJECT_STATE.md), [installer-first policy](INSTALLER-CHANGE-POLICY.md), [release gate](TESTING-v1.3.0.md).

## Selective-first source status, 2026-10-20

Selective and Transit remain separate acceptance gates; **Selective is first**. Selective support in source is double-gated by `MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1` **and** `MIHOMO_XRAY_SELECTIVE_CANARY=1`, absent from installers/units. The Xray executor verifies identity/fresh network proof, backed-up AWG routing and HTTPS and preserves a healthy AWG. An unsafe Xray abort calls the existing Selective `awg-pbr-failopen` (drops the mark-0x100 route), stops unverified components and confirms SSH/DNS; Transit continues to use its FAIL-CLOSED guard. The independent watchdog takes the shared maintenance lock to avoid racing `awg-transport select awg`.

Native health-pool AUTO retains its bounded attempts. When exhausted, and only under the explicit canary, it can nominate **one** freshly verified Xray candidate from `awg-mihomo-unified-nodes best --engine XRAY`, excluding already rejected names. A rejected Xray transaction is not passed into legacy Mihomo activation; control falls through to configured AWG. `READY=OFF` / Hot Pool OFF stays unchanged for paid HoneyVPN.

The root-only `scripts/awg-xray-selective-auto-preflight.py --check|--scan` protects unchanged live transport/node/routes. `--scan` invokes bounded isolated Xray HTTPS probes; only credential-fingerprinted Xray network cache is modified. **Not yet executed as root on the live test stand** (Desktop Commander sudo block). 

Full isolated-Pi Python regression suite: **589/589 PASS** at commit `e855ae92`, Bash syntax PASS, no live service changes. Root-only preflight, sidecar AUTO, rollback timers, forwarded client and reboot remain **OPEN**. Do not call Selective PASS or enable on production from source tests.
