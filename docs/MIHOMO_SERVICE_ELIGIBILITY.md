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
