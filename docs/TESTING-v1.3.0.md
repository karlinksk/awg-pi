# AWG Pi Gateway v1.3.0 — release validation

## Current candidate contract — 2026-10-24, PR #165

Owner-directed revision: manual selection must not require external HTTPS,
OpenAI HTTP401, ipify, ChatGPT or YouTube eligibility. AUTO uses fresh engine
network assessment through Mihomo's native fixed-Selector delay API (the existing
pool health URL, default generate_204); it never tests service eligibility.
The local `check`/manual activation contract stays independent of network tests.

AUTO observes both its incumbent and every activated candidate. A negative
engine URL-test is network evidence, not proof of provider fault; controller
failure, missing proxy, malformed result and concurrent selection are separate
infrastructure/unknown outcomes. Never turn these into “all provider nodes dead”.
Preserve threshold, full current-provider native-before-Xray traversal, safe
quiesce/retry, watchdog retirement, sticky AWG, exact identity, route ownership,
Transit guard and SSH/DNS. Xray uses the same selected bridge engine assessment.
Background Xray inventory local readiness is only advisory.

Regression must prove remote-endpoint failure triggers AUTO despite a live core,
a working later candidate prevents premature AWG, infrastructure unknown is not
counted as node failure, and MANUAL never calls network assessment. OpenAI
unavailability alone must not prevent selection. Keep guard/route/identity and
rollback failures fatal. Hardware release evidence still needs real independent
TUN traffic, cross-engine recovery, exhaustion/AWG, forwarded LAN, Selective
FAIL-OPEN, Transit FAIL-CLOSED, install/upgrade/reboot/restore. Engine delay is not
Pi-bound TUN or LAN evidence. No MikroTik/working-media changes without permission.

This document is the hardware/release gate for v1.3.0.

**Full 150-case execution matrix (all modes, transports, selectors and negative cases):** [RELEASE-ACCEPTANCE-MATRIX-v1.3.0.md](RELEASE-ACCEPTANCE-MATRIX-v1.3.0.md). Items in that checklist remain unaccepted until scoped evidence is attached to the current candidate.

**Clean-install defaults agreed 2026-10-20:** install AmneziaWG, Mihomo, optional pinned Xray adapter, Stage18 Node.js/yt-dlp and FFmpeg/FFprobe before any VPN profile/subscription exists. Finish in `Selective + unconfigured`, with transport availability-AUTO prepared but **Hot Pool SHADOW timer disabled/inactive and READY priority disabled (`ready-auto.mode=0`)**. Neither is silently enabled by subscription import or reboot; the operator can opt in via the menu after configuration. Xray remains disabled and its guarded live failover is experimental, not an accepted v1.3.0 release feature. Preserve pre-existing Hot Pool/READY choices on upgrades. This is a source contract, not hardware installation proof.

v1.3.0 adds a transport abstraction and an optional Mihomo backend while
preserving the v1.2 routing semantics:

- Selective Gateway remains **FAIL-OPEN**.
- MikroTik Transit / Backup VPN remains **FAIL-CLOSED**.
- AmneziaWG remains a first-class transport and the default on upgrade.
- Mihomo must not own global host routing (auto-route: false,
  auto-redirect: false).
- A Mihomo transport endpoint must stay DIRECT on MikroTik so the VLESS/Reality
  connection never loops through SSTP/another VPN.
- Provider cache is operational state. A failed subscription refresh must not
  destroy the last known-good cache.
- Subscription secrets, UUIDs, Reality keys, HWIDs and full private URLs must
  not appear in normal status/menu output.

## 2026-10-20 Selective two-fault hardware evidence (experimental; not release gate completion)

Owner ran pinned guarded Selective test on `awg-upgrade`: `FAULT=MIHOMO_STOP`, `FIRST_RESULT=XRAY_TUN`, `XRAY_TUN_HTTPS=PASS`; then `FAULT=XRAY_STOP`, `SECOND_RESULT=AWG`, `FINAL_AWG_HTTPS=PASS`, `SELECTIVE_XRAY_AUTO_FAILOVER=PASS`. Cleanup and watchdog recovery returned PASS. Independent non-root postcheck at 18:19:57 +07 confirmed AWG service active, Xray and Mihomo inactive, both policy route tables 100/101 via awg0, SSH/dnsmasq/monitor/health active, zero failed systemd units and no test timers. Detailed root-only trace and original native-node live restoration are **not independently verified**. This is **only** a controlled Selective Pi-bound TUN / dual-fault trial, not Transit, LAN, YouTube24, reboot or clean-install acceptance. Xray AUTO remains OFF by default; preserve owner choice to leave READY and Hot Pool OFF for paid subscriptions. Do not merge the experimental branch as v1.3.0 release evidence.

## 1. CI gate

Before any RC is installed on hardware, the target commit must pass:

- Bash syntax.
- ShellCheck (-S error).
- all unit/regression tests.
- pinned AmneziaWG v3.1 build.
- real isolated AWG profile preflight.

The installer itself must contain AWG_PI_VERSION="1.3.0", and the release tag
must match that internal version.

### Happ vs shadow video gate on same exit IP (2026-10-19 ~00:10 +07)

- User independently imported the exact public-subscription Shadowsocks candidate `shadowsocks-1827146542` into Happ on iPhone. On **home Wi-Fi** Happ showed VPN active; user reported actual YouTube playback and ChatGPT messaging. Screenshot of an external IP-checking website showed the public exit IP, which a subsequent read-only Pi journal comparison confirmed **exactly matched** the exit IPv4 from the prior shadow probe for this candidate (NL geo). This is a **user-reported functional app-level test**, not a Pi TUN/LAN-client verification or a locally reproduced frame-decode PASS. Private Shadowsocks credentials were not added to the repository.
- The Pi shadow check at 23:55:52 returned `CONNECT=PASS OPENAI=PASS CHATGPT=UNKNOWN YOUTUBE24=UNKNOWN VIDEO_REASON=stage18_ytdlp_bot_challenge GATE_REASON=YOUTUBE_VIDEO_NOT_DECODED`. The current code runs `yt-dlp` against one fixed public YouTube video; the bot-challenge classification arises before FFmpeg's actual 24-frame decode. This is **strong evidence of a functional-service false negative relative to the real viewer experience**, but NOT evidence that 24 frames were decoded by the automated gate. Do not grant READY or change criteria on this alone.
- Contrast: another candidate `shadowsocks-1827146845` had `OPENAI=PASS YOUTUBE24=PASS VIDEO_REASON=youtube_24_video_frames_decoded` at 00:08 on the same Pi; one successful scan was insufficient for READY, and the pool report remained READY 0/4. This means the decode path works for at least one shadow candidate while bot-challenge errors affect others.
- **Next bounded investigation:** on the test Pi, without browser testing or modifying live routes/transport, compare the exact failed candidate through the same isolated shadow proxy and 24-frame ffmpeg decode using the existing video vs one other public reference video; classify extraction bot challenge separately from TCP/TLS, video download and decoded-frame result. Keep network and LAN/TUN acceptance gates separate and do not reintroduce the rejected primary YouTube HTTP/Range gate.

### Hot Pool scanner skip: hardware result (2026-10-18 23:15 +07)

- Test Pi only. Two source-pinned Hot Pool helper files from draft PR #115 were installed with a RAM rollback copy. In a controlled root lock-contention experiment, the actual systemd Hot Pool service completed and reported 2/2 candidates as `RESULT=SKIPPED`, `SCAN_RC=2`, `SCAN_ERROR=LOCK_BUSY`, and 0 false `FAIL` results. Rootless regression suite: 82/82 PASS. No rollback required.
- After the test, AWG remained active in conservative AUTO, tables 100 and 101 both routed through awg0, DNS/SSH/DC/Mihomo and timer active, systemd failed units 0. This is an installed-on-test-stand partial fix, not a merged/released version.
- The intentionally blocked cycle had READY 0/4; it did not test real OpenAI, ChatGPT, 24-frame YouTube decode, Pi TUN switching, LAN forwarding or failover. The ordinary unblocked Hot Pool cycle remains OPEN.

### A/B of isolated shadow Mihomo lifetime in RAM (2026-10-18 22:45–22:46 +07)

- **Real test executed on clean-install test Pi `awg-upgrade`, no SD write or live transport change.** A one-shot root helper in `/dev/shm` used the same exact selected standby node in isolated loopback-only Mihomo instances: **COLD** launched 3 new processes for a single OpenAI API and YouTube HTTPS-page check each; **WARM** launched 1 process and ran the same checks 3 times with short pauses. Live Mihomo was checked before and after; no YouTube 24-frame decoding in this bounded comparative diagnostic. Main AWG was ACTIVE, Transit tables 100/101 stayed `default dev awg0`, SSH/DC/DNS healthy. The ephemeral configs were removed; exactly one main Mihomo process remained. A first attempted test hit a bug in the experimental helper's printing routine (no samples); corrected and retested with a function-level mock before the successful second run.
- **COLD results:** 6/6 HTTPS positive; three controller startups 195, 157, 159 ms; OpenAI 401 in 532/576/557 ms (mean 555), YouTube page HTTP 200 in 976/944/1024 ms (mean ~981). **WARM results:** 6/6 HTTPS positive; initial controller startup 157 ms; OpenAI 401 in 457/559/551 ms (mean ~522), YouTube page HTTP 200 in 946/969/886 ms (mean ~934). Live main proxy before/after: OpenAI 401 and YouTube page 200, both positive. **NO A/B evidence** that starting shadow Mihomo from RAM per candidate *necessarily* causes failures, and short-lived samples do not prove long-term stability. The SD-backed trial is explicitly rejected/not performed.
- Nearby regular Hot Pool cycle at 22:42 separately recorded `connect_not_ready` after ~22 seconds for a **different VLESS candidate**, READY 0/4 despite 115 preliminary healthy. Another Hysteria2 candidate also failed service confirmation. This suggests candidate-specific / isolation / transient underlay variability but does **NOT** identify a root cause. Do not conflate Hot Pool candidates or old shadow results with the exact standby node used in this test. Keep Hot Pool and READY gates unchanged until a controlled same-candidate reproducible difference is demonstrated.
- **Next gate OPEN:** for one previously shadow-`connect_not_ready` candidate, compare repeated isolated starts with an otherwise identical long-lived isolated process, while preserving READY OpenAI/ChatGPT/actual YouTube24 semantics and checking Pi TUN/LAN separately before any release acceptance. Never assume HTTP YouTube page 200 equals video24 decode.

### Same selected Mihomo node: TLS EOF vs later normal and pinned HTTPS PASS (2026-10-18, 21:31–21:44 +07)

