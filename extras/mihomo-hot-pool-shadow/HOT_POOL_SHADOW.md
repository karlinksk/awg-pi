# Mihomo hot reserve — shadow prototype

**Scope: NOT a production selector.** This module creates a separate eligibility
record for nodes of the existing healthy pool. No TUN, transport, policy,
SSTP/MikroTik, DNS, nftables or forwarding changes. `best` is reporting only.
The timer/service are provided for review but **not installed/enabled**.

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

## Operations after code review (not done yet)

1. Copy executable to `/usr/local/sbin/awg-mihomo-hot-pool` (root owned).
2. Place matching systemd unit and timer (timer initially disabled).
3. Run `status` and `warm` manually to check performance and memory.
4. Only then enable the timer and observe 24h without switching nodes.
5. Separate patch: selector consumes only fresh `best` choices, still performs
   postactivation health stabilization and quarantines active failures.
6. Never fall back to unsafe DIRECT when reserve is empty. Respect Transit
   FAIL-CLOSED and preserve existing AWG backup priority.

## Read-only CLI

- `awg-mihomo-hot-pool status`
- `awg-mihomo-hot-pool best --exclude NAME`
- `awg-mihomo-hot-pool warm` (network probes only; no live switch)
- `awg-mihomo-hot-pool quarantine NAME --reason active-health-failed`
  (future integration hook; never trigger manually based only on ping)

This code is an experimental stage, not a stable v1.3.0 feature.