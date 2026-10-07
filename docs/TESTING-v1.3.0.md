# AWG Pi Gateway v1.3.0 — release validation

This document is the hardware/release gate for v1.3.0.

v1.3.0 adds a transport abstraction and an optional Mihomo backend while
preserving the v1.2 routing semantics:

- Selective Gateway remains **FAIL-OPEN**.
- MikroTik Transit / Backup VPN remains **FAIL-CLOSED**.
- AmneziaWG remains a first-class transport and the default on upgrade.
- Mihomo must not own global host routing (auto-route: false,
  auto-redirect: false).
- A Mihomo transport endpoint must stay DIRECT on MikroTik so the VLESS/Reality
  connection never loops through SSTP/another VPN.
- Provider cache is operational state. A failed subscription refresh must not
  destroy the last known-good cache.
- Subscription secrets, UUIDs, Reality keys, HWIDs and full private URLs must
  not appear in normal status/menu output.

## 1. CI gate

Before any RC is installed on hardware, the target commit must pass:

- Bash syntax.
- ShellCheck (-S error).
- all unit/regression tests.
- pinned AmneziaWG v3.1 build.
- real isolated AWG profile preflight.

The installer itself must contain AWG_PI_VERSION="1.3.0", and the release tag
must match that internal version.

## 2. Existing v1.2.0 Pi upgrade gate

Target hardware:

- Raspberry Pi 4 / Debian 13 ARM64.
- existing stable v1.2.0.
- existing AWG configuration preserved.
- existing operating mode preserved.
- existing OpenCCK/domain/client state preserved.

Before upgrade record:

~~~
sudo awg-route status
sudo awg-transport status 2>/dev/null || true
sudo awg show
ip -4 rule show
ip -4 route show table 100
ip -4 route show table 101
systemctl --failed --no-pager
~~~

Upgrade from an RC/develop ref only with an explicit ref. Do not change the
stable tag until the release gate is complete.

Expected after upgrade:

- /etc/awg-pbr/version is 1.3.0.
- active transport is still awg.
- the previous Selective/Transit mode is unchanged.
- awg0 handshake is fresh.
- table 100/101 and mode semantics remain correct.
- Transit guard is SAFE in Transit mode.
- Mihomo components are installed passively; Mihomo is not selected
  automatically.
- no failed systemd units.

## 3. Upgrade rollback coverage

awg-update backup/restore must include the complete v1.3 state:

- /etc/awg-pbr
- /var/lib/awg-pbr/mihomo
- /usr/local/bin/mihomo when present
- /usr/local/lib/awg-pi
- awg-transport
- all awg-mihomo-* helpers
- Mihomo systemd service/update units

A failed gateway update must restore the previous version and leave the gateway
usable on the previous transport.

## 4. Mihomo first-run onboarding

The active datapath must remain on AWG during initial Mihomo setup.

For a provider that is not reachable DIRECT (the observed Citadel case), AUTO
bootstrap must be able to obtain the provider using an available transport.

AUTO bootstrap order:

1. current healthy Mihomo proxy (when available)
2. AmneziaWG
3. router/default path

The router/default path means Pi -> MikroTik. MikroTik may then keep the request
DIRECT or policy-route it through SSTP/another router-side VPN.

Required checks:

- subscription URL can be entered through the protected menu flow.
- full URL/token is not echoed in status.
- local provider-file import works without network.
- invalid/empty provider never replaces the working cache.
- failed refresh leaves the last valid provider cache intact.
- Last fetch path reflects the successful bootstrap path.

## 5. Provider/node discovery

After a valid provider cache exists:

~~~
sudo awg-mihomo-configure node list
~~~

The list must expose only safe metadata needed for selection, such as node name,
type, server and port. It must not expose UUIDs, Reality keys, short IDs,
passwords or full private subscription URLs.

Prepare a candidate:

~~~
sudo awg-mihomo-configure node prepare "<node name>"
~~~

Resolve one IPv4 transport endpoint and verify that endpoint independently of
the expected public egress IP.

## 6. MikroTik DIRECT protection

Before selecting a Mihomo node, its transport endpoint must bypass SSTP/VPN
policy on MikroTik.

The release test should use a narrowly scoped early mangle accept rule for:

- source: Pi LAN IPv4
- destination: selected transport endpoint IPv4
- protocol/port where known

Apply router changes in RouterOS Safe Mode and verify that the endpoint uses the
normal WAN/main route rather than r_to_vpn.

Do not disable SSTP as part of this test.

## 7. Manual/Fixed node selection

v1.3.0 ships with Manual/Fixed as the baseline node-selection mode.

The selected node must be applied transactionally:

1. provider cache already valid
2. candidate node found
3. endpoint resolved
4. MikroTik DIRECT protection confirmed
5. runtime config rendered
6. mihomo -t succeeds
7. Mihomo service becomes healthy
8. only then may the user select the Mihomo transport

If node reconfiguration fails, the previous working node/config/cache must stay
usable.

## 8. AWG -> Mihomo hardware switch

Only after sections 1–7 pass:

~~~
sudo awg-transport select mihomo
~~~

Expected:

- mihomo0 exists.
- active transport reports mihomo.
- Mihomo health is healthy.
- selected VLESS/Reality endpoint is connected DIRECT through MikroTik.
- public egress matches the selected node/provider expectation when that
  expectation is configured.
- Transit mode remains FAIL-CLOSED.
- Transit guard remains SAFE.
- Selective mode retains FAIL-OPEN semantics.
- DNS/OpenCCK behavior is unchanged.

Record:

~~~
sudo awg-route status
sudo awg-transport status
ip -4 rule show
ip -4 route show table 100
ip -4 route show table 101
ss -ntp
systemctl --failed --no-pager
~~~

## 9. Mihomo -> AWG rollback switch

Verify the normal return path:

~~~
sudo awg-transport select awg
~~~

Expected:

- active transport is awg.
- table 100/101 point to the AWG transport as appropriate.
- AWG handshake remains fresh.
- Transit guard is SAFE in Transit mode.
- user traffic works through the original v1.2-style AWG path.

This switch is required before the release candidate is accepted.

## 10. Provider outage/cache test

With a valid cache already present, make the provider URL temporarily
unreachable or use an isolated test namespace/mocked fetch failure.

Expected:

- Mihomo can start from the last valid cache.
- provider refresh reports failure without deleting/replacing the cache.
- active transport remains healthy if the selected node itself is reachable.

## 11. microSD/write sanity

Mihomo runtime logs must not introduce persistent high-volume writes.

Verify that:

- runtime logging is warning-level or lower-volume.
- temporary/test logs use tmpfs where practical.
- no high-frequency updater timer was introduced.
- provider updates are periodic and atomic rather than continuously rewriting
  cache files.

## 12. Release acceptance

A v1.3.0 RC is acceptable only after all of the following are true:

- CI is green.
- existing v1.2.0 upgrade on the real Pi passes.
- AWG remains unchanged immediately after upgrade.
- first-run Mihomo onboarding succeeds.
- blocked provider download succeeds through AUTO bootstrap.
- manual node selection succeeds with MikroTik DIRECT protection.
- AWG -> Mihomo switch succeeds.
- Mihomo -> AWG switch succeeds.
- failure/rollback scenarios preserve connectivity and cached state.
- no secrets appear in status/menu/test evidence.
- no unexpected microSD write regression is observed.

Only then should the v1.3.0 tag/release become the stable updater target.
