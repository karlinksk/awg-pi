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

## Phase H — verified nfqws2 exec failure fix (2026-10-11)

Local SSH operator's first and second A/B attempts both reached A1 (two local
Mihomo controller API 504 errors), but stopped before B1. The second attempt
captured the precise error before cleanup:

```text
NFQWS_EXIT_CODE= 1
NFQWS_STARTUP_LOG= exec of "/run/awg-dpi-test-owner/nfqws2" failed: Permission denied
SANDBOX_CLEAN= True
```

A direct mount inspection on Pi established that **/run is tmpfs mounted
rw,nosuid,nodev,noexec**, whereas **/dev/shm is a separate executable tmpfs**
(rw,nosuid,nodev). The original A/B harness copied a root-owned executable to
/run, which the kernel refused to execute. This failure was unrelated to
VLESS, ISP DPI or nftables. No real NFQUEUE interception was reached.

Fixes applied **in the research branch only**:

- Copy checksum-pinned official ARM64 nfqws2 and its two public Lua files into
  a root-owned, per-run directory under
  `/dev/shm/awg-dpi-nfqws-<24-char run-id>/`. This directory is 0755,
  binary 0755 and Lua files 0644 so nfqws2 can drop privileges to UID 1000.
- Keep sensitive Mihomo profile and test nft configuration **under root-only
  /run**, never on the executable tmpfs. No mount option or partition changed.
- The independent watchdog matches the new exact token-scoped executable
  pathname (also pinned to queue 237 and the destination IP).
- Normal and watchdog cleanup remove both temporary namespace resources and
  the root-owned /dev/shm executable directory, only for the matching session.
- Display bounded startup and nft-parser diagnostics if an isolated test
  fails, rather than losing all logs during cleanup.

Validated on Pi: copied official nfqws2 to a disposable /dev/shm directory,
verified SHA-256 `8788877cd4b3140357dd10524832ca508d47055efae072bc426b887bfea253a7`,
ran **--intercept=0** with both Lua files and the exact test filter; saw
`no intercept quit`. Disposable directory was removed. Updated scripts were
staged on Pi, Python compiled, and read-only preflight again returned
`PRECHECK=PASS`. Production Mihomo healthy and no leftover test namespace.

**Next:** operator reruns the same time-limited SSH A/B command. No successful
NFQUEUE test or DPI result is claimed until that output is reviewed.
