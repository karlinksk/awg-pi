# IP-literal HTTPS compatibility — isolated review (2026-10-16)

Status: **review-only, not installed**, no changes to live selector, Pi, MikroTik or SSTP.
Base: integration/v1.3.0-rc1-review-20261016 @ `dddd4765d70db7ffd71068d0a914ad123a5f5992`.

## Observations on the **test microSD** (awg-upgrade-test, Selective)

| Selected node | HTTPS through 127.0.0.1:7890 with host CONNECT | HTTPS through the same proxy with IP CONNECT and preserved TLS SNI | Marked TUN HTTPS |
|---|---|---|---|
| shadowsocks-1827968609 (194.38.11.86) | api.ipify.org: HTTP 200 | api.ipify.org to all three locally resolved IPv4: TLS EOF; cloudflare-dns.com to 1.1.1.1: TLS EOF | 104.26.12.205: TLS EOF |
| shadowsocks-1832007528 (194.87.196.107) | api.ipify.org: TLS EOF | api.ipify.org to 104.26.12.205: HTTP 200 | NOT CHECKED; gateway health went DOWN / Selective FAIL-OPEN |
| vless-1828375904 (77.110.105.122) | api.ipify.org: HTTP 200 | api.ipify.org to 104.26.12.205: HTTP 200 | marked IP destination: TLS1.3, HTTP 200, egress 212.87.190.51; iPhone Selective VPN and DIRECT confirmed |

These observations do **not** prove that an entire proxy protocol is defective or that every CDN address is interchangeable. Proxy CONNECT destination may affect both remote DNS choice and protocol-specific handling. A working domain CONNECT is **not** enough to guarantee LAN client traffic, because selective routing uses destination IPs.

## Existing code to reuse

- `src/awg-transport` `check_mihomo`: existing generic health uses live loopback HTTP proxy and api.ipify.org by hostname; it does NOT exercise forwarded TUN.
- `src/awg-mihomo-service-check.py`, `src/awg-mihomo-smart` and `extras/mihomo-hot-pool-shadow/awg-mihomo-hot-service-scan.py`: one-node TUN-disabled RAM-only service eligibility; OpenAI API + ChatGPT network signs + genuine YouTube frame decode. Do not duplicate that work.
- `src/awg-mihomo-network-eligibility.py`: balanced service classifier; unknown/error must never be promoted to PASS.
- `src/awg-mihomo-ready-postcheck-tun`: existing node identity, marked table 100, TUN-bound public egress and OpenAI 401. Confirmed PASS on VLESS in Selective test. Its published `READY_TUN_SCOPE=PI_BOUND_TUN_NOT_FORWARDED_CLIENT` is accurate.
- `src/awg-mihomo-node-policy`: READY AUTO canary invokes the postcheck after activation, with bounded route stabilization and rollback. **Do not** enable READY AUTO or Hot Pool timer during development.

## Proposed minimal safe change (requires review before deployment)

1. Add a **small bounded IP CONNECT compatibility sub-check** to the *existing isolated shadow candidate service scan*, after a domain/TLS readiness check and **before any costly YouTube decode**. Do not open extra video requests. Select test IPv4 addresses using Pi's configured resolver for a *fixed allowlisted HTTPS origin* already checked, e.g. api.openai.com or api.ipify.org. Reject private/reserved/non-global IPs. Maintain correct TLS hostname/SNI and certificate verification, using `curl --connect-to` with HTTP CONNECT to numeric IPv4. Preserve the original shadow proxy pin and NO_PROXY-bypass protections. At most 2–3 bounded addresses/requests and an explicit time budget; fail closed to INELIGIBLE/UNKNOWN, not a claimed region or protocol failure.
2. Extend the **existing** post-activation TUN checker to use a fixed resolved IPv4 destination (`--resolve host:443:IP` bound to `mihomo0`, never the loopback proxy) in addition to existing route, egress, OpenAI 401 checks. Ensure timeouts, one-node identity recheck, and route readiness safeguards remain. A short-lived CDN failure should be a cooldown/UNKNOWN rather than a long quarantine of a shared endpoint. Update the selector's strict allowlisted diagnostic reason if needed.
3. Maintain the security and performance contract: disabled by default until canary; no changes to live health cadence; no additional YouTube/ChatGPT probing; no browser checks; no writes to provider credentials; no MikroTik/SSTP change; no automatic production enablement.
4. Add rootless regression fixtures for domain PASS/IP FAIL, domain FAIL/IP PASS, both PASS, TLS EOF, invalid/non-global DNS answer, DNS rotation, node-change during postcheck, NO_PROXY=*, and timeout. Verify candidate eligibility with synthetic fixtures and no network.
5. Only after offline tests/CI, run supervised A/B tests against both failing Shadowsocks nodes and the working VLESS node on **test microSD**, with the existing VLESS as rollback. Then separately test iPhone forwarded LAN and Transit; do not claim PI-bound TUN alone proves clients.

## Acceptance

- VLESS `vless-1828375904` retains PASS and no extra significant CPU/traffic beyond 2–3 short HTTPS requests.
- First Shadowsocks's domain-only health can no longer authorize IP-dependent forwarding.
- Contradictory results distinguish `DOMAIN_CONNECT`, `IP_CONNECT` and `TUN_POSTCHECK` without implying a global proxy protocol outage.
- No extra global health polling, YouTube HTTP precheck, or changes to live transport until explicit supervised rollout.
