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
- /var/lib/awg-pbr/traffic
- /usr/local/bin/mihomo when present
- /usr/local/lib/awg-pi
- awg-transport and awg-traffic
- all awg-mihomo-* helpers
- Mihomo systemd service/update units
- selection-monitor and traffic-accounting units

A failed gateway update must restore the previous version and leave the gateway
usable on the previous transport.

## 4. Mihomo first-run onboarding

On a fresh install the first transport is chosen before Operating Mode. The
wizard must support either AWG or Mihomo as the first backend without assuming
that the other one already exists.

For Mihomo first-run the interactive flow must support:

1. subscription URL or local/pasted provider input;
2. provider profile/format validation;
3. safe live-node listing;
4. exact selection of the first node and one resolved IPv4 endpoint;
5. optional ordered exact-node fallback chain (2+ explicit nodes);
6. activation of Mihomo as the first transport;
7. Operating Mode selection only afterward.

For a provider that is not reachable DIRECT, AUTO bootstrap must be able to use
an already healthy transport. AUTO bootstrap order is:

1. DIRECT through the normal Pi LAN/uplink;
2. the currently selected healthy transport, if one exists;
3. other configured healthy transports explicitly supported by the bootstrap manager.

Router-side SSTP/VPN is not a required bootstrap dependency. Pi-originated
transport/control traffic must retain the gateway-wide DIRECT invariant so that
a new transport is not accidentally configured through itself.

Required checks:

- subscription URL can be entered through the protected menu flow;
- full URL/token is not echoed in status;
- local provider-file import works without network;
- invalid/empty provider never replaces the working cache;
- failed refresh leaves the last valid provider cache intact;
- Last fetch path reflects the successful bootstrap path;
- declining node failover leaves Mihomo node policy MANUAL;
- accepting it saves only the exact ordered node names entered by the user.

### Provider adapter independence gate

v1.3.0 must not depend on Citadel/Remnawave or on one subscription encoding.
Every raw provider input is normalized into the same internal Mihomo
`proxies:` provider before node selection or runtime preparation.

Required adapter formats for v1.3.0:

- native Mihomo/Clash YAML with a non-empty `proxies:` list;
- plain `vless://` URI subscriptions;
- Base64 or URL-safe Base64 containing a VLESS URI subscription.

AUTO format detection is the default. The operator must also be able to force
`mihomo`, `vless` or `base64` manually when autodetection is ambiguous.

For VLESS URI conversion the supported release baseline is:

- transport: TCP, WebSocket, gRPC;
- security: none, TLS, Reality;
- common SNI, fingerprint, flow, ALPN, Reality public-key/short-id and
  WebSocket/gRPC options.

Unknown transport/security modes must fail closed at the adapter: they must not
silently drop URI parameters or replace the last known-good provider cache.

Before stable release, hardware/release evidence must include at least:

1. one native Mihomo YAML provider path (Citadel/Remnawave is acceptable here);
2. one **non-Citadel provider format** using plain VLESS URI or Base64 VLESS;
3. both inputs normalize to a safe provider cache and expose nodes through the
   same `node list / node prepare / node select` workflow;
4. a format mismatch or unsupported VLESS mode is rejected without changing the
   working cache.

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

All Pi-originated transport/control traffic must bypass router-side SSTP/VPN
policy. This gateway-wide invariant replaces per-endpoint MikroTik rules for
normal node changes.

For every selected Mihomo node, verify that its resolved endpoint uses the
normal main route through the home router/LAN and never recursively traverses
the Pi transport, SSTP, or another VPN path. The same invariant applies to AWG
transport endpoints and bootstrap/control downloads.

Do not disable SSTP as part of this test. SSTP remains the priority management
link and should not be disturbed by transport validation.

## 7. Manual/Fixed node selection

v1.3.0 ships with MANUAL and FIXED exact-node policy.

FIXED is an explicit one-way ordered chain. Only nodes after the current exact
node may be tried automatically; the chain never wraps back to an earlier node.
Country inference is disabled. A healthy current node is sticky and there is no
performance-based return to a previous node.

Example release chain:

~~~text
Finland -> Estonia -> Latvia -> Sweden
~~~

If the last allowed node fails, exact-node recovery is exhausted and transport
selection gets the next chance (for example Mihomo -> AWG).

The selected node must be applied transactionally:

1. provider cache already valid;
2. candidate node found;
3. endpoint resolved;
4. gateway-wide DIRECT protection confirmed;
5. runtime config rendered;
6. mihomo -t succeeds;
7. Mihomo service becomes healthy;
8. dataplane/health monitoring is restored.

If node reconfiguration fails, the previous working node/config/cache must stay
usable. The TUI and fresh-install wizard must both support configuring the full
ordered chain, not only one primary/fallback pair.

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

## 9a. Transport selection policy gate

Transport selection is independent from Mihomo node selection.

Required modes:

- MANUAL: no automatic transport switching.
- FIXED: explicit primary plus fallback order, triggered only by repeated health
  failure. A healthy fallback is sticky; there is no automatic failback.
