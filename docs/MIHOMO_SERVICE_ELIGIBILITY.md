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

## Actual service-specific failure analysis (13 October 2026)

A fresh passive scan on Pi checked 10 provider nodes, seven reached the preliminary warmup and six returned an OpenAI API HTTP 401 rather than a regional error. No node attained both-service PASS. The originally active Shadowsocks node emitted an explicit OpenAI region error and is FAIL.

Further **independent one-node shadow-only diagnostics** (never modifying the selected Mihomo transport or table 100) established:

- `hysteria2-335173174`: OpenAI API 401 PASS; ChatGPT web 403 UNKNOWN; YouTube watch HTTP 200 but embedded `playabilityStatus=LOGIN_REQUIRED`, no verified video bytes. This is an *anonymous player-access restriction*, not definitive evidence that a signed-in end user cannot watch video on this node.
- `shadowsocks-27307`: OpenAI API 401 PASS; ChatGPT web 403 UNKNOWN; YouTube watch HTTP 200 with `playabilityStatus=OK`. The page advertised 14 adaptive representations, including six video formats, **but none contained a plain stream URL or signatureCipher**; it did include `streamingData.serverAbrStreamingUrl` (SABR). This is an unsupported player/media delivery protocol for our initial byte-range checker. It does **not** prove playable media was decoded or that the node is blocked.
- A normal Chrome-style `User-Agent` and browser `Accept` headers through the isolated proxy still returned ChatGPT HTTP 403, so changing headers alone did not confirm browser eligibility. No authenticated chat interaction or decoded YouTube playback was attempted.

The service checker now preserves UNKNOWN with **diagnostic reasons** `youtube_player_login_required` and `youtube_sabr_stream_unvalidated` (only for a trusted Googlevideo SABR URL). It never upgrades either case to PASS. Dedicated offline tests cover both branches and disallow untrusted SABR hosts.

**Deployment decision:** keep `service-eligibility.mode` OFF until an authorized browser-level test can confirm actual ChatGPT interaction and video playback and a safe way exists to produce auditable, per-node eligibility evidence from that result. Do not force PASS on an HTTP status or absent media URL. The existing transport fallback and MikroTik/NAS boundaries are unchanged.


## Reused Stage17–18 video decoder — real rediscovery, 13 October 2026

The previously successful Stage17/Stage18 media test was traced back to its
technical method: a distinct TUN-disabled Mihomo on localhost, yt-dlp
2026.08.19 using Node.js v22.16.0 and YouTube's official player extractor,
a bounded initial video segment downloaded **through that same shadow proxy**,
and ffmpeg decoding at least 24 frames. Stage18 had reported 2/2 independent
24-frame tests on `shadowsocks-27307`.

We restored **the exact two tool versions** into root-owned mode 0700 under
`/dev/shm/awg-stage18-service-runtime`, with known SHA-256 hashes of both
binaries and the downloaded official Node tarball. The new operator-only
`scripts/awg-mihomo-stage18-ram-runtime.sh` validates or restores this RAM
runtime. It does not install Debian packages or change system services.

New `src/awg-mihomo-video-decode.py` implements a conservative Stage18
frame check on the existing shadow HTTP proxy port:

- Root-owned SHA-256 pinned Node/yt-dlp tools required. Absent, modified or
  non-root-owned runtime always results in UNKNOWN.
- Fixed known YouTube watch URL, no authentication cookies or user secrets;
  yt-dlp has an explicitly forced `127.0.0.1:<shadow-port>` HTTP proxy and
  fixed bounded network timeouts. EJS JavaScript solver obtained from the
  upstream yt-dlp project as needed through that proxy.
- `--download-sections *0-4` from a low-resolution video format, hard 2 MiB
  output limit, max 55 seconds yt-dlp and 17 seconds ffmpeg execution.
  Temporary file is under `/dev/shm` only, and is deleted at completion.
- ffmpeg is limited to local `file,pipe,data` inputs; **only 24 decoded frames**
  can return `PASS / youtube_24_video_frames_decoded`. HTTP statuses,
  YouTube HTML, SABR presence and an ffmpeg exit without frames are NEVER PASS.
- The decoder is invoked from the existing `awg-mihomo-smart service-scan`
  for a specifically selected one-node shadow test; ordinary 10-node
  benchmarking invokes it only when API and ChatGPT web are already PASS so
  CPU and downloads are not wasted on ineligible candidates.
