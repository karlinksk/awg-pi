# Health Monitor: systemd stop/recovery contract (v1.3 review)

This review documents and tests **existing** stop semantics. It does not
change runtime routing, unit configuration, or failover selection.

## Source contract

- Installer install.sh generates /usr/local/sbin/awg-pbr-failopen and
  sets ExecStopPost on awg-pbr-health.service.
- src/awg-pbr-health also traps EXIT and performs mode-aware shutdown.
  In Selective mode it removes the VPN policy rule; in Transit mode it
  invokes awg-transit-routing disable.
- The generated post-stop helper **unconditionally** deletes the marked VPN
  policy rule and writes health.state=down. It does *not* itself install
  the Transit nftables guard: that is the separate setup/routing subsystem's
  responsibility.
- Systemd is configured with Restart=always, RestartSec=2, but no
  process watchdog (WatchdogSec). A live process is not automatically
  equivalent to a healthy VPN.

## Tested expectations

| Simulated scenario | Expected behavior |
| --- | --- |
| Selective SIGTERM | EXIT trap removes marked VPN policy, state down |
| Selective post-stop | Repeated deletion is safe, state remains down |
| Selective SIGKILL | No EXIT trap; post-stop helper removes policy |
| Selective healthy restart | First health cycle restores policy, state up |
| Selective unhealthy restart | No VPN policy rule, state down (FAIL-OPEN) |
| Transit SIGTERM | Mode-aware disable called; simulated guard remains |
| Transit restart | Mode-aware apply called, VPN policy and state up |

**Security limitation:** even when the underlying Mihomo process remains
healthy, restarting its Health Monitor can temporarily remove the Selective
VPN policy rule, permitting marked clients to use DIRECT. This is the
existing Selective FAIL-OPEN design, **not** leak prevention. Do not remove
ExecStopPost merely to hide this interval: abrupt termination otherwise
requires equivalent cleanup. Transit must retain its separate FAIL-CLOSED
forwarding guard.

## Reproducing the isolated tests

    python3 -B tests/test_health_systemd_recovery.py

The rootless test harness runs the repository's Health Monitor with fake
ip, transport check, transit routing, and logging tools. It extracts the
**real generated helper and service unit heredocs** from install.sh; only
the helper's hard-coded filesystem paths are redirected to an isolated
temporary directory. No real kernel routes, VPN network traffic, systemd,
Mihomo or nftables are changed.

The Transit guard is *modeled*, not actually enforced by kernel nftables in
these tests. Likewise, simulated post-stop invocation does not establish
systemd timing, restart-limit behavior, or genuine network fail-closed
behavior. Those require separately approved on-device testing with verified
backup and rollback, not on a test Pi with no AWG fallback profile.