- AUTO: explicit allowed transport order, availability-only. It must never
  switch a healthy current transport for latency, throughput, preference or
  performance reasons.

Hardware evidence must cover both AWG -> Mihomo and Mihomo -> AWG failover with
a stopped standby backend, plus conservative AUTO stickiness after the alternate
backend recovers.

Exact-node recovery has priority while active transport is Mihomo. Only after
the ordered node-chain is exhausted may transport-level failover run.

## 10. Provider outage/cache test

With a valid cache already present, make the provider URL temporarily
unreachable or use an isolated test namespace/mocked fetch failure.

Expected:

- Mihomo can start from the last valid cache.
- provider refresh reports failure without deleting/replacing the cache.
- active transport remains healthy if the selected node itself is reachable.

## 11. microSD/write sanity

Mihomo runtime logs and traffic accounting must not introduce persistent
high-volume writes.

Verify that:

- runtime logging is warning-level or lower-volume;
- temporary/test logs use tmpfs where practical;
- no high-frequency provider updater timer was introduced;
- provider updates are periodic and atomic rather than continuously rewriting
  cache files;
- transport traffic is sampled into /run (RAM);
- the first sample establishes a baseline and does not claim interface bytes
  accumulated before accounting was enabled;
- persistent traffic state is checkpointed no more often than the configured
  low-write interval (default 21600 seconds / 6 hours), plus initial baseline,
  clean shutdown and period rollover;
- awg0/mihomo0 recreation is detected by interface identity;
- reboot is detected by boot identity even if Linux reuses the same interface
  index, so counter resets do not silently corrupt today/month totals.

## 12. Release acceptance

A v1.3.0 RC is acceptable only after all of the following are true:

- CI is green.
- existing v1.2.0 upgrade on the real Pi passes.
- AWG remains unchanged immediately after upgrade.
- fresh first-run can choose either AWG or Mihomo before Operating Mode.
- first-run Mihomo onboarding selects the initial exact node and can save a
  multi-node ordered fallback chain interactively.
- blocked provider download succeeds through DIRECT-first AUTO bootstrap with
  healthy Pi-transport fallback when DIRECT is unavailable.
- provider adapters pass native Mihomo YAML plus at least one non-Citadel
  VLESS/base64 format.
- manual node selection succeeds with gateway-wide Pi transport/control DIRECT
  protection.
- the ordered exact-node chain advances only forward and exhausts into
  transport-level fallback.
- FIXED AWG -> Mihomo and Mihomo -> AWG failover both succeed from realistic
  standby states.
- conservative AUTO switches only on repeated health failure and retains a
  healthy current transport after the alternate backend recovers.
- Selective remains FAIL-OPEN and Transit remains FAIL-CLOSED throughout all
  transport/node transitions.
- the TUI exposes the system dashboard, timezone control, unified VPN/OpenCCK
  destination entry, full ordered node-chain editor and traffic statistics.
- today/month transport traffic accounting survives interface recreation,
  samples in RAM and uses low-frequency persistent checkpoints.
- failure/rollback scenarios preserve connectivity and cached state.
- no secrets appear in status/menu/test evidence.
- no unexpected microSD write regression is observed.

Only then should the v1.3.0 tag/release become the stable updater target.


## 13. Raspberry Pi live evidence — 2026-10-08

Hardware/live validation on Raspberry Pi 4, Debian 13 ARM64, LAN
`192.168.112.0/24`, Pi `192.168.112.34`, MikroTik `192.168.112.1`.
Validated code head: `bceb06847f9ec273399bf97c1cf48882d431d591`.

### CI and local regression

GitHub Actions run `37734894001` passed both jobs:

- `shell`: Bash syntax, ShellCheck and all unit/regression tests;
- `awg-v31`: pinned AWG v3.1 build and real isolated profile preflight.

The same Pi also passed the targeted local regression gate:

- first-transport wizard (AWG and Mihomo onboarding);
- existing transport is never silently replaced;
- FIXED/AUTO transport-selection policy;
- exact-node FIXED validation, no wrap-back and exhaustion behavior;
- low-write traffic baseline, deltas, interface recreation, rollover and reboot
  identity handling;
- TUI/menu regression.

### Live UX/traffic deployment

The v1.3 UX completion was deployed transactionally with backup
`/root/awg-v13-ux-pre-20261008-125710`.

Post-deploy invariants:

- Operating Mode: Transit;
- active transport: AWG, healthy;
- Transit guard: SAFE;
- transport selection: MANUAL;
- Mihomo node policy: MANUAL;
- Mihomo standby: inactive;
- `awg-traffic.service`: enabled and active;
- no failed systemd units.

Installed `awg-first-run`, `awg-menu`, `awg-route`, `awg-update`,
`awg-traffic` and `awg-traffic.service` matched the repository blobs.

