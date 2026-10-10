# Phase F — guarded VLESS baseline in isolated DIRECT namespace

**Observed on Pi 2026-10-11 local +07:00. No zapret2 installed, downloaded or executed.**

## Configuration boundary

- Experimental namespace `awg-dpi-test`, macvlan `awdpi0` over eth0, separate DHCP lease from MikroTik; default route configured ONLY inside namespace.
- Isolated Mihomo with a **single** VLESS+REALITY+Vision profile pointing at `159.89.87.21:28190`. Subscription checksum validated; no node keys, UUIDs, SNI or credentials printed.
- Native Mihomo controller bound to loopback **inside** namespace. HTTP delay checks at 10s against gstatic generate_204 and Cloudflare trace.
- Direct control egress matched host's Russian WAN public IP. No production Mihomo, AWG, MikroTik, SSTP or host nftables/route modifications.

## Independent watchdog experiment

- An independent systemd one-shot timer `awg-dpi-guard-<token prefix>` was scheduled BEFORE namespace creation.
- A unique 24-character session token was embedded in the namespace ownership marker on creation; old/stale timers are required to compare that token and refuse cleanup of a newer session.
- The runner deliberately killed its own process using **SIGKILL** (bypassing Python finally cleanup).
- Journal contained **`WATCHDOG=CLEANED`**, and after timer execution the namespace, interface and ownership marker were absent.
- Production Mihomo remained active and healthy.
- Watchdog refuses cleanup of unowned or unrecognized processes. Only test Mihomo processes whose executable and configuration path match the isolated research sandbox can be terminated.

## Real isolated baseline

| Condition | Result |
| --- | --- |
| Namespace creation / empty nft tables | PASS |
| Separate DHCP lease | PASS |
| Direct public IPv4 equals host DIRECT | PASS |
| Isolated Mihomo started | PASS |
| Native VLESS via Google HTTPS at 10s | **Local controller HTTP 504 (failed)** |
| Native VLESS via Cloudflare HTTPS at 10s | **Local controller HTTP 504 (failed)** |
| All test process and namespace cleanup | PASS |

The failure reproduces **outside the production Pi VPN policy engine** using the same upstream MikroTik and independent DHCP address. It does not by itself prove DPI, and a per-destination MikroTik sniffer for the isolated DHCP identity has not yet been captured. The prior live-Pi sniffer confirmed DIRECT for the production Pi identity only.

## Test source and remaining safeguards

- `research/awg-dpi-netns-sandbox.py`: namespace lifecycle, DHCP and cleanup plus an optional run-id marker.
- `research/awg-dpi-guardian.py`: independent timer cleanup with ownership and PID executable checks.
- `research/awg-dpi-vless-baseline.py`: single-profile VLESS test with 105-second independent recovery timer. It does **not** run zapret2.
- Script copies staged under `/home/karlinks/` on Pi; none installed as production services.
- Never merge this research unreviewed into a stable AWG release.
- Future tests should include a verified on-device nfqws2 binary and Lua dependencies, nft NFQUEUE only in the namespace, explicit packet/endpoint scope, a repeat of the no-intervention baseline and multiple A/B runs with guarded rollback.
- No zapret2 binary deployment or NFQUEUE A/B test is claimed here; pre-installation capability inspection could not be completed through the connected tool.

## Remaining limits

- A timeout-driven guard is not instantaneous; the transient namespace can persist until the guard fires if the controlling process dies unexpectedly.
- Power loss removes the namespace but any dynamic DHCP lease may persist in MikroTik for its normal lifetime.
- This experiment does not check whether the isolated Pi DHCP IP is treated differently by MikroTik policy routing at the tested **destination**. External WAN public IP match is a useful but not exhaustive confirmation.

**Final state**: netns/interface/ownership marker absent, main Mihomo healthy. No changes to production paths.