- Service Eligibility still requires **both** ChatGPT and video check PASS.
  A video PASS cannot erase the ChatGPT web UNKNOWN, and an OpenAI region
  FAIL is never overridden.

**Independent live proof on 2026-10-13:** for `shadowsocks-27307`, isolated
yt-dlp obtained the YouTube video and ffmpeg successfully decoded **24 frames**
from a 43,449-byte RAM-only segment in 7.9 seconds of download processing.
A subsequent run of the **integrated new Service Eligibility code** returned:
`OPENAI_API=PASS`, `YOUTUBE_VIDEO=PASS`, `CHATGPT_WEB=UNKNOWN`,
`SERVICE_ELIGIBILITY=UNKNOWN`. Existing live Mihomo/AWG, table100,
Transit guard, SSTP on MikroTik and NAS were not modified.

This is a working VIDEO decoder but does **not** prove authenticated ChatGPT
chat is accessible. Cloudflare HTTP 403 from anonymous Python HTTP requests
remains UNKNOWN, and previously successful interactive ChatGPT sessions do
not constitute a fresh per-node automatic browser proof.

The decoder and SMART integration in the feature branch are not yet installed
to the working transport selector. Service-gated automatic failover remains
OFF while ChatGPT eligibility is being resolved. RAM tools must be verified
and re-created after reboot before any service gating can be enabled.


## ChatGPT Chrome/TLS/JavaScript diagnostic, 13 October 2026

On 12 October, the Stage20 browser test had independently confirmed actual
ChatGPT opening, authentication and message exchange on shadowsocks-27307,
using Windows Chrome through a temporary SSH tunnel to Pi's isolated Mihomo.
This historical evidence is NOT a fresh automated PASS.

We restored Chromium 154 ARM64 from signed Raspberry Pi Debian apt packages
into /dev/shm, including four missing libraries. No system package was installed.
Chromium rendered a local test HTML document. In a fresh, empty, unprivileged,
RAM-only browser profile, with all requests directed through a temporary Mihomo
proxy, ChatGPT returned the Cloudflare JS challenge "Just a moment...".
This occurred independently with shadowsocks-27307 and hysteria2-335173174.
Longer JS virtual time did not result in access to an authenticated chat.
No browser credentials/cookies were transferred to Pi.

A browser challenge or anonymous HTTP403 cannot disprove that ChatGPT works in
the user's authenticated browser. Equally, OpenAI API HTTP401 and a YouTube
24-frame video decode cannot prove ChatGPT chat functionality.
The checker now distinguishes HTTP403 containing anti-bot markers as
chatgpt_web_antibot_challenge from generic chatgpt_web_http_403.
Both remain UNKNOWN. There is no implicit PASS for Cloudflare challenge.

The Chromium installation is NOT part of Service Eligibility or production.
The browser RAM fixture is removed after the experiment. The Stage18 decoder
keeps its independently confirmed video PASS.

Release gate unchanged: automatic switching remains OFF until there is fresh
authenticated chat proof for the exact candidate through an authorized browser,
with no transfer of session cookies/tokens to Pi, and a reviewed freshness
policy. The project must not conflate anonymous anti-bot blocking with node
unavailability or assume that a public API401 is a working chat.

## Stage20 ephemeral browser test: fresh proof without copying credentials to Pi

The original 12 October Stage20 user acceptance was a genuine authenticated
Chrome chat, while anonymous Python and even Chromium from RAM get Cloudflare
challenge/HTTP403. This **cannot be solved by changing status code policy**.

The focused `awg-mihomo-smart browser-session --node NAME --seconds 600` reuses
our existing isolated Mihomo candidate listener rather than adding any new
VPN/backup architecture. It requires root to read private subscription and
checks the candidate underlay is a public IPv4 with matching Pi DIRECT ethernet
route. Its proxy is explicitly bound to **127.0.0.1:17891**, the controller is
also localhost, TUN is disabled, secret config remains in temporary /dev/shm,
shared smart test lock prevents concurrent shadow tests, and the process is
terminated and RAM config removed within a maximum 600 seconds. It does not
set any production health result, whitelist a candidate, change node selection,
or report ChatGPT PASS merely because the listener exists.