- **Critical distinction:** do not call the Shadowsocks endpoint conclusively blocked/failed based on short TLS EOF observations. Manual isolated `service-scan` of the already-selected node at 21:31 returned `SERVICE_CONNECT_STATE=UNKNOWN`, 3 attempts, `SERVICE_CONNECT_WAIT_MS=20088`, all service checks UNKNOWN and video24 NOT RUN. The same *live selected node* through local proxy and Pi TUN had mixed failures at 21:32–21:35: OpenAI/YouTube TLS EOF, while ipify and Cloudflare HTTP 200 and ChatGPT HTTP 403 with working TLS. AWG remained active and healthy; neither selected node nor Mihomo systemd process changed.
- **Read-only counterexperiment after the failures, no transport/node/service changes:** 21:41 fixed destination IP tests: **14/14** HTTPS successful (OpenAI 401 for both IPv4 and YouTube/Cloudflare 200 for selected IPv4, each over loopback proxy and Pi-bound TUN); **32/32** four-cycle alternating tests succeeded for OpenAI and YouTube across ordinary domain-URL versus fixed IPv4 `--resolve`/ `--connect-to`, again both proxy and TUN. Live selected controller remains same. The real Python `awg-mihomo-service-check.py` `fetch` (urllib via forced proxy) and curl were then interleaved: **16/16** API/web HTTPS successes (OpenAI 401 / ChatGPT 403). No cause identified for prior intermittent EOF; cannot infer underlying uptime from a short successful burst. HTTPS YouTube 200 **does not establish 24 decoded frames**.
- **Interpretation:** proven *time-varying* result on same endpoint; repeated one-shot TLS EOF / cold-start timeout is insufficient evidence to quarantine a node for hours. Candidate causes include transient underlay/TLS connection behavior, DNS/backend-selection differences, load from isolated shadow probes, endpoint service instability, YouTube API anti-bot. None individually proven. A fixed-IP test changes destination selection (preserves SNI), so it is useful for diagnosis but not a substitute for normal-domain and live-client tests. Numerical probability of a real prolonged outage is not estimable from these samples. The standalone IP_CONNECT diagnostic itself alternated PASS and TLS_FAILED on the same live proxy.
- **Release gate remains OPEN:** determine failure timing/correlation with Hot Pool without touching active AWG, retain candidate PASS/SUSPECT/UNKNOWN distinctions rather than a false hard FAIL, confirm 24-frame YouTube decode on exact selected node and fresh OpenAI/ChatGPT HTTPS with consistent scope, then actual Pi TUN, MikroTik LAN client, failover/double failure/rollback. Do not merge/release PR #115 on these diagnostic bursts. DNS independence, Selective FAIL-OPEN, Transit FAIL-CLOSED, SSH/SSTP all preserved.

### Isolated service-scan numeric-IP false blocker (2026-10-18, after standby repair)

- **Real failure:** on `awg-upgrade` after `standby-repair`, the selected Shadowsocks node reached OpenAI via `mihomo0` and local proxy (both HTTPS HTTP 401) with AWG still active in tables 100/101. Yet a root `awg-mihomo-smart service-scan --node <selected>` at 21:05 reported `SERVICE_ELIGIBILITY=UNKNOWN`, all three services `UNKNOWN`, `SERVICE_REASON_CHATGPT_WEB=ip_connect_unverified`, `SERVICE_REASON_YOUTUBE_VIDEO=not_run_ip_connect`, `SERVICE_SCAN_EXIT=1`. A fresh 24-frame decode for this exact instance was **NOT performed**. Existing Hot Pool separately recorded real video24 PASS on this node, but this is historical evidence, not proof of the new run.
- **Read-only independent check:** standalone numeric-IP probe on the *live* Mihomo proxy and Pi-bound TUN first reported `2/2 PASS`; repeated later, the exact proxy numeric-IP diagnostic returned `TLS_FAILED` at the first IP while ordinary OpenAI HTTPS over proxy/TUN remained HTTP 401. Root cause of a particular shadow failure is not proven, because its `SERVICE_IP_CONNECT_REASON` was omitted by the operator's original grep. **Numeric-IP CONNECT and domain-based HTTPS are not interchangeable proofs.**
- **Source diagnosis:** unlike the Hot Pool isolated scanner, old `src/awg-mihomo-smart service-scan` considered controller visibility sufficient to immediately run `IP_CONNECT` and unconditionally rejected any non-PASS before performing OpenAI, ChatGPT or 24-frame YouTube. Hot Pool already has bounded HTTPS cold-start readiness and treats numeric-IP diagnostic as telemetry, not as the media/network eligibility gate.
- **Draft #115 source fix, uninstalled:** `service-scan` now waits at most 20 seconds / 4 cold-start HTTPS attempts on its isolated proxy before proceeding. It always reports `SERVICE_CONNECT_STATE`, attempts/wait; when ready it reports a validated `SERVICE_IP_CONNECT_STATE`, `SERVICE_IP_CONNECT_REASON` and explicit `SERVICE_IP_CONNECT_POLICY`. In Transit the numeric-IP probe is diagnostic only; OpenAI + ChatGPT + **actual 24-frame decode** still must pass the medium network gate and the selected live node still requires a real TUN postcheck before use. **Selective** retains strict numeric-IP CONNECT eligibility; missing/invalid mode fails closed. No browser checks, no old primary YouTube HTTP or Range test, no DNS/route change. This source fix is not a runtime PASS.
- **Source checks on current test Pi's isolated source checkout:** `tests/test_mihomo_ip_connect_gate.py` 11/11; `tests/test_mihomo_ip_connect_probe.py` 10/10; `tests/test_mihomo_standby_repair.py` 7/7; `tests/test_transport_tun_preflight.py` 7/7; `tests/test_ready_auto_canary.py` 23/23 — PASS. Actual root re-test of corrected `service-scan`, selected exact-node HTTPS/YouTube24, LAN through Mihomo, failover/rollback and full PR CI are **OPEN**. Do not merge/release based on rootless tests.
- **Next step:** on test Pi only, run the reviewed exact PR source `sudo python3 -B src/awg-mihomo-smart service-scan --node "$node"` with active AWG checked before/after and record complete **sanitized** `SERVICE_CONNECT_*`, `SERVICE_IP_CONNECT_*`, `SERVICE_CHECK_*`, and `SERVICE_REASON_*` statuses. Do not install the draft or switch active transport until the result is independently verified.

### Clean-install Mihomo selected-node TLS EOF and guarded recovery (2026-10-18)

- **Original failure REPRODUCED on new Debian 13 ARM64 test Pi after reboot (read-only probes):** active transport AWG, Transit SAFE, table100/101 default `awg0`. Installed Mihomo and `mihomo0` link were up, but OpenAI, Cloudflare, ipify HTTPS through **Pi-bound `mihomo0`** all failed TLS EOF. Loopback mixed proxy `127.0.0.1:7890` likewise failed. Redacted Mihomo journal confirmed 50 attempts at one selected node's TCP endpoint failing `ECONNREFUSED`; independent TCP connect to that endpoint also returned `Connection refused`. Its underlay route was DIRECT via `eth0` (not AWG). AWG-bound OpenAI API HTTP 401 and ipify HTTP 200 passed. This proves an unavailable **selected endpoint**, not a universal Mihomo TUN defect, and does not prove that other subscription nodes work.
- **Underlying policy nuance:** conservative transport AUTO intentionally keeps healthy AWG selected (no performance-driven automatic return); Mihomo node AUTO only runs failure recovery while Mihomo is active. Consequently a previously selected Mihomo node can become stale while AWG is active. An active Mihomo's proxy-only transport health also did not independently prove the Pi-bound TUN.
- **Source fix in draft PR #115 only (NOT installed or hardware-PASS):** `src/awg-transport` now requires verified Pi-bound `mihomo0` OpenAI HTTPS (HTTP 401) as part of live Mihomo health, before selecting Mihomo and again after a route reload (existing ERR rollback). The normal health loop performs one bounded probe; activation attempts up to two. No inherited proxy, fake-IP, DNS hijack or browser test. `src/awg-mihomo-node-policy standby-repair` is an explicitly requested one-shot attempt to replace an unverified Mihomo *standby* while healthy AWG remains active; first verifies active AWG health and **both table100/101 through awg0**, uses existing READY-priority/fresh service-scan, and then tests actual Mihomo TUN HTTPS+global IPv4. If exhausted it may stop only the unused Mihomo service; **must never call Transit disable or Selective failopen while AWG is active**. `src/awg-menu` offers this action with Russian confirmation/progress and a clear result.
- **Verified rootless against the new test Pi's isolated source checkout:** `test_transport_tun_preflight.py` **7/7**, `test_mihomo_standby_repair.py` **7/7**, existing `test_ready_auto_canary.py` **23/23**, `test_ready_auto_persistence.py` **3/3**, `test_menu_ux.py` **8/8**, existing `test-menu.py` and `test-transport.sh` PASS, Bash syntax PASS. Root-required `test-transport-switch.sh` and `test-selection.sh` could not run via unprivileged Remote Desktop Commander; these remain OPEN. New Python regressions wired into CI, **full CI not yet confirmed**.
- **Next hardware acceptance (OPEN):** independently recover a service-qualified standby node via `standby-repair` with root on the *test* Pi only; confirm AWG active/Transit SAFE/routes100+101 before/during/after, real HTTPS 401 and public ipify through Mihomo TUN, exact node, independent DNS/SSH/DC. Then test guarded operator transition to Mihomo, true Pi TUN/ChatGPT/YouTube24 and separately MikroTik LAN-forwarded client plus double-outage FAIL-CLOSED/recovery. The installed Pi still uses the previous transport/node-policy scripts; no route/transport change was made during source tests. No release/merge until these real gates pass.
- **Hot Pool progress on the new Pi:** READY 0/4 first reboot cycle, 1/4 at 19:49 and 20:02 (+07), shortlisted/live health counts distinct from service-qualified READY. The confirmed READY does NOT automatically prove the currently selected, unavailable node healthy.

### Russian SSH dialog and first-run menu acceptance

