# Mihomo hot reserve — shadow prototype

**Scope: NOT a production selector.** This module creates a separate eligibility
record for nodes of the existing healthy pool. No TUN, transport, policy,
SSTP/MikroTik, DNS, nftables or forwarding changes. `best` is reporting only.
On the Pi test stand the diagnostic unit is installed and its timer enabled for SHADOW-only observation. It never selects or changes a live node.

## 2026-10-17 safety review: live-proxy isolation

**Default remains manual, no Hot Pool timer and no AUTO activation.**
A separate TUN-disabled Mihomo still shares the remote VPN server, bandwidth
and possible provider connection limits with the live service. Two failures of
the live VLESS observed during Stage18 Shadow checks are correlated, not
proven caused by those checks. To avoid repeating the risk:

- Refuse a Shadow probe of the selected Mihomo node or **any candidate on
  the same physical server IP/host**, even with a different name or port.
- If the active Mihomo health is not `up` or its selected identity cannot be
  verified, stop before issuing candidate network requests. Re-check before
  each major probe phase, with secure cleanup of the short-lived process.
- Hot Pool shortlists exclude aliases of the active server; successful historical
  proofs alone cannot override the independent live guard.
- The root-owned, opt-in Stage18 runtime in `/dev/shm` requires FFmpeg
  at `/usr/bin/ffmpeg` **in addition** to pinned Node.js and yt-dlp. Missing
  FFmpeg yields `stage18_ffmpeg_unavailable` and never a YouTube PASS.
- On a minimal Debian 13 Pi, preview installation first with
  `sudo apt-get -s install --no-install-recommends ffmpeg`. Install deliberately
  with `sudo apt-get install --no-install-recommends ffmpeg`; it can add a large
  multimedia library tree. Do not automatically install it on a VPN gateway.
- A Stage18 `UNKNOWN` never qualifies READY. Active traffic health may recover
  later independently of a Shadow scan; do not conflate timing with causation.
- If the active transport fails in **Selective** mode, the documented
  FAIL-OPEN/DIRECT policy can expose traffic to the ISP. Transit is fail-closed.
  A missing `awg0.conf` means there is **no AWG fallback** on that test card.
  Never enable automatic selection without a validated independent backup.

No live gateway, MikroTik or SSTP change is performed by these GitHub edits.

## Semantics

- Existing pool latency/HTTPS result is **reachability only**.
- A reserve node requires **two successful, separated by >=10 minutes**, fresh
  one-node `service-scan` passes via the existing RAM-only, TUN-disabled Mihomo.
  Each scan requires OpenAI API PASS, ChatGPT network reachability (HTTP 200 or
  selected 403/challenge signals) and **actual 24-frame YouTube decode**.
  This proves *network suitability*, never authenticated ChatGPT or sustained TUN.
- Qualified checks expire after 60 minutes; a changed subscription digest
  invalidates all node passes. Names and endpoint identity cannot substitute
  for provider-specific credentials; credentials are never saved here.
- A *confirmed active failure*, when eventually wired in, quarantines the
  entire `server:port` endpoint for >=2 hours (including aliases), with bounded
  backoff on repeated failures. A rejected shadow check alone does not condemn
  the endpoint; it only retries the individual node after 20 minutes.
- Maximum two isolated service probes per run. RAM-only state; no microSD
  churn or automatic restoration of unverified qualification after reboot.
- Selector integration is deliberately not enabled yet. Keep the current
  on-demand balanced checks as a fail-safe until the reserve has been trialed.

## Deployment and planned production integration

1. Copy executable to `/usr/local/sbin/awg-mihomo-hot-pool` (root owned).
2. Place matching systemd unit and timer (timer initially disabled).
3. Run `status` and `warm` manually to check performance and memory.
4. Only then enable the timer and observe 24h without switching nodes.
5. Separate patch: selector consumes only fresh `best` choices, still performs
   postactivation health stabilization and quarantines active failures.
6. Never fall back to unsafe DIRECT when reserve is empty. Respect Transit
   FAIL-CLOSED and preserve existing AWG backup priority.

## Tested 2026-10-14 (Novosibirsk)

- 21 local core checks and 6 network gate regression tests passed.
- Legacy latency healthy pool included 143 reachable profiles, of which
  97 had usable globally routable IPv4 literals; the other profiles are
  not passed to the current direct-route-verified service-scan.
- Shadow sandbox permits AF_NETLINK for route lookups but drops CAP_NET_ADMIN.
  Only /run/awg-pbr and /dev/shm are writable; 70 percent CPU quota,
  900 MiB memory cap and five-minute wall time cap are applied.
- Untried candidates are preferred to previously failed candidates, while
  candidates with a first PASS have priority for a qualifying second PASS.