Example, when a Windows browser session is available and **only after** the
operator decides to perform the controlled test:

```bash
sudo python3 -B /tmp/awg-service-eligibility-dev/src/awg-mihomo-smart browser-session --node shadowsocks-27307 --seconds 600
```

In a separate Windows PowerShell terminal, tunnel its loopback port:

```powershell
ssh -N -L 127.0.0.1:18891:127.0.0.1:17891 karlinks@192.168.112.34
```

Start Windows Chrome with an **isolated local browser profile** using
`--proxy-server=http://127.0.0.1:18891 --disable-quic`, open
`https://chatgpt.com/`, sign in and **actually send a test chat message**.
User credentials, cookies and chat content remain entirely in Windows Chrome.
The user may report successful chat as an explicit acceptance result, but no
RAM-only or GitHub code assumes such a report to be a fresh automated PASS.

**Independent Pi smoke**: port 17891 bound ONLY to 127.0.0.1; request to
OpenAI API returned 401 through selected shadowsocks-27307; the working
Mihomo and table100 remained unchanged. The 60-second test lease then
terminated automatically. No persistent media/browser runtime, systemd,
MikroTik or NAS changes were made.

**Unresolved original requirement:** before fully autonomous service-qualified
switching, an audited way to refresh actual authenticated browser results
for each candidate is still required. We do NOT equate API401, the open browser
proxy, a 403 challenge, or a historical successful chat with current proof.
The production service gate remains OFF.

## Extended candidate verification — 13 October 2026

After Stage18 frame decoding was integrated, further **isolated one-node live
service-scan** checks (no production switch, no changes to MikroTik/NAS) showed:

| Exact node | OpenAI API | YouTube decoded 24 frames | ChatGPT | Overall |
| --- | --- | --- | --- | --- |
| shadowsocks-27307 | PASS | PASS | UNKNOWN (anonymous Cloudflare) | UNKNOWN |
| vless-1741441891 | PASS | PASS | UNKNOWN (anonymous Cloudflare) | UNKNOWN |
| hysteria2-335173174 | PASS | UNKNOWN | UNKNOWN | UNKNOWN |
| vless-1771506792 | NOT TESTED | NOT TESTED | NOT TESTED | UNKNOWN (FQDN endpoint rejected by strict public-IPv4 DIRECT validator) |

The video PASS is an *actual local ffmpeg >=24-frame decode of a sample
received through that candidate's own shadow proxy*, not inferred from a
watch-page HTTP200. A ChatGPT 403/Cloudflare challenge remains UNKNOWN; prior
user Chrome success on a different day does not silently promote freshness.

The current user facing next step is a new **real Windows Chrome** chat test
through each candidate's 60-600s Stage20 `browser-session` and SSH localhost
forwarding, with no transfer of cookies to Pi. Until authenticated ChatGPT
results can be refreshed safely and independently, AUTO SMART gate stays OFF.


## Two candidate browser acceptance tests completed — 13 October 2026

The operator independently confirmed real authenticated ChatGPT message
exchange (message sent and ChatGPT reply received) in Windows Chrome
through each fresh one-node Stage20 test proxy. Each node had already
passed the real 24-frame YouTube/ffmpeg decoder on Pi.

| Exact node | Decoded YouTube | Windows Chrome ChatGPT | Acceptance |
| --- | --- | --- | --- |
| shadowsocks-27307 | PASS, 24 decoded video frames | PASS, reply received | Both services manually accepted |
| vless-1741441891 | PASS, 24 decoded video frames | PASS, reply received | Both services manually accepted |

The second candidate's isolated proxy was verified at 127.0.0.1:17891.
OpenAI API returned HTTP401 and its public egress IPv4 was 193.233.74.6.
The previous Shadowsocks test instance was terminated before the VLESS
instance started. After user confirmed receiving the ChatGPT reply on
VLESS, the temporary Mihomo was terminated and port 17891 freed.
Both tests used Windows-local browser sessions with no ChatGPT cookies
or credentials copied to Pi. The production node remained
shadowsocks-696792830, transport healthy, Transit guard SAFE and
table100 default dev mihomo0.

IMPORTANT: This is MANUAL FUNCTIONAL ACCEPTANCE, not continuous autonomous
browser evidence. Never pretend fresh authorized ChatGPT conversations
can be verified after the browser closes, nor persist PASS indefinitely.
The strict automatic gate therefore remains OFF until a secure
freshness/authorization mechanism is reviewed and tested.