- **Implementation in draft PR #115, not yet installed on test/production Pi:** `install.sh` already installs `src/awg-menu` on both clean installs and upgrades. Updated TUI uses one native `dialog` first-transport setup instead of dropping the operator into an unexpected text SSH wizard; AWG file/text import uses the existing guarded `awg-first-run awg-file` activation after checks. Interactive LAN reconfiguration keeps the necessary console handoff but now warns explicitly.
- **Clean-install UI contract:** when the VPN engine binary is absent show **«не установлено»**; when installed with no profile show **«не настроено»**, not a broken VPN. Without an active transport show **«ожидает настройки»**; distinguish a configured but stopped service from an actual failed operation, and show Transit guard FAIL-CLOSED rather than calling an unconfigured system broken.
- **Progress and error UX:** non-interactive operations display a heartbeat, elapsed time and source-reported pool phase/progress where available. Both live and staged node preparations use the same progress window. Result dialogs explicitly say **«ВЫПОЛНЕНО»** or **«ОШИБКА (код …)»**, retaining the technical log underneath. A failed gateway/all update must not falsely restart the menu as if upgrade succeeded. AUTO transport help does not deny separate Mihomo node failover; AWG fallback text is conditioned on a configured working AWG.
- **Screen sizing/READY:** Russian text uses a menu-local `C.UTF-8` fallback when SSH inherited a non-UTF-8 locale, without changing the OS locale. All `dialog` calls are capped to the actual interactive SSH tty; oversized status/dashboard prompts reduce menu item height without losing selection/scroll. Terminals below 78×22 receive a clear diagnostic. The home screen displays real **two-proof READY/target** from the read-only Hot Pool status, or **«ожидает подписку»** on fresh install.
- **Rootless verification on test Pi, 2026-10-18:** `tests/test_menu_ux.py` **8/8 PASS** using simulated 80×24 and 140×40 controlling TTYs and a clean-install no-profile fixture; existing `tests/test-menu.py` PASS; **16 additional** installer/selection/system-node Python tests PASS; Bash syntax PASS, prior READY/Hot Pool packaging checks PASS. New UI test is wired to CI. `test-first-run.sh` could not execute without root/TTY from the remote connector, and a real operator-driven visual tour on the test Pi, genuine fresh Debian 13 install, and reboot are **still pending**, so do not mark the full UI hardware/release gate PASS.
- **No live routing changes:** verified on test Pi after source checks: table 100/101 still `awg0`, AWG/selection monitor/dnsmasq/SSH/DC active, zero failed units. Installed `/usr/local/sbin/awg-menu` remains the previous version until a separately controlled installer upgrade.

### Clean-install Node22 npm/npx and Desktop Commander gate (2026-10-18)

- **Observed by user on fresh Debian 13 ARM64 install of draft #115:** `node -v` reported `v22.16.0`, while `npm` and `npx` were not found. Root cause: Stage18/System Node installed only the pinned Node executable; Desktop Commander was intentionally opt-in, and old `awg-dc prepare` would use APT packages (potentially pulling the separate Debian Node20). This is a reproducible *provisioning gap*, not evidence of VPN dataplane failure.
- **Updated draft source only:** `scripts/awg-system-node.sh npm` extracts bundled npm and npx from the **same SHA256-pinned official Node 22.16 ARM64 tarball** as Stage18. It checks the system Node22 SHA, the full archive SHA, both JS CLI entrypoints, executable resolution, and refuses to overwrite unrelated `/usr/local/bin/npm` or `npx`. `install.sh` attempts this on *fresh install* after verified Node22; failure warns rather than aborting the optional DC path. On verified Node22 hosts, `awg-dc prepare USER` tries the pinned helper before legacy Debian APT fallback; normal-user OAuth and remote-agent enablement remain opt-in.
- **Acceptance still OPEN:** full CI for this draft HEAD is not yet reported, official tar extraction and npm/npx CLI have **not** been run on the freshly installed Pi, and remote pairing/systemd/reboot/DC read-only remote execution have not passed. Recheck `node -v; npm -v; npx -v`, `sudo awg-dc prepare USER` cache, `awg-dc pair` (user consent), `sudo awg-dc enable USER`, and reboot recovery. Confirm no change to AWG/Mihomo, policy routes, independent DNS, SSH, or SSTP. Do not claim the clean-install gate PASS on user report alone.

### Fresh install timezone gate

- Fresh Debian 13 ARM64 install defaults to **`Asia/Novosibirsk`** using `timedatectl` and installed `tzdata`; verify `timedatectl show -p Timezone --value` and `date` output.
- Explicit `AWG_PI_TIMEZONE=Etc/UTC` (or another valid IANA zone) overrides only the fresh-install default. Invalid or absent zones fail clearly, without changing timezone or silently continuing.
- Existing gateway upgrades preserve their previously selected timezone, including `Asia/Bangkok` or any other zone. The TUI's timezone change function stays available.
- Automated isolated tests in `tests/test_installer_timezone.py` must pass in CI, plus one real fresh-install system-level check before stable release.

## 2. Existing v1.2.0 Pi upgrade gate

Target hardware:

- Raspberry Pi 4 / Debian 13 ARM64.
- existing stable v1.2.0.
- existing AWG configuration preserved.
- existing operating mode preserved.
- existing OpenCCK/domain/client state preserved.

Before upgrade record:

~~~
sudo awg-route status
sudo awg-transport status 2>/dev/null || true
sudo awg show
ip -4 rule show
ip -4 route show table 100
ip -4 route show table 101
systemctl --failed --no-pager
~~~

Upgrade from an RC/develop ref only with an explicit ref. Do not change the
stable tag until the release gate is complete.

Expected after upgrade:

- /etc/awg-pbr/version is 1.3.0.
- active transport is still awg.
- the previous Selective/Transit mode is unchanged.
- awg0 handshake is fresh.
- table 100/101 and mode semantics remain correct.
- Transit guard is SAFE in Transit mode.
- Mihomo components are installed passively; Mihomo is not selected
  automatically.
- no failed systemd units.

## 3. Upgrade rollback coverage

awg-update backup/restore must include the complete v1.3 state:

- /etc/awg-pbr
- /var/lib/awg-pbr/mihomo
- /var/lib/awg-pbr/traffic
- /usr/local/bin/mihomo when present
- /usr/local/lib/awg-pi
- awg-transport and awg-traffic
- all awg-mihomo-* helpers
- Mihomo systemd service/update units
- selection-monitor and traffic-accounting units

A failed gateway update must restore the previous version and leave the gateway
usable on the previous transport.

## 4. Mihomo first-run onboarding

On a clean Debian 13 ARM64 install, **installation completes before VPN
onboarding**: neither AWG .conf nor Mihomo subscription is present, and
\`install.sh\` never launches a profile-input wizard. The completed installation
must be \`Selective + transport=unconfigured\`, with both engines, Stage18,
FFmpeg/FFprobe, yt-dlp and media dependencies installed. READY and Hot Pool
SHADOW timers may be enabled, but run no provider-dependent network tests
until a subscription is explicitly supplied. The menu must provide **post-install**
first transport onboarding for either AWG or Mihomo and only then optional
Transit mode activation. Existing-install upgrades still preserve configured
nodes and transport priorities.

For Mihomo first-run the interactive flow must support:

1. subscription URL or local/pasted provider input;
2. provider profile/format validation;
3. safe live-node listing;
4. exact selection of the first node and one resolved IPv4 endpoint;
5. optional ordered exact-node fallback chain (2+ explicit nodes);
6. activation of Mihomo as the first transport;
7. Operating Mode selection only after a working profile has been supplied
   (no Transit activation on an empty fresh install).

For a provider that is not reachable DIRECT, AUTO bootstrap must be able to use
an already healthy transport. AUTO bootstrap order is:

1. DIRECT through the normal Pi LAN/uplink;
2. the currently selected healthy transport, if one exists;
3. other configured healthy transports explicitly supported by the bootstrap manager.

Router-side SSTP/VPN is not a required bootstrap dependency. Pi-originated
transport/control traffic must retain the gateway-wide DIRECT invariant so that
a new transport is not accidentally configured through itself.

Required checks:

- subscription URL can be entered through the protected menu flow;
- full URL/token is not echoed in status;
- local provider-file import works without network;
- invalid/empty provider never replaces the working cache;
- failed refresh leaves the last valid provider cache intact;
- Last fetch path reflects the successful bootstrap path;
- declining node failover leaves Mihomo node policy MANUAL;
- accepting it saves only the exact ordered node names entered by the user.

### Provider adapter independence gate

v1.3.0 must not depend on Citadel/Remnawave or on one subscription encoding.
Every raw provider input is normalized into the same internal Mihomo
`proxies:` provider before node selection or runtime preparation.

Required adapter formats for v1.3.0:

- native Mihomo/Clash YAML with a non-empty `proxies:` list;
- plain `vless://` URI subscriptions;
- Base64 or URL-safe Base64 containing a VLESS URI subscription.

AUTO format detection is the default. The operator must also be able to force
`mihomo`, `vless` or `base64` manually when autodetection is ambiguous.

For VLESS URI conversion the supported release baseline is:

- transport: TCP, WebSocket, gRPC;
- security: none, TLS, Reality;
- common SNI, fingerprint, flow, ALPN, Reality public-key/short-id and
  WebSocket/gRPC options.

Unknown transport/security modes must fail closed at the adapter: they must not
silently drop URI parameters or replace the last known-good provider cache.

Before stable release, hardware/release evidence must include at least:

1. one native Mihomo YAML provider path (Citadel/Remnawave is acceptable here);
2. one **non-Citadel provider format** using plain VLESS URI or Base64 VLESS;
3. both inputs normalize to a safe provider cache and expose nodes through the
   same `node list / node prepare / node select` workflow;
4. a format mismatch or unsupported VLESS mode is rejected without changing the
   working cache.

## 5. Provider/node discovery

After a valid provider cache exists:

~~~
sudo awg-mihomo-configure node list
~~~

The list must expose only safe metadata needed for selection, such as node name,
type, server and port. It must not expose UUIDs, Reality keys, short IDs,
passwords or full private subscription URLs.

Prepare a candidate:

~~~
sudo awg-mihomo-configure node prepare "<node name>"
~~~

Resolve one IPv4 transport endpoint and verify that endpoint independently of
the expected public egress IP.

## 6. MikroTik DIRECT protection

All Pi-originated transport/control traffic must bypass router-side SSTP/VPN
policy. This gateway-wide invariant replaces per-endpoint MikroTik rules for
normal node changes.

For every selected Mihomo node, verify that its resolved endpoint uses the
normal main route through the home router/LAN and never recursively traverses
the Pi transport, SSTP, or another VPN path. The same invariant applies to AWG
transport endpoints and bootstrap/control downloads.

Do not disable SSTP as part of this test. SSTP remains the priority management
link and should not be disturbed by transport validation.

## 7. Manual/Fixed node selection

v1.3.0 ships with MANUAL and FIXED exact-node policy.

FIXED is an explicit one-way ordered chain. Only nodes after the current exact
node may be tried automatically; the chain never wraps back to an earlier node.
Country inference is disabled. A healthy current node is sticky and there is no
performance-based return to a previous node.

Example release chain:

~~~text
Finland -> Estonia -> Latvia -> Sweden
~~~

If the last allowed node fails, exact-node recovery is exhausted and transport
selection gets the next chance (for example Mihomo -> AWG).

The selected node must be applied transactionally:

1. provider cache already valid;
2. candidate node found;
3. endpoint resolved;
4. gateway-wide DIRECT protection confirmed;
5. runtime config rendered;
6. mihomo -t succeeds;
7. Mihomo service becomes healthy;
8. dataplane/health monitoring is restored.

If node reconfiguration fails, the previous working node/config/cache must stay
usable. The TUI and fresh-install wizard must both support configuring the full
ordered chain, not only one primary/fallback pair.

## 8. AWG -> Mihomo hardware switch