- At 16:46 one candidate named shadowsocks-11045 passed OpenAI API, the
  accepted ChatGPT HTTP 403 network check, and actual 24-frame YouTube
  decode. This is ONE qualifying pass, not READY yet.
- The timer was enabled at 16:50 for a non-mutating shadow observation;
  no production selector integration or change to MikroTik/SSTP took place.
- Next release gate: two separated PASS results plus postactivation TUN-path
  and endpoint-quarantine validation, in a separate reviewed change.

## READY retention and renewal fix (2026-10-14)

The initial top-12 ranking could exclude a still-healthy READY candidate
after a latency spike. More importantly, an oldest qualifying PASS could
expire at 60 minutes because READY nodes were never probed until expiration.

The patch changes only SHADOW selection and verification:

- READY nodes remain prioritized despite changed latency ranking, but only
  while present as healthy in the latest provider-matched live pool, within
  the current policy and with valid recent proofs.
- Refresh READY 25 minutes before its oldest of two proofs expires, provided
  at least ten minutes elapsed since its most recent proof.
- One-pass candidates rank after READY; untested candidates then come next.
  Failed checks stay lower priority and respect the existing retry cooldown.
- Aliases sharing a host:port use exactly one shortlist slot and never count
  as distinct reserve endpoints; aliases of the active endpoint are excluded
  where the active node appears in the healthy pool.
- A failed renewal clears that node's proof; no expired state is ever
  accepted as READY. Source digest changes and quarantine still invalidate.
- Pre-existing expired proofs cannot be revived retroactively. They must
  undergo fresh tests.
- Root-safe installer: apply-ready-retention.sh checks tests first, copies
  executable and unit backups to /run, briefly disables the Hot Pool timer
  during the installation, restores the original timer state, and rolls back
  the files on failure. It never launches a probe or changes the live selector.

Apply on test Pi only with root via:
sudo bash /home/karlinks/awg-hot-pool-shadow/apply-ready-retention.sh

The staged files and PR do not themselves modify the installed service.

## Balanced four-READY Hot Pool scheduler (2026-10-14)

Target: four independently qualified READY endpoints (prefer 2 VLESS,
1 Shadowsocks, 1 Trojan/Hysteria2 when actually eligible), drawn from
a capped shortlist of twelve healthy, provider-matched, unique endpoints.
Diversity is a **preference**, not a waiver of balanced service gates.
Four READY is a capacity target, not a fabricated availability guarantee.

Each 12-minute timer cycle allows at most TWO isolated service probes,
with <=1 minute timer slack. The shorter cadence matters: simulated
20-minute paired renewal permanently consumed both scan slots under
the strict 60-minute two-PASS proof window. Test scenarios with a
12-minute timer and realistic probe duration maintained four READY
and allowed additional discovery without changing qualification rules.

- Maintenance lane renews proven READY before proof expiry; urgent renewals
  take priority when a deadline can be missed before the next scheduled run.
- Discovery lane uses all safe spare scan slots while READY count is below
  four. Prefer previously confirmed one-pass prospects and missing
  protocol types; failed candidates respect retry delays.
- Discovery cannot steal slots needed to keep READY valid. All assignments
  share the original two-probes-per-cycle limit. The timer can run without
  doing any network probe once four READY are stable and none are due.
- Different names with the same public host:port share one shortlist slot.
  The existing 4-per-protocol cap is retained, and no failed, expired,
  quarantined, provider-mismatched or unhealthy node is marked READY.
- Status now includes HOT_POOL_TARGET_READY=4. Warm-run logs include
  HOT_POOL_PLAN_RENEW and HOT_POOL_PLAN_DISCOVER for audit, with no secrets.
- The policy remains SHADOW_ONLY. There is no live TUN or transport
  selector integration; switching and rollback remain a later, explicit test.
- The 12-minute cadence increases the number of timer wakes but does not
  exceed two tests per cycle. Long-term RAM/CPU and microSD impact should
  be reviewed using the ordinary live system counters.

Staged deployment on the test Pi (root required):
sudo bash /home/karlinks/awg-hot-pool-shadow/apply-ready-retention.sh

The existing guarded updater preserves the previous timer-enabled state,
keeps an in-RAM backup, and rejects installation while a shadow probe runs.
The original live Mihomo, SSTP, AWG and routing remain unchanged.

## Cold-connect readiness and SUSPECT retention (2026-10-14)

This SHADOW-only improvement addresses false negatives caused by starting
the full service check the instant an isolated Mihomo controller sees a node.
Controller visibility is NOT proof of a working remote transport.