### False-failover blocker corrected in this PR

The initial awg-selection-monitor treated ANY nonzero service checker
exit status as a failing current-node observation. But anonymous
Cloudflare and YouTube bot challenges legitimately produce UNKNOWN
and a nonzero checker exit. Two such observations could previously
trigger false node fallback, even though user ChatGPT chat works.

The monitor now parses the bounded JSON verdict; only status FAIL
counts as a negative observation. UNKNOWN (including malformed
checker data and missing checker) breaks the explicit-failure streak
without asserting a new PASS. PASS also resets the failure streak.
Two independent explicit FAIL observations plus the existing selection
monitor failure threshold and validated eligible target are still needed
before failover. Bogus mode continues to fail closed.
Regression tests cover consecutive FAIL, FAIL then UNKNOWN,
UNKNOWN then FAIL, UNKNOWN twice, malformed data, PASS reset and
off/bogus service gating. No running Pi services are modified.


## Exact two-node isolated Mihomo switch validation — 13 October 2026

After both nodes passed user-authenticated ChatGPT conversation and 24-frame
YouTube decoding, a separate TUN-disabled in-RAM Mihomo was configured
with both exact subscription nodes. The existing Mihomo controller
changed the selected proxy from shadowsocks-27307 to vless-1741441891.

- First selection: shadowsocks-27307 egress 169.150.210.233;
  OpenAI API HTTP401 as expected.
- Second selection: vless-1741441891 egress 193.233.74.6;
  OpenAI API HTTP401 as expected.
- Selector transition PASS; public egress IPv4 did change.
- Test Mihomo was terminated and temporary RAM config removed.
- Production remains selected shadowsocks-696792830, Mihomo healthy,
  Transit guard SAFE, table100 default dev mihomo0; no MikroTik, SSTP,
  NAS or AWG modifications.

This proves two-candidate isolated proxy selection and reachability.
It does NOT by itself prove production failover timers/policies or a
subsequent automatic authenticated ChatGPT conversation. The user
confirmed genuine chat replies on both candidates separately earlier.
Production service gate remains OFF pending a safe unattended way
to refresh authenticated ChatGPT usability without exporting session
cookies or weakening UNKNOWN semantics.

The latest selection-monitor regression deliberately counts only
explicit JSON FAIL; UNKNOWN from Cloudflare never causes false failover.
90 Python tests and GitHub v1.3.0 CI passed for the safety fix.


## FINAL DESIGN DECISION — NETWORK BALANCED, NO BROWSER GATE (13 Oct 2026)

The user explicitly removed the browser-validation stage from the project's
target AUTO SMART architecture. The browser-proof design in the preceding
draft was **reverted**. No time-bound user attestation, logged-in Chrome,
cookies, account or device integration is required for automatic decisions.

An opt-in service-eligibility.mode=balanced has been added instead:

1. The existing Mihomo health pool screens **all supported protocol families**
   and provider entries subject to configured protocol/region policies. There
   is no fixed 2-node allowlist and no browser-approved node restriction.
2. At node failover, the best currently healthy candidate is selected from
   the pool. An independent one-node TUN-disabled RAM-only Mihomo service-scan
   checks that exact candidate. At most three candidates are checked per
   failover call, avoiding uncontrolled media tests across a huge provider.
3. Qualify a candidate as NETWORK_ELIGIBILITY=ELIGIBLE only if:
   - OpenAI API returned PASS (normally HTTP 401: auth required but region
     allowed and HTTPS endpoint reached), AND
   - YouTube real video was **successfully decoded for 24 frames**, AND
   - ChatGPT HTTPS returned confirmed page access or a challenge response:
     the web check is PASS, or its UNKNOWN reason is an HTTP 403, recognized
     Cloudflare challenge, or reached authentication/login page.
   Failures due to an API region error, video decoder failure, ChatGPT DNS
   or TLS timeout, malformed output, explicit service FAIL, or unavailable
   proxy do **NOT** qualify. A network-level 403 is only a probabilistic
   signal; it is NOT recast as full ChatGPT login/chat PASS.