Only after sections 1–7 pass:

~~~
sudo awg-transport select mihomo
~~~

Expected:

- mihomo0 exists.
- active transport reports mihomo.
- Mihomo health is healthy.
- selected VLESS/Reality endpoint is connected DIRECT through MikroTik.
- public egress matches the selected node/provider expectation when that
  expectation is configured.
- Transit mode remains FAIL-CLOSED.
- Transit guard remains SAFE.
- Selective mode retains FAIL-OPEN semantics.
- DNS/OpenCCK behavior is unchanged.

Record:

~~~
sudo awg-route status
sudo awg-transport status
ip -4 rule show
ip -4 route show table 100
ip -4 route show table 101
ss -ntp
systemctl --failed --no-pager
~~~

## 9. Mihomo -> AWG rollback switch

Verify the normal return path:

~~~
sudo awg-transport select awg
~~~

Expected:

- active transport is awg.
- table 100/101 point to the AWG transport as appropriate.
- AWG handshake remains fresh.
- Transit guard is SAFE in Transit mode.
- user traffic works through the original v1.2-style AWG path.

This switch is required before the release candidate is accepted.

## 9a. Transport selection policy gate

Transport selection is independent from Mihomo node selection.

Required modes:

- MANUAL: no automatic transport switching.
- FIXED: explicit primary plus fallback order, triggered only by repeated health
  failure. A healthy fallback is sticky; there is no automatic failback.
- AUTO: explicit allowed transport order, availability-only. It must never
  switch a healthy current transport for latency, throughput, preference or
  performance reasons.

Hardware evidence must cover both AWG -> Mihomo and Mihomo -> AWG failover with
a stopped standby backend, plus conservative AUTO stickiness after the alternate
backend recovers.

Exact-node recovery has priority while active transport is Mihomo. Only after
the ordered node-chain is exhausted may transport-level failover run.

### Current test Pi hardware transport-failover evidence (18 October 2026)

- **Selective/FIXED, AWG → Mihomo:** on `awg-upgrade-test`, the normal selection monitor logged `Automatic failover: awg -> mihomo (mode=fixed)` at 13:24:08 +07, about 45 s after stopping AWG. Real `mihomo0` Pi-bound HTTPS and table 100 passed; the independent restore guard was disarmed after baseline recovery.
- **Transit/AUTO, AWG → Mihomo:** temporary root-only guarded test stopped `awg-quick@awg0` at 13:53:04 +07. The normal monitor logged `Automatic failover: awg -> mihomo (mode=auto)` at **13:53:38** (34 s). With AWG down, the nft Transit forward guard retained its drop policy and did not contain an unrestricted DIRECT accept rule. After switchover, tables 100/101 used `mihomo0`; unauthenticated OpenAI API over the real TUN returned expected HTTP 401. After AWG restarted as standby, healthy Mihomo remained selected for 24 s (sticky AUTO). At 13:54:14 the originally selected **Transit/AUTO `awg,mihomo` with AWG active** was restored, no pending guard timer, and SSH/DC/DNS healthy.
- **Installer integration:** the source selector, transport and Transit guard are already installed by `install.sh`; the two temporary root test harnesses are deliberately **not** shipped as runtime daemons. Upgrade now checks SHA256 of the operator's existing transport AUTO/FIXED order and Mihomo node/READY policies before and after installation; the new rootless test exercises the actual AUTO monitor with a cold Mihomo standby, and is part of CI.
- **Still OPEN:** real marked MikroTik LAN-client attribution, actual packets blocked during *double transport* failure (Transit FAIL-CLOSED), reverse Mihomo-node exhaustion→AWG, clean Debian 13 ARM64 install, reboot and authenticated app/YouTube 24-frame service acceptance. Successful Pi-bound HTTPS and nft rule inspection are **not** a LAN PASS.


## 10. Provider outage/cache test

With a valid cache already present, make the provider URL temporarily
unreachable or use an isolated test namespace/mocked fetch failure.

Expected:

- Mihomo can start from the last valid cache.
- provider refresh reports failure without deleting/replacing the cache.
- active transport remains healthy if the selected node itself is reachable.

## 11. microSD/write sanity

Mihomo runtime logs and traffic accounting must not introduce persistent
high-volume writes.

Verify that:

- runtime logging is warning-level or lower-volume;
- temporary/test logs use tmpfs where practical;
- no high-frequency provider updater timer was introduced;
- provider updates are periodic and atomic rather than continuously rewriting
  cache files;
- transport traffic is sampled into /run (RAM);
- the first sample establishes a baseline and does not claim interface bytes
  accumulated before accounting was enabled;
- persistent traffic state is checkpointed no more often than the configured
  low-write interval (default 21600 seconds / 6 hours), plus initial baseline,
  clean shutdown and period rollover;
- awg0/mihomo0 recreation is detected by interface identity;
- reboot is detected by boot identity even if Linux reuses the same interface
  index, so counter resets do not silently corrupt today/month totals.

## 12. Release acceptance

A v1.3.0 RC is acceptable only after all of the following are true:

- CI is green.
- existing v1.2.0 upgrade on the real Pi passes.
- AWG remains unchanged immediately after upgrade.
- blank clean-install completes without importing or asking for VPN profiles;
  only afterward can first-run via \`awg-menu\` choose AWG or Mihomo,
  then choose Transit if a working profile exists.
- first-run Mihomo onboarding selects the initial exact node and can save a
  multi-node ordered fallback chain interactively.
- blocked provider download succeeds through DIRECT-first AUTO bootstrap with
  healthy Pi-transport fallback when DIRECT is unavailable.
- provider adapters pass native Mihomo YAML plus at least one non-Citadel
  VLESS/base64 format.
- manual node selection succeeds with gateway-wide Pi transport/control DIRECT
  protection.
- the ordered exact-node chain advances only forward and exhausts into
  transport-level fallback.
- FIXED AWG -> Mihomo and Mihomo -> AWG failover both succeed from realistic
  standby states.
- conservative AUTO switches only on repeated health failure and retains a
  healthy current transport after the alternate backend recovers.
- Selective remains FAIL-OPEN and Transit remains FAIL-CLOSED throughout all
  transport/node transitions.
- the TUI exposes the system dashboard, timezone control, unified VPN/OpenCCK
  destination entry, full ordered node-chain editor and traffic statistics.
- today/month transport traffic accounting survives interface recreation,
  samples in RAM and uses low-frequency persistent checkpoints.
- failure/rollback scenarios preserve connectivity and cached state.
- no secrets appear in status/menu/test evidence.
- no unexpected microSD write regression is observed.

Only then should the v1.3.0 tag/release become the stable updater target.


## 13. Raspberry Pi live evidence — 2026-10-08

Hardware/live validation on Raspberry Pi 4, Debian 13 ARM64, LAN
`192.168.112.0/24`, Pi `192.168.112.34`, MikroTik `192.168.112.1`.
Validated code head: `bceb06847f9ec273399bf97c1cf48882d431d591`.

### CI and local regression

GitHub Actions run `37734894001` passed both jobs:

- `shell`: Bash syntax, ShellCheck and all unit/regression tests;
- `awg-v31`: pinned AWG v3.1 build and real isolated profile preflight.

The same Pi also passed the targeted local regression gate:

- post-install first-transport wizard (AWG and Mihomo onboarding);
- existing transport is never silently replaced;
- FIXED/AUTO transport-selection policy;
- exact-node FIXED validation, no wrap-back and exhaustion behavior;
- low-write traffic baseline, deltas, interface recreation, rollover and reboot
  identity handling;
- TUI/menu regression.

### Live UX/traffic deployment

The v1.3 UX completion was deployed transactionally with backup
`/root/awg-v13-ux-pre-20261008-125710`.

Post-deploy invariants:

- Operating Mode: Transit;
- active transport: AWG, healthy;
- Transit guard: SAFE;
- transport selection: MANUAL;
- Mihomo node policy: MANUAL;
- Mihomo standby: inactive;
- `awg-traffic.service`: enabled and active;
- no failed systemd units.

Installed `awg-first-run`, `awg-menu`, `awg-route`, `awg-update`,
`awg-traffic` and `awg-traffic.service` matched the repository blobs.

Traffic accounting started from a zero baseline instead of claiming historical
`awg0` bytes. A controlled AWG health probe produced a 1.48 KiB delta. The
runtime state in `/run` changed while the persistent state mtime stayed
unchanged, confirming that normal samples are RAM-only and do not write the
microSD before the low-write checkpoint.

### Live transport failover

FIXED `AWG -> Mihomo` passed with Mihomo initially stopped:

- automatic switch occurred after repeated health failure;
- `table 100` moved to `mihomo0`;
- Mihomo endpoint `45.86.66.170` stayed DIRECT through the LAN router;
- observed Mihomo proxy egress was `45.86.66.170`;
- Transit guard remained SAFE;
- simulated Transit FAIL-CLOSED and restore both passed;
- final baseline returned to AWG / MANUAL with Mihomo inactive.

Reverse FIXED `Mihomo -> AWG` also passed:

- AWG remained a healthy standby;
- automatic switch occurred after repeated Mihomo health failure;
- fallback AWG stayed sticky and did not automatically return to Mihomo;
- FAIL-CLOSED and restore both passed.

Conservative AUTO passed in both directions:

- AWG failure switched to Mihomo only after repeated health failure;
- recovering AWG did not move a healthy current Mihomo;
- Mihomo failure switched to AWG only after repeated health failure;
- recovering Mihomo did not move a healthy current AWG;
- performance optimization remained disabled;
- FAIL-CLOSED and restore passed;
- final baseline returned to AWG / MANUAL / Mihomo inactive.

### Exact-node chain evidence

The live selection-monitor journal records the explicit one-way chain:

~~~text
🇫🇮 Finland -> 🇪🇪 Estonia
🇪🇪 Estonia -> 🇱🇻 Latvia
🇱🇻 Latvia -> 🇸🇪 Sweden
~~~

After the last exact node was exhausted, transport fallback `mihomo -> awg`
occurred. This provides live evidence for ordered exact-node recovery before
transport-level fallback and no country inference. The working baseline was
subsequently restored to Mihomo node policy MANUAL with Finland selected.

### Additional live multi-protocol validation — 2026-10-09

The same Raspberry Pi 4 / Debian 13 ARM64 stand was then used to validate the
final Mihomo health-pool and multi-protocol work on the public
`Au1rxx/free-vpn-subscriptions` Clash provider.

The provider contained 1772 nodes. A full all-protocol isolated scan completed
in 15m16s and found 188 healthy nodes:

- Trojan: 81 healthy;
- Hysteria2: 45 healthy;
- VLESS: 30 healthy;
- VMess: 18 healthy;
- Shadowsocks: 14 healthy.

Protocol-scoped scanning was also validated. For example, the same provider
contained 786 VLESS nodes and the isolated VLESS scan found 38 healthy nodes
without disturbing the live transport.

Real runtime activation was confirmed for all protocol filters exposed by the
v1.3 TUI:

- VLESS;
- Trojan;
- Hysteria2;
- Shadowsocks;
- VMess.

The all-protocol AUTO node policy was then tested end-to-end. With VMess active,
`awg-mihomo-pool best live` selected a Hysteria2 node, and
`awg-mihomo-node-policy failover` switched
`vmess-197954839 -> hysteria2-1725316146`. The previous node entered
cooldown, the new public egress changed, and the active Mihomo transport
remained healthy. This confirms that AUTO can choose the best healthy node
across protocol types when `MIHOMO_POOL_PROTOCOL=all`.

Earlier in the same validation sequence, automatic exact-node recovery also
switched a failed Estonia node to Sweden after repeated active-Mihomo health
failure, without transport fallback. This confirms selection-monitor integration
with the health pool and cooldown behavior.

The daily provider refresh path was upgraded to a transactional safe auto-refresh
and tested against the live public subscription. An unchanged refresh reported
`MIHOMO_PROVIDER_AUTO_REFRESH=UNCHANGED`, created no candidate, preserved the
current node and left the Mihomo service/transport healthy. Changed-provider
promotion, rollback and MANUAL/FIXED/AUTO policy cases remain regression-tested
in CI.

The TUI was also hardened so an already-applied candidate is not confused with
a missing prepared profile: after successful commit the candidate is promoted
to live and cleared, while the menu explicitly shows whether a prepared profile
exists and directs live search/filter/statistics to the live-node menu.

### Still required before stable v1.3.0

**Important scope correction (2026-10-17):** Sections above include historical
passing hardware tests from an earlier configured installation. On the **current
test installation** (`awg-upgrade-test`), AWG has **not yet been connected**
and the MikroTik Transit forwarding path has **not yet been accepted**.
Historical AWG/Transit/failover PASS results must **not** be carried over as
evidence that this installation is ready.

The stable release is blocked by **all five** of these gates (plus the
feature-specific pending Mihomo READY/TUN/LAN checks):

1. **Current test Pi: configure and accept AWG as a real transport.** Keep the
   existing Mihomo selection and DIRECT control plane intact; back up before
   changing `awg0.conf`. Check compatibility and endpoint DIRECT, secure
   configuration permissions, interface up, fresh handshake, routed external
   HTTPS and service availability, health classification, service restart and
   failback. Use an operator-approved profile only. Do not claim AWG standby
   is configured/healthy merely because its binary or unit is installed.
2. **Current test Pi: end-to-end MikroTik Transit hardware gate.** After taking a
   baseline and confirming the SSTP management route, route **one designated**
   LAN test client through MikroTik -> Pi -> Mihomo and verify the actual client
   egress, HTTPS to YouTube/ChatGPT, correct DNS behavior, NAT, policy table,
   DIRECT exemptions and Transit guard. Repeat with active AWG once its
   handshake/data path is confirmed. Deliberately simulate loss of the active
   transport: selected Transit traffic must remain FAIL-CLOSED, while
   SSH/router/SSTP management survives. Restore baseline after each scenario.
   Do not alter the MikroTik's global routing or disable the priority SSTP
   management connection during a trial.
3. **One destructive fresh install** from a clean Debian 13 ARM64 image using
   the current v1.3 installer head (on a **separate SD/SSD**, retaining the
   old card read-only). Finish the full installer **without any AWG profile or
   Mihomo subscription** and verify \`Selective + transport=unconfigured\`.
   Verify both engines, Node.js 22.16 / native WebSocket, ffmpeg/ffprobe,
   yt-dlp, Stage18, Hot Pool/READY (idle without provider), independent DNS,
   optional DC onboarding and clean reboot. **Only after completion**, add
   the first real AWG/Mihomo profile through \`awg-menu\`, then check
   FIXED/AUTO, Transit activation and service-dependent Hot Pool gates.
   Also test configured-state upgrade/rollback with the previous user
   preferences and safe DC autostart.
4. **One live non-Citadel provider** using the plain VLESS URI or Base64 VLESS
   adapter path. The earlier live Clash YAML test does not close this gate.
5. **Reboot/persistence acceptance** on the newly configured test installation:
   AWG/Mihomo services, DNS, Selective/Transit mode, standby health, exact
   selected node, Hot Pool/Stage18 timers, system Node 22, DC pairing and
   non-root service, policy routes and direct management path must survive.
   Confirm service and client networking after reboot.

**Additional blockers before shipping `ready-auto` as unattended behavior:**
active proxy-health must not stand in for actual Pi TUN success, tested
`mihomo0` numeric-IP HTTPS must be distinguished from real forwarded LAN
traffic, recovery must wait boundedly for `fwmark 0x100` table 100 after
Mihomo restarts, and the real node-failover chain must proceed to a **healthy
AWG standby** when exhausted. Test a safe, independent rollback timer and
no unrequested auto-return. Both transports should be tested in Selective
and Transit, with actual LAN clients where each mode requires them.

Until all required current-install hardware gates and CI/upgrade/rollback
checks pass, keep PR #115 **DRAFT**, and keep `main` / the stable release
updater target at v1.2.0. No speculative PASS entries.

## 2026-10-20 Transit AUTO two-fault hardware evidence — test Pi only

On `awg-upgrade`, the authorized owner ran `scripts/awg-xray-transit-gate-from-awg.sh` with independently armed 600s/420s recovery timers. `TRANSIT_BASELINE=PASS`, `FAULT=MIHOMO_STOP`, `FIRST_RESULT=XRAY_TUN`, `XRAY_TUN_HTTPS=PASS`; then `FAULT=XRAY_STOP`, `SECOND_RESULT=AWG`, `SECOND_LAST_PREDICATE=PASS`. Before scripted rollback the observer confirmed AWG selected, healthy Xray/Mihomo shutdown, Transit guard SAFE, policy ACTIVE, VPN table READY, both route tables 100/101 through AWG, and HTTPS through awg0 PASS. Native Transit policy disable produced `TRANSIT_POLICY=DISABLED_FAIL_CLOSED` and `TRANSIT_FAIL_CLOSED_GUARD_STATE=PASS_NOT_PACKET_TEST`; reapply produced `TRANSIT_POLICY=ACTIVE`. Test reported `TRANSIT_XRAY_AUTO_FAILOVER=PASS_PI_TUN_AND_GUARD_ONLY`; two recovery layers and Selective restoration PASS. Independent posttest observation found AWG active, SSH/DNS/monitor active, Mihomo/Xray inactive, both tables through awg0 and zero failed services.

**Scope:** this is real test-Pi engine/TUN HTTPS and protective nft/policy state evidence, **not** a LAN-client packet-level FAIL-CLOSED test. No clean-install/reboot proof, no production media/MikroTik modification, and the restored native Mihomo node was **not live retested**. Xray experimental PR #141 remains separate from installer PR #115; do not call v1.3.0 released, merged, clean-installed, or fully accepted on this receipt alone.

### Unified subscription inventory and manual Xray selection (pending live gate)

The user-facing node list must show **all uniquely identified, supported Mihomo
and Xray profiles from the current loaded subscription**, including Xray profiles
with `UNTESTED` / failed basic network status. Visibility is not eligibility.
No false READY, network, TUN or LAN PASS is inferred from importing a profile.
Do not leak UUID, Reality keys, provider URLs or subscription credentials.
A rotated source URL or changed node count invalidates cached candidate proof
unless the exact transport fingerprint is unchanged.

The current candidate implements unified subscription inventory and an
isolated automatic scanner (provider-directory path watch plus periodic timer)
that checks bounded groups of Xray candidates after subscription import.
A dormant local Xray SOCKS alias is present in Mihomo's generated configuration
when the Xray core is installed; this does **not** start the Xray service.
**Guarded manual Xray activation code is now present in the candidate**, including
native/Xray previous-node snapshots, fresh-network preflight, bounded TUN probe,
independent watchdog and intended recovery. This is **not installed, hardware
validated or accepted** yet; the real manual transitions/rollback/reboot/LAN
release gate remains pending.
A separate root-only guarded manual transaction is required before exposing
"activate" in the TUI. It must provide a recoverable previous healthy Mihomo
or Xray node, independent timeout rollback/watchdog, fresh subscription-identity
validation, live TUN postcheck, LAN forwarding checks, safe reboot restoration,
and independent SSH/DNS/MikroTik/SSTP protections. It must handle Mihomo→Xray,
Xray→Xray, and where configured AWG→Xray without using the failed-incumbent
AUTO transaction to interrupt a healthy node.

Until the above transaction and negative tests pass on the **test Pi**, leave
manual activation disabled. Preserve Selective FAIL-OPEN, Transit FAIL-CLOSED
and the opt-in READY/Hot Pool/Xray AUTO policies. No PR merge or release PASS
is implied by passing inventory unit tests.

### 2026-10-21 candidate code verification (not a release acceptance)

Candidate `8266bb0` integrates Xray-core install, a bounded provider-change/periodic
background scanner, unified Mihomo/Xray catalog (including UNTESTED rows), a
dormant localhost SOCKS5 bridge rendered with Mihomo, and an explicit guarded
manual selection CLI. On `awg-upgrade`, **693 of 693 Python tests passed**,
Bash syntax, unit file parsing and real Mihomo binary config parsing checked. The current native/default node is preserved on clean import, and a saved Xray selection is mapped to the SOCKS alias only when the exact credential fingerprint matches; removed provider profiles never cause a dead alias to become the new default. The live installed menu remained the
prior candidate, Xray service inactive, ssh/dnsmasq/Mihomo active. No true manual
Mihomo→Xray→Xray→native transition, LAN-client forwarding, reboot persistence,
Transit/Selective live failover, or clean install of this revision was run.
Unit tests alone do NOT certify the rollback watchdog. No merge/release PASS.

### 2026-10-21 post-install Xray bridge application checkpoint

- Test Pi installed candidate `3943118`; user-confirmed root render with `XRAY_BRIDGE=PRESENT`, `DEFAULT_IS_XRAY=False`, `MIHOMO_TEST_RC=0` and active SSH/dnsmasq/Mihomo. **Running Mihomo controller still lacks alias**: upgrade did not automatically restart healthy TUN (intentionally).
- Installed background isolated Xray scanner path/timer active; actual service ran 5/5 Xray OpenAI HTTPS 401 probes successfully (basic proxy only). Xray live service inactive; no manual Xray selection or LAN/reboot tests yet.
- Existing full snapshot created by operator: `gateway-manual-20261021-095559-T51z9AsE/gateway-state.tgz`, `BACKUP=VERIFIED`, 124000831 bytes. Restore execution not independently tested.
- Test-only bridge reload helper in `scripts/awg-xray-bridge-reload-test.py`: user ran initial `preflight` (native TUN healthy and Transit SAFE, no restart). During review we identified a critical rollback failure: normal Mihomo ExecStartPre regenerates the new Xray bridge even if old config.yaml is restored. Fixed by a runtime-only, marker-checked systemd ExecStartPre override while restoring the exact original config; the override is removed after recovery. Mock guard/restore tests and full Python suite **707/707 PASS** at source commit `ce07458323b08edcb2365e62a62fd879cbb7dd39`. This newer helper is not yet installed; no real manual restart or rollback PASS is claimed. Use root-only pinned install then repeat preflight before supervised apply. Keep reboot blocked until after recovery validation.

### 2026-10-21 supervised Mihomo bridge activation: live verified, Xray switch pending

Operator installed the reviewed bridge-reload test helper on test Pi `awg-upgrade` and ran `preflight` and `apply`. Actual output: `BRIDGE_RELOAD_PREFLIGHT=PASS`, `ACTIVE_NATIVE_NODE=HEALTHY`, `TRANSIT_GUARD=SAFE`, `XRAY_BRIDGE_LIVE=PASS`, `PREVIOUS_NODE=UNCHANGED`, `TRANSIT_GUARD=VERIFIED`; local protected snapshot under `/var/backups/awg-gateway/xray-bridge-1792553379-648409`. After apply, independent read-only check confirmed running controller `BRIDGE_LIVE=True`, `BRIDGE_SELECTED=False`, original choice present in controller options, SSH/dnsmasq/Mihomo/health/selection monitor active, Xray inactive, both VPN policy routing tables default via `mihomo0`, and zero systemd failed units; no armed bridge rollback timer remained. This is a **live bridge reload PASS only**, not a tested forced rollback or an Xray TUN PASS.

The isolated Xray scanner had previously recorded 5/5 `NETWORK_OK` using HTTPS OpenAI probe on the Xray SOCKS sidecar. Those results are transient (600-second cache) and do **not** establish Xray as a live TUN node. Next gate: refresh one indexed Xray profile via `awg-mihomo-unified-nodes probe INDEX`, run `awg-xray-manual-switch preview INDEX`, review rollback and reboot behavior, then supervised first manual Xray activation/TUN test. Reboot and LAN forwarded traffic remain untested. No production SD or MikroTik changes.

### 2026-10-21 first manual Xray candidate preflight

After live Mihomo bridge reload PASS, the operator ran `awg-mihomo-unified-nodes probe 1` and `awg-xray-manual-switch preview 1`: `UNIFIED_PROBE_INDEX=1 ENGINE=XRAY BASIC_NETWORK=NETWORK_OK`, `XRAY_MANUAL_PREFLIGHT=PASS`, `XRAY_MANUAL_TUN=NOT_TESTED`. No Xray selection was made; SSH/dnsmasq/Mihomo/health monitor/selection monitor remained active, Xray service inactive, native node still selected. Independent routing checks show VPN mark rules 0x100/0x101 and both tables default dev `mihomo0`.

Review caught a silent policy mutation in the manual switch: on successful Xray selection the script was resetting node policy to manual and deleting the FIXED order. Corrected in source `742655a` to change the current transport exit only and preserve MANUAL/FIXED/AUTO/READY/Hot Pool policy files. Added a mocked successful-transition regression that asserts policy/order/READY byte preservation; rootless suite now **708/708 tests PASS** at `7517dd2a889dd38b3d9ba4e857b4055b0722fbc2`. Corrected manual helper is **not yet installed**; original root preflight belongs to previously installed helper, not the revised one. Next: pinned helper replacement, new probe/preview, then supervised `apply` with live TUN/rollback/Transit validation. No LAN/reboot or forced failure PASS claimed.

### 2026-10-21 first Xray manual apply: local SOCKS readiness race, rollback observed

Test Pi `awg-upgrade` manual activation of indexed Xray profile 1:

- `awg-mihomo-unified-nodes probe 1` reported `BASIC_NETWORK=NETWORK_OK`; `awg-xray-manual-switch preview 1` reported `XRAY_MANUAL_PREFLIGHT=PASS` and `XRAY_MANUAL_TUN=NOT_TESTED`.
- First supervised `awg-xray-manual-switch apply 1` returned **`XRAY_MANUAL_ERROR=NEW_XRAY_LOCAL_HTTPS_FAILED`** before the Mihomo controller switch. This is a **failed gate**, not Xray TUN PASS.
- Independent post-failure read-only check confirmed SSH, dnsmasq, Mihomo, health and selection monitor active, controller still on native Mihomo with Xray alias present but unselected; Xray service inactive, no pending Xray-manual watchdog timer, tables 100/101 default dev `mihomo0` and 0x100/0x101 policy rules present. This verifies the **observed safe post-error state**, not a forced watchdog recovery test.
- Sanitized systemd journal confirmed `awg-xray-vless.service` started 10:38:00.880, Xray-core 26.3.27 logged successful startup at 10:38:01.345, and controlled rollback stopped the service at 10:38:01.800 (about 0.45 seconds after core startup). No kernel/core crash was evident. The old transaction performed a single immediate HTTPS check without waiting for fixed port 17892 to listen; a startup/listener readiness race is **strongly suspected**, but old logs cannot independently prove which HTTP/curl error occurred.
- Corrected source in candidate branch: bounded 10-second service/listener wait at 127.0.0.1:17892, then at most two bounded HTTPS 401 probes before any native-to-Xray TUN selector change; explicit error categories `XRAY_SERVICE_NOT_ACTIVE`, `XRAY_SOCKS_PORT_NOT_LISTENING`, `XRAY_SERVICE_EXITED_DURING_HTTPS`, `XRAY_SOCKS_HTTPS_NOT_VERIFIED`. Existing native/Xray rollback guard preserved.
- Test-Pi source suite **713/713 PASS** including 14 targeted manual-transaction tests; corrected live helper **NOT INSTALLED OR LIVE RETESTED YET**. Next gate: pinned install only of revised manual helper, fresh candidate `probe 1` and `preview 1` before a supervised manual Xray apply and TUN/LAN/rollback/reboot verification. No MikroTik/production SD changes.


### 2026-10-21 first manual Xray activation — actual Pi TUN HTTPS PASS (not LAN/reboot)

On test Pi `awg-upgrade`, operator installed the revised guarded manual helper and ran `probe 1`, `preview 1`, then supervised `apply 1`. Output:
`UNIFIED_PROBE_INDEX=1 ENGINE=XRAY BASIC_NETWORK=NETWORK_OK`,
`XRAY_MANUAL_PREFLIGHT=PASS`, `XRAY_MANUAL_TUN=VERIFIED`,
`MIHOMO_NODE_POLICY=UNCHANGED`, `XRAY_MANUAL_REBOOT=NOT_TESTED`.

Independent **post-apply live** read-only checks at 10:50 +07 confirmed:
- Mihomo controller `AWG-XRAY-VLESS-LOCAL` **is the selected outbound** (`ALIAS_PRESENT=True`, `ALIAS_SELECTED=True`); Xray sidecar active, enabled for boot, running with 0 systemd restarts; Mihomo, SSH, dnsmasq, health and selection monitors active.
- Actual `curl --interface mihomo0 --noproxy '*'` to `https://api.openai.com/v1/models` returned HTTP **401**, curl exit **0**; separate local `curl --socks5-hostname 127.0.0.1:17892` to the same HTTPS endpoint also returned **401**, curl exit **0**. Loopback SOCKS listener `127.0.0.1:17892` present. No browser testing or rejected YouTube HTTP gate used.
- Both `fwmark 0x100/0x101` rules present and routing tables 100/101 default via `mihomo0`; 0 failed systemd units, no pending manual-switch watchdog timer.
- **Limitations:** privileged `awg-transit-routing status` (nftables forward guard) could not be independently read by the non-root remote agent after the switch; that specific guard remains to be checked as root. These are Pi-bound TUN and SOCKS observations, **not LAN-client proof**, nor a forced rollback/automatic failover/YouTube 24-frame decode/reboot or full clean-install acceptance. No production microSD or MikroTik configuration changes.

