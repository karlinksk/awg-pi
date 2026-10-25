# Experimental Xray VLESS/Reality adapter (opt-in)

**Architecture:** Mihomo stays the primary TUN router; AWG is a fallback when configured. Xray v26.3.27 is an additional **TCP outbound only** for VLESS Reality XHTTP and gRPC, never a replacement TUN.

## Using the existing HoneyVPN subscription

HoneyVPN is already imported by the ordinary Mihomo provider pipeline: 11 profiles in the tested subscription, including six Hysteria2 and five VLESS. **There is no separate Xray subscription URL.**

After post-install onboarding adds a subscription, the optional manager reads the root-owned Mihomo subscription cache. It validates an exact VLESS profile and stores only a SHA256 identity (not credentials). On service start, it checks this identity against the current provider. Changed/missing profiles fail closed; original provider files are never modified.

The clean installer includes the pinned, SHA256-verified official ARM64 Xray 26.3.27 core, root-only manager and hardened service even if no profiles have been configured. **The service is never started or enabled automatically by the installer or updater.**

## Manual local exploration

These commands apply **only after** the user has imported a provider through the normal Mihomo menu:

    sudo awg-xray-install status
    sudo awg-xray-vless list
    sudo awg-xray-vless select 1   # example index, check list first
    sudo systemctl start awg-xray-vless.service
    sudo awg-xray-vless status
    curl -4 --socks5-hostname 127.0.0.1:17892 --noproxy '' \
      --max-time 20 -o /dev/null -w '%{http_code}\n' \
      https://api.openai.com/v1/models

The port is 127.0.0.1:17892 only; it is **never exposed to LAN/WAN**. A loopback SOCKS5 client can reach Xray, while Xray dials VLESS via the protected direct uplink interface rather than through Mihomo TUN. UDP/QUIC is intentionally unsupported in this first TCP-only adapter.

HTTP 401 from OpenAI API without an API key confirms HTTPS reachability, not API authentication. ChatGPT Web HTTP 403 is UNKNOWN. Only actual YouTube **24-frame ffmpeg decode** may count as YouTube PASS. No primary HTTP/Range shortcut.

The versioned Mihomo config generator has an explicitly disabled-by-default option MIHOMO_XRAY_VLESS_BRIDGE=1 that adds the named local SOCKS5 output AWG-XRAY-VLESS-LOCAL to a generated Mihomo selection group. No production group/config changes without a guarded apply and post-switch verification. This is NOT an automatically READY/FIXED-eligible candidate. If the Xray daemon stops, attempts to use this output fail closed. Ordinary nodes, independent DNS, priority SSTP and existing fallback policy are unaffected.

## Security and lifecycle

- Selection fingerprint is root-only and contains no UUID or Reality key.
- Ephemeral Xray config (containing credentials) resides in /run/awg-pbr/xray-vless, root-only 0600. It is rebuilt from the protected provider on start. The systemd unit deletes the temporary config on stop.
- systemd service has ProtectSystem=strict, ProtectHome and a restricted capabilities/network address-family set; no automatic activation or route changes.
- The gateway backup includes the pinned binary, service, helper and stored selection. The running RAM config is not archived.
- Subscription refresh does not silently reconfigure an already-running Xray service. Stop/revalidate/restart after subscription change; stale identity cannot start a new service.
- During the first experimental phase, no automatic Mihomo→Xray promotion, READY admission, LAN routing or failover is claimed.

## Evidence, 2026-10-19 on the authorized test Pi

In isolated **proxy-only** tests, Xray 26.3.27 passed native config validation and a separate Mihomo HTTP proxy → Xray local SOCKS5 → HoneyVPN VLESS connection:
- XHTTP (first VLESS in the current provider): OpenAI HTTPS HTTP 401, ChatGPT Web HTTP 403 UNKNOWN, YouTube **24 decoded frames PASS**.
- gRPC (fifth VLESS in the current provider): OpenAI HTTPS HTTP 401, ChatGPT Web HTTP 403 UNKNOWN, YouTube24 **UNKNOWN** due to yt-dlp bot challenge.

No live Mihomo service, actual TUN, FIXED chain, Pi LAN-client route or MikroTik rule was changed. Tests through the isolated proxy are **not** production TUN/LAN/READY/failover PASS. Real optional bridge TUN, LAN, provider-refresh, outage and reboot gates remain OPEN.

This adapter is an independent experimental PR layered on draft PR #115. It must not delay or silently expand the release gate for v1.3.0; no merge or release before tests and explicit owner approval.

## Experimental guarded failover executor (2026-10-19)

The versioned installer now includes **disabled-by-default** transaction components:
`awg-xray-activation-transaction` (state-machine safety checks) and
`awg-xray-live-backend` (Linux operations, independent timer watchdog,
Transit fail-closed on failure). Neither is invoked by the installer, a node
policy, systemd timers, or Hot Pool. The executable `apply` action is
test-Pi gated and must not be advertised as installed/working AUTO failover.

The transaction explicitly rejects the original failed node, duplicate or
rotated candidate identities, stale basic-network eligibility and missing
TUN postcheck. Before switching it arms a watchdog; on failure it disables
Transit policy under the existing nftables guard, stops unverified services
and removes transaction-owned boot wiring without restoring the failed node.
Systemd boot dependencies are staged only after TUN validation. Cancellation
of a failed watchdog arm cannot stop a previously healthy gateway later.

**Acceptance still open:** real interrupted-activation recovery, actual
Mihomo -> Xray TUN failover on the test Pi, reboot and boot ordering, LAN/WG
forwarding, AWG fallback if configured, subscription rotation during failover,
and independent proof that management SSH/SSTP remains accessible. Mock tests,
isolated Xray proxy tests and the earlier manual healthy-HY2 canary are
different evidence scopes. No runtime service or MikroTik configuration was
modified while developing this versioned executor. Release v1.3.0 and PR
#115 remain gated by clean install, LAN, failover and reboot validation.
