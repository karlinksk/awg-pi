# Research: isolated Mihomo endpoint re-probe (Phase B)

**Never run on the production routing service.** This is a separate program
run on Pi to investigate why some subscription profiles fail the ordinary
4.5-second Mihomo health probe. It does not use zapret2, change rules, or
alter SSTP/active transport.

## Sample
From a pool matching the provider SHA-256 exactly, pick 25 distinct
textual host:port pairs: four failed and one healthy reference from
each of five proxy families (Hysteria2, Shadowsocks, Trojan, VLESS,
VMess). Stable hashed ordering prevents manual cherry-picking.
Count successful re-tests by baseline group; do not extrapolate 25 results to
all 1,869 without confidence intervals.

## Preflight
- Resolve endpoint IPv4 and ensure each sampled IP has an unmarked Pi route
  via \`192.168.112.1 dev eth0\`. Skip non-public, unresolved, non-direct
  or unknown routes. **This does not prove MikroTik uses its WAN/DIRECT
  instead of SSTP**; independently verify MikroTik policy before treating
  the result as a pure ISP/direct-path comparison.
- Run root-only test Mihomo with *no TUN, auto-route, fwmark or nft changes*.
  Runtime config and proxy credentials exist only in a mode-0700 tmpfs
  directory under \`/run\`, removed in a finally block.
- Test a local-controller HTTPS delay probe through the selected proxy
  against two URLs, each with 4,500 ms and 10,000 ms timeouts.
- Perform a raw TCP connect check on TCP-oriented endpoints; this is not
  a valid full proxy-protocol handshake. UDP/QUIC cause is **not** isolated.
- Separate direct HTTPS controls for the target URLs.
- Keep at most six concurrent proxy probe tasks and five DNS preflights.

## Running
Review \`research/mihomo-endpoint-reprobe.py\`, then:
\`\`\`bash
sudo python3 research/mihomo-endpoint-reprobe.py --plan
sudo python3 research/mihomo-endpoint-reprobe.py --run
\`\`\`
No secrets, endpoint addresses or proxy identifiers are printed. No
configuration changes are intended. Output is aggregate only and need
not be persisted to microSD.

## Interpretation
A \`recovered_at_10s\` result suggests the first 4.5s health timeout
may be too strict **for that profile at that time**, not a guarantee
of general service availability. \`api_503\` and \`api_504\` are local
Mihomo API status codes, not remote target website status codes.

A failed TCP dial can be caused by server outage, blocking, transient
routing, firewall, or protocol differences. A successful TCP connection
does not prove usable TLS/authentication/HTTPS, and failures still cannot
be attributed to DPI by this test alone. Need tests from another network
and explicit MikroTik outgoing route verification before DPI claims.

## Out of scope
No automatic node selection, no production installer or updater,
no zapret2 or NFQUEUE, no SSH/firewall changes on MikroTik,
no IP route changes and no credentials in stdout or issues.