Next gate: root read-only Transit guard status and actual LAN-client experience while Xray is selected, followed by supervised Xray→native/FIXED preserving recovery, forced-failure watchdog validation, reboot and full v1.3.0 release matrix. Keep PR draft until all applicable gates are satisfied.

### 2026-10-21 menu repeat-Xray selection — failed UI transaction, watchdog recovery confirmed

After successful initial Pi-TUN activation, the operator tried manual Xray selection via `awg-menu` while Xray was **already the live selected outbound**. The menu reported generic exit code 2, not a successful switch. Independent unprivileged observation confirmed live Xray, Mihomo, SSH, dnsmasq and health service active; controller `AWG-XRAY-VLESS-LOCAL` selected; `mihomo0` HTTPS OpenAI 401/curl RC0; policy rules 0x100/0x101 via `mihomo0` intact. Journal showed Xray service restarts at 10:55:37 and 10:55:47 and a still-armed autonomous watchdog that fired at 10:58:52 and restarted Xray. Watchdog service result success, no pending timer afterward, Pi-TUN HTTPS passed afterward. Do **not** call menu or rollback path fully PASS: the transition itself failed; root-only snapshot phase, requested profile identity, and `XRAY_MANUAL_ERROR` detail remain to be inspected.

Safety correction **committed to candidate, not installed**: when the requested exact Xray profile fingerprint matches the currently active one and existing TUN HTTPS is healthy, return `XRAY_MANUAL_ALREADY_SELECTED=YES` with no service stop/restart/transaction/watchdog. Menu reports "already active" and exits, protecting the healthy channel. Different profile still requires guarded transaction. Targeted source tests **17/17 PASS** on Pi. Full suite **716 cases attempted, 22 failures and 4 errors** under real active Xray because existing mock fixtures inspect live Xray systemd state (`XRAY_ACTIVE_DEFER_TO_TRANSPORT_AWG`, `SERVICE_RUNNING_STOP_FIRST`); this is not a full regression PASS. Restore a separately isolated test environment rather than switching live Xray just for green test output. No production SD/MikroTik changes.


### 2026-10-21 Xray-to-Xray failed menu transition: root snapshot and regression repair