Traffic accounting started from a zero baseline instead of claiming historical
`awg0` bytes. A controlled AWG health probe produced a 1.48 KiB delta. The
runtime state in `/run` changed while the persistent state mtime stayed
unchanged, confirming that normal samples are RAM-only and do not write the
microSD before the low-write checkpoint.

### Live transport failover

FIXED `AWG -> Mihomo` passed with Mihomo initially stopped:

- automatic switch occurred after repeated health failure;
- `table 100` moved to `mihomo0`;
- Mihomo endpoint `45.86.66.170` stayed DIRECT through the LAN router;
- observed Mihomo proxy egress was `45.86.66.170`;
- Transit guard remained SAFE;
- simulated Transit FAIL-CLOSED and restore both passed;
- final baseline returned to AWG / MANUAL with Mihomo inactive.

Reverse FIXED `Mihomo -> AWG` also passed:

- AWG remained a healthy standby;
- automatic switch occurred after repeated Mihomo health failure;
- fallback AWG stayed sticky and did not automatically return to Mihomo;
- FAIL-CLOSED and restore both passed.

Conservative AUTO passed in both directions:

- AWG failure switched to Mihomo only after repeated health failure;
- recovering AWG did not move a healthy current Mihomo;
- Mihomo failure switched to AWG only after repeated health failure;
- recovering Mihomo did not move a healthy current AWG;
- performance optimization remained disabled;
- FAIL-CLOSED and restore passed;
- final baseline returned to AWG / MANUAL / Mihomo inactive.

### Exact-node chain evidence

The live selection-monitor journal records the explicit one-way chain:

~~~text
🇫🇮 Finland -> 🇪🇪 Estonia
🇪🇪 Estonia -> 🇱🇻 Latvia
🇱🇻 Latvia -> 🇸🇪 Sweden
~~~

After the last exact node was exhausted, transport fallback `mihomo -> awg`
occurred. This provides live evidence for ordered exact-node recovery before
transport-level fallback and no country inference. The working baseline was
subsequently restored to Mihomo node policy MANUAL with Finland selected.

### Additional live multi-protocol validation — 2026-10-09

The same Raspberry Pi 4 / Debian 13 ARM64 stand was then used to validate the
final Mihomo health-pool and multi-protocol work on the public
`Au1rxx/free-vpn-subscriptions` Clash provider.

The provider contained 1772 nodes. A full all-protocol isolated scan completed
in 15m16s and found 188 healthy nodes:

- Trojan: 81 healthy;
- Hysteria2: 45 healthy;
- VLESS: 30 healthy;
- VMess: 18 healthy;
- Shadowsocks: 14 healthy.

Protocol-scoped scanning was also validated. For example, the same provider
contained 786 VLESS nodes and the isolated VLESS scan found 38 healthy nodes
without disturbing the live transport.

Real runtime activation was confirmed for all protocol filters exposed by the
v1.3 TUI:

- VLESS;
- Trojan;
- Hysteria2;
- Shadowsocks;
- VMess.

The all-protocol AUTO node policy was then tested end-to-end. With VMess active,
`awg-mihomo-pool best live` selected a Hysteria2 node, and
`awg-mihomo-node-policy failover` switched
`vmess-197954839 -> hysteria2-1725316146`. The previous node entered
cooldown, the new public egress changed, and the active Mihomo transport
remained healthy. This confirms that AUTO can choose the best healthy node
across protocol types when `MIHOMO_POOL_PROTOCOL=all`.

Earlier in the same validation sequence, automatic exact-node recovery also
switched a failed Estonia node to Sweden after repeated active-Mihomo health
failure, without transport fallback. This confirms selection-monitor integration
with the health pool and cooldown behavior.

The daily provider refresh path was upgraded to a transactional safe auto-refresh
and tested against the live public subscription. An unchanged refresh reported
`MIHOMO_PROVIDER_AUTO_REFRESH=UNCHANGED`, created no candidate, preserved the
current node and left the Mihomo service/transport healthy. Changed-provider
promotion, rollback and MANUAL/FIXED/AUTO policy cases remain regression-tested
in CI.

The TUI was also hardened so an already-applied candidate is not confused with
a missing prepared profile: after successful commit the candidate is promoted
to live and cleared, while the menu explicitly shows whether a prepared profile
exists and directs live search/filter/statistics to the live-node menu.

### Still required before stable v1.3.0

The multi-transport implementation and real Pi runtime validation are now
substantially complete, but stable tagging must still wait for the remaining
release gates that require a separate environment or planned interruption:

1. one destructive clean install from a fresh Debian image using the current
   v1.3 head (the first-run logic is regression-tested, but the working Pi was
   not wiped for this test);
2. one live non-Citadel provider specifically using the plain VLESS URI or
   Base64 VLESS adapter path. The public Clash YAML provider validates a
   non-Citadel native Mihomo source, but does not replace this adapter-specific
   gate;
3. a deliberate post-v1.3 reboot/persistence hardware check after scheduling an
   acceptable gateway interruption.

Until those three gates pass, `main` / the latest stable GitHub release should
remain v1.2.0 and the stable updater target must not move to v1.3.0.