4. Candidate rejection in balanced mode temporarily cools it for 180 seconds
   in the normal RAM-only health pool so repeated failover attempts may
   inspect more candidates. Existing pool policy, health ranking, cooldown
   and rollback semantics remain intact; arbitrary healthy nodes are not
   elevated to qualified status without these checks.
5. For an active Mihomo node, UNKNOWN from Cloudflare or YouTube antibot
   **does not accumulate false outages**. Only repeated explicit JSON FAIL
   can initiate service-health failover; genuine transport connectivity
   loss still follows the pre-existing health/backup policy.

The mode is OPT-IN and NOT installed or enabled in production. Existing
require (strict full-check) and off modes remain unchanged. Manual Stage20
historical acceptance through Windows Chrome of two named nodes remains
documented only as prior test evidence; it no longer participates in the
new decision policy.

**Accuracy contract:** MEDIUM network-level likelihood for ChatGPT plus a
high-confidence actual YouTube playback test, not guaranteed authenticated
chat functionality. No browser stage will be designed or required. The
supported protocol inventory still includes SS, VLESS, Trojan, Hysteria2,
VMess and the project's other supported Mihomo entries; note the current
one-node DIRECT-route verifier requires literal public IPv4 endpoints,
so a DNS-hostname node may remain UNKNOWN pending a separately reviewed
safe resolver. Neither MikroTik/SSTP nor production Pi route tables, live
node, NAS or AmneziaWG backup are touched by the feature branch.

Quality: 108 Python regression tests PASS after removing browser proof tests;
the existing Stage18 decode is retained, while the new network-only classifier
rejects timeouts and malformed/unverified responses. A repeat of the actual
live one-node network scan with this exact branch was not possible from the
current restricted operator sudo context (the privileged helper does not
expose ad-hoc service-scan), so do NOT state that the newly integrated balanced
mode was live-tested or deployed. The earlier exact-node Stage18 real decoder
and browser results remain verified separately.


## Stage18 RAM runtime after reboot: passive opt-in bootstrap

The balanced candidate gate requires SHA256-verified official Node.js
v22.16.0 and yt-dlp 2026.08.19 to decode real YouTube video frames.
The binaries are held in root-owned /dev/shm/awg-stage18-service-runtime
and disappear after reboot. Missing binaries mean UNKNOWN, not PASS.

The PR adds passive systemd service awg-mihomo-stage18-ram-runtime.service
and retry timer awg-mihomo-stage18-ram-runtime.timer. install.sh only
copies the units and pinned bootstrap helper. It DOES NOT enable the timer,
enable balanced mode, restart the active transport or change firewall rules.

When an operator explicitly opts into balanced mode, the timer may be
enabled separately. It runs after boot and approximately hourly; the
service has an ExecCondition requiring the literal balanced mode.
Pinned official artifacts are downloaded only if absent or invalid
in RAM, with SHA256 validation. All writes stay in /dev/shm.
Service constraints include CPUQuota 80%, MemoryMax 256 MiB, 180s timeout,
NoNewPrivileges, ProtectSystem strict and ReadWritePaths=/dev/shm.

If runtime restoration fails, video decoding cannot claim PASS and
the candidate fails service eligibility. The existing selected healthy
transport is not automatically changed by the bootstrap. The timer
remains disabled by default to reduce overhead and microSD writes.
Complete canary testing and review is required before opt-in activation.

## Real transport fallback and rollback, 13 October 2026

The existing full selection-monitor mock suite passed: Mihomo node
fallback first, then AWG transport fallback after node exhaustion,
standby outage handling, repeated failure threshold, safe manual mode,
maintenance lock and sticky recovery.

On the real Pi an authorized awg-gpt transport-select switched
Mihomo -> AmneziaWG -> Mihomo. An independent 75-second failsafe was
armed and an EXIT-trap would also restore the original transport.
AWG Transit preflight verified DIRECT underlay, awg0 usable, fresh
handshake; AWG was healthy with table100 default dev awg0, Transit
policy ACTIVE and guard SAFE. Returning to Mihomo passed its own
Transit preflight; table100 returned to default dev mihomo0 with the
original active node shadowsocks-696792830 and guard SAFE.
The failsafe was cancelled and is not running.

This proves live transport switching, plus the automatic selection
order in isolated mocks. It does not prove a live automatic balanced
node decision: PR code remains uninstalled and production gate OFF.
No MikroTik SSTP or NAS changes were made.