Operator root-only audit of failed menu transaction snapshot \`xray-manual-1792554937-677635\`: \`RECOVERY_PHASE=rolled_back\`, \`PREVIOUS_WAS_XRAY=True\`, **\`REQUESTED_SAME_XRAY=False\`**, \`MENU_ERROR=NOT_FOUND\`. Therefore the attempt targeted a **different Xray profile**, disproving the earlier same-profile re-selection hypothesis for this failure. Privileged \`awg-transit-routing status\` showed \`Transit guard: SAFE\`, \`Transit policy rule: ACTIVE\`, \`Transit VPN table: READY\`. Independent subsequent read-only checks found Xray still selected, Xray/Mihomo/SSH/dnsmasq/health and selection monitor active, mark 0x100/0x101 and tables 100/101 via mihomo0 intact and no pending manual watchdog. The watchdog executed ~10:58:52 and its service finished successfully. **Observed old-Xray restoration** is supported; a successful different-Xray transition is **not** supported.

The old menu displayed only exit code 2 and discarded its temporary capture; the previous snapshot had no persisted safe failure code. Exact failure root cause (new Xray SOCKS HTTPS, Pi-bound TUN, post-commit, or immediate recovery) cannot be recovered from that attempt. No unsupported assertion of root cause or Xray-to-Xray PASS.

Candidate source changes **not installed or live retested yet**: Xray manual transaction persists only sanitized \`failure_code\` / \`failed_at\` / \`rollback_failure_code\` and nonsecret checkpoint fields in the owner-only recovery snapshot, adds root-only \`diagnose\` that prints only safe fields, and performs bounded retry verification of the previous Xray TUN during recovery. Same exact-profile selection is idempotent by fingerprint and does not restart service; this is separate from the failed different-profile path. Dedicated regressions simulate different-Xray failure with successful and failed immediate recovery while ensuring the watchdog remains armed in the latter. Synthetic READY/AUTO/adapter fixtures were isolated from installed live Xray state, so CI no longer depends on Xray being off. **721/721 rootless Python unit tests PASS on test Pi with Xray live at commit \`e1003b264c566e7dbb9255e29e50da53b753a9fa\`**; previous full suite had 22 failures/4 errors due solely to fixture pollution.

Next: pinned install corrected manual switch helper, root-only \`diagnose\` and read-only exact candidate selection and \`preview\`; do not repeat different-Xray \`apply\` until operator agrees to a supervised guarded test. Keep LAN forward, cross-Xray hardware PASS, intentional failure/watchdog, reboot and clean install release gate open. No production SD or MikroTik changes.

### 2026-10-21 Xray-to-Xray manual switch — test Pi TUN PASS

User executed on the **test Pi** `awg-upgrade` with previously healthy and actively selected Xray: `awg-mihomo-unified-nodes probe 3` → `UNIFIED_PROBE_INDEX=3 ENGINE=XRAY BASIC_NETWORK=NETWORK_OK`, `awg-xray-manual-switch preview 3` → `XRAY_MANUAL_PREFLIGHT=PASS`, then guarded `awg-xray-manual-switch apply 3` → **`XRAY_MANUAL_TUN=VERIFIED`**, `MIHOMO_NODE_POLICY=UNCHANGED`, `XRAY_MANUAL_REBOOT=NOT_TESTED`. This is the first successful **different Xray profile → Xray index 3**, after an earlier attempt through the menu had failed with code 2 and rolled back. It is a supervised manual switch, not automatic failover.

Independent read-only confirmation at **2026-10-21 11:21 +07**:
- Mihomo controller `AWG-XRAY-VLESS-LOCAL` remains selected; Xray service active and enabled with `NRestarts=0` and unit `Result=success`, `ActiveEnterTimestamp=11:20:02 +07`; loopback `127.0.0.1:17892` listening.
- HTTPS `curl --interface mihomo0 --noproxy '*'` to `https://api.openai.com/v1/models` returned **401, curl exit 0**; separate Xray SOCKS5 probe of the same endpoint also **401, exit 0**. This verifies Pi-originated actual TUN egress as well as SOCKS, not forwarded LAN.
- SSH, dnsmasq, Mihomo, pbr-health and selection-monitor active. Both policy `fwmark 0x100/0x101` rules present and tables 100/101 default via `mihomo0`. No pending `awg-xray-manual-*` recovery timer, zero failed systemd units.
- **Post-switch root checks now PASS (operator 2026-10-21):** `sudo awg-transit-routing status` reported `Transit guard: SAFE`, `Transit policy rule: ACTIVE`, `Transit VPN table: READY`; independently recomputed SHA256 fingerprint for current provider `proxies[2]` (index 3, excluding `name`) exactly matched the root-owned `xray-vless/selected.json`: `XRAY_NODE_3_SELECTED=True`. This establishes correct Xray profile identity and current root Transit guard after the successful switch; it is not a forced failure / forwarded LAN traffic test.
- **PASS scope:** supervised Xray-to-different-Xray manual selection and real Pi TUN HTTPS; no LAN client, forced rollback/failover, YouTube 24-frame media/ChatGPT Web, reboot, or clean-install acceptance claimed. No changes to production microSD or MikroTik/SSTP.


### 2026-10-21 native Mihomo menu appears selected while Xray remains actual outbound

Operator evidence: `Состояние Mihomo` screenshot displayed saved `Selected node: NL Netherlands 1 Hysteria2`; Windows IP-check screenshot showed the previous Xray exit IP. Independent **read-only** test Pi inspection at 11:30 +07 verified live `AWG-MIHOMO` controller `now=AWG-XRAY-VLESS-LOCAL`, Xray and Mihomo active, mark rules 0x100/0x101 and both routes via `mihomo0`, no pending recovery timers or failed systemd units. Pi direct vs Xray bound egress through `https://api.ipify.org`: `--interface mihomo0` and `--socks5-hostname 127.0.0.1:17892` **both matched** the public IP visible on Windows, while Pi DIRECT did **not**. This demonstrates the **Pi TUN was still using Xray**, and the Mihomo status' named native node was not the live outbound. Matching Windows egress IP alone does **not** prove its forwarding path through Pi rather than MikroTik SSTP; LAN still unverified.

Source root cause: `src/awg-mihomo-configure status_cmd` printed only the stored `node-name`; `awg-menu` translated it to **Выбранный узел**, even when controller still selected the live Xray SOCKS alias. The ordinary manual Mihomo choice called `node select-auto` which can update `node-name`/endpoint and restart Mihomo while `profile.store-selected=true` continues selecting `AWG-XRAY-VLESS-LOCAL`. Hence UI metadata may diverge from dataplane.

Candidate fixes (**committed in draft PR, NOT installed / NOT Pi-live-tested**):
- Status now queries the **actual local Mihomo controller**, displays `Actual outbound engine: XRAY|MIHOMO|UNKNOWN` and distinguishes saved native metadata from live selection; if controller fails, no false successful live status.
- Manual menu selection of Mihomo while Xray is selected routes through the existing `awg-xray-manual-switch` root-only `native-preview NAME` / guarded `native-apply NAME`, **not** ordinary unguarded `node select-auto`. Strict preview requires the native node already loaded in the current controller AND matching the stored configured native node; reject unsupported different native choice without any dataplane mutation.
- Guarded native return snapshots previous Xray, holds maintenance lock, arms independent watchdog, switches actual controller to native, confirms OpenAI HTTPS 401 through Pi `mihomo0` and routes/Transit SAFE, only then detaches persistent Xray boot dependency/staged selection and stops/disables the optional sidecar. If validation fails, roll back to original Xray; no code claims LAN/reboot. Pre-arm errors do not restart the healthy incumbent. Does not change Mikrotik/SSTP, DNS, or FIXED/AUTO/READY/Hot Pool.
- **26/26 targeted mocked manual switch tests PASS** and `bash -n` of modified scripts PASS on Pi at `ac39026` before the last pre-arm guard refinement. The new pre-arm negative regression was committed afterward; full suite outcome **not yet independently verified** because test Pi remote commander monthly quota was reached while a full run was executing. Obtain the rootless test result before proposing a live native-return apply, and perform separate root-only `native-preview`.

Status: screenshot/UI mismatch **REPRODUCED/EXPLAINED**; source fix **COMMITTED ONLY**; actual Xray→native switch, Windows LAN client path, forced rollback, and reboot **NOT YET PASS**.


### 2026-10-21 generalized manual Mihomo/Xray node switch — source candidate, test gate pending

User requirement: any current exact provider node must be manually selectable regardless of whether the current outbound is Mihomo or Xray, without lying about the selected exit or overwriting unrelated FIXED/AUTO/READY policies. The observed `XRAY_MANUAL_ERROR=XRAY_NOT_ACTIVE` came from the earlier `native-preview` requiring **Xray service active AND controller selector on the Xray alias**, even after the controller/sidecar state changed. Old native `node select-auto` could update `node-name` and restart Mihomo but still leave the Xray alias selected, as independently observed via Pi TUN/socks egress.

**Candidate source only, NOT installed/NOT hardware PASS:**

- `src/awg-menu` resolves the engine from the existing unified provider catalog. Xray target keeps previously-tested guarded `preview/apply INDEX`; **every** Mihomo target now invokes `native-preview/native-apply NAME` in the guarded manual helper, not the unguarded `node select-auto` path. Target native profile can be loaded from current provider, rather than required to already exist in a controller filtered to a different node.
- `src/awg-xray-manual-switch.py` generalizes native preflight to both **Mihomo→Mihomo** and **Xray→Mihomo**, authoritative live controller selection and current Pi-bound HTTPS, exact profile uniqueness, repository-native provider `info` resolver for `filter_regex` and first IPv4 endpoint. Invalid/unsupported profiles and mismatched service/controller states fail without mutation.
- Under owner-only snapshot/maintenance lock + 180-s independent systemd watchdog, native candidate changes are made only to Mihomo provider filter, endpoint and node-name; Mihomo restarts with its own `awg-mihomo-prepare` config validation, controller explicitly selects target after startup, and **real Pi `mihomo0` OpenAI API HTTPS** (HTTP 401) and routing/Transit guard are checked before commit. On success the old Xray sidecar (if previous active exit) is detached only after new native TUN has passed. The native→native case leaves unrelated engine policy files untouched. There may be brief TUN downtime during Mihomo restart; Transit must remain FAIL-CLOSED.
- On any failed transaction after mutation, rollback restores byte copies of previous Mihomo `provider.env`, `config.yaml`, endpoint and expected-egress state, `node-name`, previous Xray selected state and boot override, fixed policy/order, then restarts the old Mihomo controller selection and verifies HTTPS TUN. Failed immediate recovery leaves the independent watchdog armed; later recovery may refuse replacing a newer transport.
- Synthetic regression tests added/updated for all native-engine starts, no-op, profile rejection, preserved FIXED order, live controller selection, native/Xray error handling, and byte-level rollback. **No full test run or new Pi-live switch has yet been observed after these candidate commits** because remote Pi control is currently unavailable; operator should run pinned `py_compile`, `bash -n`, targeted tests and full suite. Do NOT infer PASS from earlier 726/726 which predates this change.
- Installer and existing-install upgrade already deliver versioned `src/awg-menu`, `src/awg-xray-manual-switch.py` and `src/awg-mihomo-configure`; no new daemon, dependency or transport engine required.

**Next gate:** test-Pi pinned source checkout, rootless  tests, then nonmutating `native-preview` for a selected native node while controller is actually Xray/native; only after current Transit/SSH checks and operator approval a timed live transition with independent TUN egress observation, valid controller state, rollback, then LAN/failover/reboot. Do not touch MikroTik priority SSTP or production microSD.