- A dedicated \`awg-mihomo-hot-service-scan\` starts a fresh, isolated,
  TUN-disabled Mihomo for each selected node using the existing verified
  DIRECT route, subscription and other read-only smart-code helpers.
  Its script does NOT replace the common production \`awg-mihomo-smart\`.
- After controller readiness (max 10s), the script attempts TLS-verified
  HTTPS through that exact loopback proxy, using the existing allowed
  OpenAI API endpoint. It retries up to four times, spending at most 22s
  across attempts. HTTP reachability **only confirms the cold connection**;
  it is not a PASS for OpenAI or ChatGPT. Afterward the unmodified
  balanced gate still requires OpenAI and actual YouTube video frames.
- Logs use only scrubbed fields \`COLD_MS\`, \`CONTROLLER_MS\`, \`WAIT_MS\`,
  \`ATTEMPTS\` and \`CONNECT_FAMILY\`. No raw URLs, server secrets,
  downloaded media or authenticated cookies are persisted. A RAM-only
  bounded twelve-sample history is also kept per node.
- The first UNKNOWN or other inconclusive/negative check after a PASS
  changes the node to **SUSPECT**, retaining previous PASS timestamps
  for forensic analysis and a bounded recovery attempt. A SUSPECT is
  immediately NOT READY and never eligible for failover. The next
  retry is permitted after 10 minutes. A later positive scan only
  restores READY if two separated, unexpired PASS timestamps exist.
- Two consecutive unsuccessful checks clear all PASS proofs and enter
  FAIL (20-minute cooldown). Expiry, provider digest changes, missing
  live-pool health and quarantine continue to invalidate READY.
- The two-probes-per-cycle cap and four-READY target remain unchanged.
  REPAIR/RECOVER slots are bounded within that existing cap, after
  urgent READY renewals and before new discovery.
- As this is still cold-start testing, it does not prove sustained
  operation of four simultaneously connected nondes or activate
  any hot node. Real failover remains a separate gated test.
- 125s max for each isolated scan; the 5-minute systemd one-shot timeout
  and 70% CPU / 900MiB memory budget remain unchanged. The shorter
  12-minute timer is unchanged.

Use the existing guarded root installer to atomically replace only
the SHADOW-only diagnostic components, with rollback in /run:

\`sudo bash /home/karlinks/awg-hot-pool-shadow/apply-ready-retention.sh\`

The unattended live transport selector, TUN, AWG, SSTP, route policies,
MikroTik and main gateway services are never modified.

## 24-hour YouTube / egress geography study (2026-10-14)

Hot Pool uses the *existing* \`awg-mihomo-pool.egress_geo\` code with Cloudflare
\`cdn-cgi/trace\` over the **same isolated Mihomo proxy** after its cold
HTTPS readiness and service tests, before terminating the test instance.
No full-pool geolocation scan is enabled. The existing strict
\`MIHOMO_POOL_REGION=all\` policy and all live routing stay unchanged.

- At most two isolated probes per scheduled cycle; one extra proxied
  HTTPS call per node, with curl's existing 6-second max time.
- Only strictly validated **global IPv4 and two-letter location codes**
  are accepted. Missing trace, malformed/private address, or a timeout is
  GEO=UNKNOWN, **not a service-gate rejection**. The unchanged
  balanced OpenAI + 24-frame YouTube gate decides eligibility.
- Neutral diagnostic fields \`EGRESS_IP\`, \`COUNTRY\`, \`GEO\` and
  \`GEO_REASON\` are printed together with \`YOUTUBE24\` and
  \`VIDEO_REASON\`; geo fields are not supplied to the strict gate.
  The country is what **Cloudflare reports for the outgoing proxy IP**,
  not the country of the provider's entry server or a guaranteed
  YouTube/Google geolocation classification.
- Only sanitized per-check observations are kept in
  \`/run/awg-pbr/hot-pool/shadow.json\` (RAM, root-only mode 0600);
  max 256 records and 24-hour TTL. Old readiness proofs are still
  invalidated on provider changes; historical geo samples survive
  subscription refreshes within the 24-hour window.
- Aggregated non-mutating report, after installation:
  \`sudo /usr/local/sbin/awg-mihomo-hot-pool geo-report\`.
  It groups YouTube PASS/FAIL/UNKNOWN against actual **exit**
  country and IP. Samples are correlated observations, not evidence
  of causation. Never infer READY solely from exit country.
- Shadow scanner timeout bounded to 135s; systemd oneshot remains
  5 minutes, CPUQuota 70%, MemoryMax 900M. No extra disk writes.

The existing guarded install script
\`sudo bash /home/karlinks/awg-hot-pool-shadow/apply-ready-retention.sh\`
atomically updates only the shadow-only tester and can roll back in
\`/run/awg-pbr/hot-pool-backup\`.

## Read-only CLI

- `awg-mihomo-hot-pool status`
- `awg-mihomo-hot-pool best --exclude NAME`
- `awg-mihomo-hot-pool warm` (network probes only; no live switch)
- `awg-mihomo-hot-pool quarantine NAME --reason active-health-failed`
  (future integration hook; never trigger manually based only on ping)

This code is an experimental stage, not a stable v1.3.0 feature.