### 2026-10-21 first unified-manual full suite FAILED; candidate corrections await rerun

Operator tested pinned source commit `8cce62fa3f1e558cf93c75129871a41851c7cc70` on test Pi: syntax checks completed; full rootless Python suite: **730 cases, FAIL (1 failure + 1 error)**. Named results: `test_rollback_xray_restores_old_profile_before_local_selection` ERROR, `test_initial_setup_is_native_dialog_not_hidden_ssh` FAIL. **Do not install that revision or claim PASS.**

Candidate corrections committed after operator evidence:
- Xray rollback synthetic fixture now mocks systemd service liveness required by existing bounded previous-Xray TUN recovery (prevents unit test dependence on current running Pi state); no runtime service is changed.
- The unified native menu restores its preexisting read-only `run_with_progress ... awg-mihomo-configure node prepare` behavior for normal/first-run setup.
- Explicit **Transit FAIL-CLOSED** quiesce (existing `awg-transit-routing disable` under nft forward DROP guard) *before* stopping Mihomo TUN, followed by `awg-transit-routing apply` after real target node/controller become ready and before HTTPS/TUN postcheck; the same protection is required on native rollback. **Selective FAIL-OPEN** uses existing `awg-pbr-failopen` before any Mihomo TUN stop.
- Preserves operator `MIHOMO_XRAY_VLESS_BRIDGE` setting instead of forcing `auto`; permits known, installer-owned Xray sidecar active while an actual native node is selected (passive managed Xray), and retains original sidecar state on rollback. Unknown/foreign Xray continues to be rejected before mutation.
- Synthetic tests assert both Transit quiesce/rearm and Selective failopen happen before service teardown, native state restoration, and no mutable action on invalid provider profiles.

**Corrected source and regression tests have NOT been re-run on test Pi yet**, so current full-suite status is **FAIL pending new run**, independent of the previous 726/726 gate. There is **no** verified live/native↔Xray switch using corrected files, no installer clean-install/LAN/reboot/failover PASS. The candidate remains a **draft PR**, not production or stable release.

### 2026-10-21 unified-manual regression rerun — 731/731 rootless PASS (not hardware)

Operator on test Pi `awg-upgrade` checked pinned candidate commit `9d92f6375a0adc28bd6491f1ecad0cce8d216674`, verified Python `py_compile` for `awg-xray-manual-switch.py` and its tests, `bash -n src/awg-menu`, then ran `python3 -m unittest discover -s tests -q`: **`Ran 731 tests in 26.768s`, `OK`, `TEST_EXIT=0`**. The earlier 730-suite failure/error in the previous candidate were resolved by that tested revision. This is **automated rootless regression PASS**, with no modification of live Xray or Pi VPN dataplane.

Next acceptance gate remains staged **test-Pi install of only versioned manual switch and menu helpers** after verifying no armed recovery timer, followed by read-only `native-preview` (exact current subscription native name) and privileged Transit status. Only after preflight permit supervised native↔Xray real TUN switching, which must check actual selected controller and egress, service health, rollback and guard. LAN/reboot/forced-failure/clean install not PASS. PR #143 remains draft, PR #115 open, no release.

### 2026-10-21 test Pi: AUTO Mihomo→AWG fallback confirmed, manual AWG→Mihomo returned

On test Pi `awg-upgrade` after installation of candidate manual-menu/transaction files (installer and router not modified), operator independently confirmed: `awg-transport status` reports `AmneziaWG/awg healthy`; `awg-transport check awg` returned `healthy`; `awg-quick@awg0.service` is `active`, `Result=success`. `awg-selection status` shows conservative AUTO order `mihomo,awg`, fallback only for repeated health failures. System journal contains `Automatic failover: mihomo -> awg (mode=auto)`. At that moment Mihomo exited cleanly, Xray inactive and `mihomo0` absent; no pending manual transaction watchdog. This was **intended transport fallback**, not a failed installer or confirmed cause of initial Mihomo health failure.

Operator then executed existing versioned `sudo awg-transport select mihomo`; real Transit preflight **OK** (router/LAN/direct endpoint and live `mihomo0`), `Transport activated: Mihomo`, transport status `healthy`, `Transit guard: SAFE`, policy rule `ACTIVE`, VPN table `READY`; `awg-mihomo-configure status` showed saved **and actual controller-selected** `Netherlands 1 Hysteria2`, service active. **Verified:** manual healthy AWG→native Mihomo transport recovery on Pi, in Transit. **Not verified:** arbitrary Mihomo→different Mihomo using new guard, Xray→native return, Xray→Xray after new guard, deliberately induced native switch rollback, LAN-client forwarded route, reboot, clean install. Original reason for node health failure remains undiagnosed; no automatic return to Mihomo is desired in sticky conservative AUTO.

The user reports Desktop Commander remote tooling is quota-limited; GitHub revisions can be reviewed, but live Pi command execution currently requires operator's own SSH session. Preserve current working Mihomo and do not disable MikroTik SSTP. Next controlled gate is exact `native-preview` for current node (expect idempotent already-selected), then choose a different provider-backed native name in the versioned menu and check TUN/controller/guard and failure metadata. An unsuccessful preview is not evidence of a broken current VPN.

### 2026-10-21 direct Desktop Commander validation after UI and Selective health recovery fixes

Test-Pi `awg-upgrade` online again through connected Desktop Commander (device user `karlinks`, unprivileged). Read-only verification: `awg-mihomo.service` active (`NRestarts=0`), Xray inactive, SSH/dnsmasq active; routing tables `100` and `101` default through `mihomo0`, fwmark rules 0x100/0x101 present; genuine `curl -q -4 --interface mihomo0 --noproxy '*'` to OpenAI HTTPS returned HTTP **401** with curl exit **0**. Journal confirms prior fallback `2026-10-21 12:21:24 +07:00 Automatic failover: mihomo -> awg (mode=auto)`. All these readings are **current active Mihomo Pi-TUN evidence**, not a switch to a different node.

After operator's SSH screen rejected 71×33 window as too narrow, candidate `src/awg-menu` lowered minimum terminal width from 78 to 70 and retained clamp-to-actual-terminal dimensions; new pseudo-TTY fixture verifies a 71×33 SSH dialog. Code audit found Selective manual `awg-pbr-failopen` necessarily removes fwmark 0x100, while `awg-pbr-health` independently restores it after health polling; previous postcheck only waited ~1 second. Candidate `src/awg-xray-manual-switch.py` now waits up to 20 seconds for route return before actual TUN HTTPS checks; a missing rule cannot be called a successful switch. Transit continues using independent guarded disable and rearm. Tests cover delayed Selective return and timeout failure.

On test Pi the operator's git checkout now matches candidate `c17e7b619c4b31b2e7d54e950361743060b2ca6f`; Python compile and `bash -n` PASS; independently invoked targeted suites: **34/34 manual-switch PASS**, **9/9 menu PASS**; **full rootless suite 734/734 PASS, 27.267s** on connected Desktop Commander. These test cases use mocks and pseudo terminals; no native `apply` was executed, no production router/SD edits.

**Tooling limitation:** Desktop Commander's current security configuration explicitly blocks `sudo`/root escalation commands. Restoring its monthly usage quota does not itself authorize privileged execution. No removal of that guard or workaround was performed. The root-owned installed manual switch/menu still correspond to the previously installed cbb95a8 candidate, **not these later c17e7b6 changes**; hardware acceptance requires explicit permission for controlled test-Pi privileged commands or a separately authorized operator action. PR #143 remains draft; no live Mihomo→different Mihomo, Xray→Mihomo, LAN or reboot PASS.

### 2026-10-21 test Pi installed candidate c17e7b6 — native same-node PASS, cross-node pending

Operator on test Pi `awg-upgrade` installed root-owned versioned manual-switch + menu from pinned checkout `800762dba6534f80eed2c16d2e81e0fb4682f57a` (implementation code `c17e7b6`, later docs-only). Rollback copies saved in root-only `/var/backups/awg-gateway/manual-unified-v2.NvExf9Y6`. Operator then verified exact saved Netherlands 1 Hysteria2 with `native-preview` output `NATIVE_RETURN_PREFLIGHT=PASS`, `NATIVE_MANUAL_ALREADY_SELECTED=YES`, `NATIVE_RETURN_TUN=EXISTING_HEALTHY_NOT_SWITCHED`, plus live Mihomo healthy and Transit guard SAFE/rule ACTIVE/table READY. Through connected read-only Desktop Commander after install: `awg-mihomo.service` active, Xray inactive, rules 0x100 and 0x101, tables 100 and 101 both `default dev mihomo0`, Pi-bound OpenAI API HTTPS **401** curl exit 0; no armed manual watchdog timer. This validates **installation, current-node no-op, current TUN and Transit**, not a different-node transition.

Desktop Commander `sudo` command block was briefly removed with user's explicit permission, then restored after it became clear Debian still required a password: `sudo -n true` returned `sudo: a password is required`. No sudoers changes or credentials were supplied. Live privileged native apply cannot be executed through DC without the user's authorized sudo session. Next minimal operator action: `sudo /usr/local/sbin/awg-menu` in SSH (71x33 supported) then choose another native Mihomo profile and confirm; assistant can independently observe ongoing Pi routing/HTTP/controller where unprivileged. Record actual switch or rollback before claiming cross-engine PASS. No MikroTik/production microSD changes.

## Forwarded IPv4 TCP MSS regression — 2026-10-25

Real Transit/AWG LAN TLS sometimes needed about5s to recover an initial1460-byte server segment gap, while Pi-bound AWG HTTPS completed in about0.5s. Do not mistake a4s test deadline for proof that AWG forwarding never worked. A guarded site-specific MSS1380 canary removed the delay (22/22 HTTP200); retain its distinct hardware scope and the original timeout receipts.

Candidate0cdcf0a uses live route MSS (`tcp option maxseg size set rt mtu`) for LAN→selected-VPN IPv4 SYNs in both renderers. Transit MAC/source/egress guards, Selective DIRECT behavior and lockdown remain unchanged. The setter preserves smaller existing MSS. See [Netfilter MSS documentation](https://wiki.iptables.org/wiki-nftables/index.php/Mangling_packet_headers#Mangling_TCP_options). Installer and upgrade already deliver the corrected renderers.

Mandatory tests: ordinary rootless discovery covers both renderers and unconfigured/lockdown; explicit-root `AWG_MSS_NETNS_TEST=1` runs `tests/test_tcp_mss_forward.py` in disposable Linux namespaces, proving1460→1380 over a1420-byte VPN route and preservation of536. CI includes that privileged isolated check. Do not execute the entire ordinary discovery as root. Namespace passing is not an actual LAN-client or router test.

Still require final dynamic-source LAN recheck, real Selective recovery and relevant mode/failure cases; don't infer complete upload, IPv6, no-network reboot or full release acceptance from this single-site canary. Latest detailed scope is in PROJECT_STATE.md.
