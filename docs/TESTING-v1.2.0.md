# AWG Pi Gateway v1.2.0 hardware validation

This is the release-gate checklist for the v1.2.0 Selective + MikroTik Transit
implementation. Do not tag v1.2.0 until the required Raspberry Pi and MikroTik
checks pass.

## 1. Test branches

Development base:

```text
develop/v1.2.0
```

Implementation branch:

```text
feature/v1.2-transit-datapath
```

Current release candidate:

```text
rc/v1.2.0-rc9
```

RC9 is a documentation-only freeze on top of the hardware-validated RC8 runtime.
It records the completed non-empty v1.1 -> v1.2 Selective preservation test and
the successful Selective -> Transit -> Selective round-trip after the RC8
DIRECT-precedence fix.

RC8 keeps the RC7 TUI mode indicator and fixes a Selective-mode DIRECT
precedence bug discovered by the non-empty v1.1 -> v1.2 hardware regression.
A manual DIRECT parent such as `youtube.com` must also keep its subdomains
DIRECT. dnsmasq chooses the most-specific matching domain directive, so a more
specific OpenCCK/VPN child such as `accounts.youtube.com` could previously
populate `vpn4` instead of the parent DIRECT nftset. RC8 omits every
VPN/OpenCCK domain directive already covered by a manual DIRECT rule and adds a
regression test for both parent-DIRECT and child-DIRECT cases.

RC7 keeps the RC6 clean-install race fix and adds persistent operating-mode
identification in the SSH TUI. The dialog backtitle, main-menu title, System
screen and Operating mode screen now make SELECTIVE/TRANSIT visible at a glance;
the currently active mode is explicitly marked in the mode selector.

RC6 fixed the clean-install race found during final diagnostics. With Transit
already active, the health monitor could request a base-ruleset rebuild at the
same time as an explicit `awg-route reload`. Two concurrent
`awg-pbr-setup` processes could then race while replacing
`/etc/nftables.d/99-awg-pbr.nft`, causing GNU `install` to fail with
`File exists`. The setup transaction is serialized with a dedicated runtime
lock and covered by a concurrent-setup regression test.

For hardware testing, use the frozen RC ref explicitly so the installer does
not expect an unreleased v1.2.0 tag:

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/rc/v1.2.0-rc9/install.sh -o /tmp/install-v1.2-rc9.sh
sudo AWG_PI_REF=rc/v1.2.0-rc9 bash /tmp/install-v1.2-rc9.sh
```

## 2. Baseline status

Record:

```bash
sudo awg-route mode status
sudo awg-route status
sudo systemctl --failed --no-pager
sudo systemctl is-active awg-pbr-setup.service dnsmasq.service awg-quick@awg0.service awg-pbr-health.service
sudo ip -4 rule show
sudo ip -4 route show table 100
sudo nft list table inet awg_pbr
```

Expected after a successful fresh install: `Mode ID: transit`. The installer
temporarily stages Selective while AWG is validated, then switches to Transit
transactionally. If Transit preflight fails, the safe fallback is
`Mode ID: selective`.

## 3. Selective regression

Before testing Transit, re-run the v1.1.0 behavior:

- DIRECT traffic stays through the normal LAN router.
- One VPN-list domain routes through `awg0`.
- DIRECT exception wins over a VPN rule.
- OpenCCK domain/IP/CIDR sources still work.
- client allow-list semantics are unchanged.
- `vpn off` is FAIL-OPEN/DIRECT.
- reboot preserves Selective mode and all saved lists.

Record `awg-route diagnostics` after the test.

## 4. Transit preflight

With AWG healthy:

```bash
sudo /usr/local/sbin/awg-transit-preflight
```

Required results include:

```text
OK: IPv4 forwarding is enabled
OK: main IPv4 route is DIRECT ...
OK: MikroTik/router MAC resolved ...
OK: AWG tunnel transport is usable
OK: AWG handshake is fresh ...
OK: AWG endpoint stays DIRECT ...
TRANSIT_PREFLIGHT=OK
```

The endpoint route must show the MikroTik/LAN path, never `awg0`.

## 5. Mode switch: Selective -> Transit

```bash
sudo awg-route mode transit
sudo awg-route mode status
sudo awg-route status
sudo nft list chain inet awg_pbr forward_guard
sudo ip -4 rule show
sudo ip -4 route show table 100
```

Required:

- mode is `transit`;
- Transit guard is SAFE;
- healthy AWG gives ACTIVE policy + READY VPN table;
- if router/MAC discovery is deliberately made unavailable during Transit
  setup, the live guard reports LOCKDOWN rather than exposing LAN forwarding;
- forward ingress contains the MikroTik Ethernet source MAC restriction;
- no LAN->LAN accept fallback exists in the Transit forward chain;
- no DNS redirect rules exist in Transit;
- Pi management/default traffic remains DIRECT;
- an OpenCCK timer refresh in Transit updates cache files without rebuilding the
  live Transit nftables datapath.

## 6. MikroTik -> Pi -> AWG datapath

After applying the RouterOS configuration from
`docs/MIKROTIK-TRANSIT-v1.2.0.md`, send only a small test client/prefix through
the backup table first.

Verify:

- primary healthy path uses SSTP;
- forced SSTP failure sends the selected test traffic to the Pi;
- the Pi forwards it through `awg0`;
- non-selected clients remain on their normal routing policy;
- Pi SSH remains reachable.

For production-style health testing, do not rely only on SSTP
`running=yes`. The documented two-probe Netwatch design must also pass:

- one probe DOWN: no failover;
- both probes DOWN: disable only the SSTP policy default route and activate Pi;
- SSTP interface can remain RUNNING while its policy route is withdrawn;
- both probes UP: restore the SSTP policy default and return Pi to standby;
- probe blackholes prevent health checks from escaping through Pi or normal WAN.

Capture relevant MikroTik route/Netwatch state and:

```bash
sudo nft list table inet awg_pbr
sudo awg-route status
```

Avoid publishing raw tunnel secrets. `awg-route status` must redact private,
preshared and header-protection keys.

## 7. Transit FAIL-CLOSED

While MikroTik is using the Pi backup, make AWG unhealthy without removing the
LAN connection to the Pi.

Expected:

```bash
sudo awg-route status
```

shows Transit health down / policy FAIL-CLOSED. Selected traffic must not appear
on the Pi's ordinary LAN Internet path.

Restore AWG. The health monitor should re-enable Transit policy automatically.

## 8. Return to Selective

```bash
sudo awg-route mode selective
sudo awg-route mode status
sudo awg-route status
```

Verify all pre-existing VPN/DIRECT/OpenCCK/client state is still present and
classification works again without recreation.

Return to Transit and verify the preflight succeeds again, Transit reports
SAFE/ACTIVE/READY, and the AWG endpoint remains DIRECT in both modes.

## 9. Reboot persistence

Test one Raspberry Pi reboot in each mode.

After each reboot verify mode, services, nftables table, policy state, DIRECT
AWG endpoint path and connectivity.

A RouterOS reboot-persistence test for the optional MikroTik Netwatch automation
is recommended after an external RouterOS backup/export has been saved. It may
be deferred when the only administrative path depends on the same remote router.

## 10. TUI usability and profile paste

Run `sudo awg-menu` on a real SSH terminal and verify:

- the active operating mode is always obvious: the dialog backtitle and main
  menu show `SELECTIVE` or `TRANSIT`, the System screen repeats the badge,
  and the Operating mode screen marks the current choice with `[ТЕКУЩИЙ]`;
- every main-menu and submenu choice shows a contextual explanation for the
  currently highlighted item;
- Selective/Transit, VPN OFF, LAN reconfigure, reboot and poweroff descriptions
  explain the operational consequence before the action is taken;
- `VPN-mаршрутизация -> Конфигурация AmneziaWG -> Вставить конфигурацию текстом`
  opens a multiline editor suitable for terminal clipboard paste;
- cancelling the editor leaves the live profile unchanged;
- an empty or invalid pasted profile is rejected before any live service change;
- CRLF text pasted from Windows is accepted after line-ending normalization;
- a valid profile passes `config check` before the final install confirmation;
- the temporary pasted file is mode 0600 under `/run/awg-pbr` and is removed
  after completion/cancellation;
- successful replacement still uses the existing transactional
  handshake/transport validation and previous-profile rollback path.

CI includes `tests/test-menu.py` to enforce the secure paste path, require
`--item-help` on every dialog menu, and require the visible operating-mode
indicator. Hardware validation on a real SSH terminal is PASS for the RC5 menu
rendering/context-help/profile-paste workflow and for the post-RC6 persistent
SELECTIVE/TRANSIT indicator. The mode badge was visually accepted on the real
terminal before freezing RC7.

## 11. v1.1.0 -> v1.2.0 upgrade

On a validated v1.1.0 machine, preserve copies of:

```bash
sudo cp -a /etc/awg-pbr /tmp/awg-pbr-v1.1
sudo cp -a /etc/amnezia/amneziawg /tmp/amnezia-v1.1
```

Run the v1.2 branch installer with the explicit ref. The upgrade prompt defaults
to Transit. The installer must preserve all Selective state.

If Transit preflight cannot succeed, v1.2 must remain/restored in Selective
rather than leave a partial Transit datapath.

## 12. Hardware run: 2026-09-30

Hardware used:

```text
Raspberry Pi 4 Model B Rev 1.2
Debian GNU/Linux 13 (trixie), arm64
MikroTik hAP ax2
RouterOS 7.24.2
LAN 192.168.112.0/24
Pi 192.168.112.34
Router 192.168.112.1
```

The Pi code under test was RC3 SHA
`35b1e723bc497f3faef4839318d7db25e4d49e2e`. RC4 keeps the same Pi code and
adds the validated RouterOS procedure/checklist.

Results:

- PASS — v1.1.0 -> v1.2.0 remote upgrade with explicit Selective staging.
- PASS — RC3 post-upgrade diagnostics; no `diag_mode` unbound-variable
  regression.
- PASS — Selective reboot persistence.
- PASS — Selective FAIL-OPEN when the policy rule is removed by diagnostics.
- PASS — Transit preflight, including DIRECT AWG endpoint route.
- PASS — Selective -> Transit transactional switch.
- PASS — Transit guard SAFE, MikroTik source-MAC restriction, no Transit DNS
  redirect, marked route via `awg0`, normal Pi route DIRECT.
- PASS — actual MikroTik -> Pi -> AWG -> Internet datapath.
- PASS — actual selected-client traffic through Pi/AWG with SSTP policy route
  unavailable.
- PASS — Transit AWG failure produces health down, policy FAIL-CLOSED, no policy
  rule/table, and 100% loss for selected test traffic rather than WAN leakage.
- PASS — AWG recovery restores ACTIVE/READY Transit state.
- PASS — MikroTik two-probe health logic: one DOWN does not fail over; both DOWN
  withdraw the SSTP policy default while the SSTP interface remains RUNNING;
  both UP restore the primary route.
- PASS — automatic MikroTik failover/failback route selection between SSTP and
  Pi/AWG by distance.
- PASS — Transit Raspberry Pi reboot persistence; zero failed systemd units
  after reboot.
- PASS — AWG endpoint remains DIRECT via the LAN router after Transit reboot.
- PASS — Transit -> Selective -> Transit round-trip; endpoint remains DIRECT in
  both modes and Transit returns SAFE/ACTIVE/READY.
- PASS — saved RouterOS binary backup and text export before and after the
  failover changes.

Still pending or intentionally deferred:

- PASS — visual hardware smoke test for the persistent TUI
  SELECTIVE/TRANSIT indicator; accepted on the real SSH terminal before RC7.
- PASS — RC5 TUI rendering/profile-paste negative-path smoke test on the real SSH terminal.
- FOUND/FIXED IN RC6 — RC5 clean install reached healthy Transit
  SAFE/ACTIVE/READY, then final `awg-route reload` hit a concurrent
  `awg-pbr-setup` file-replacement race (`install: ... File exists`).
  Direct overwrite of the same target with GNU install 9.7 succeeds when run
  alone, confirming the filesystem/target itself is normal. RC6 serializes
  setup and has a concurrent regression test.
- PASS — RC6 clean v1.2.0 install on clean Debian 13 ARM64 completed through
  final reload/diagnostics in default Transit. Post-install state: version
  1.2.0, Transit SAFE/ACTIVE/READY, all core services/timer active, zero failed
  systemd units, table 100 default via awg0, and the AWG endpoint remained
  DIRECT via the LAN router on eth0.
- PASS — non-empty v1.1 -> v1.2 upgrade preservation and RC8 Selective
  regression completed on real Raspberry Pi 4 hardware. The upgrade preserved
  env, manual VPN/DIRECT lists, client list, requested VPN state, AWG profile and
  OpenCCK metadata/cache byte-for-byte (8/8 SHA256 checks). Manual VPN
  `wikipedia.org` routed through `awg0`; manual DIRECT `youtube.com`
  correctly kept `accounts.youtube.com` DIRECT after the RC8 fix; independent
  OpenCCK `googlevideo.com` remained routed through `awg0`. The same saved
  state survived Selective -> Transit -> Selective unchanged; Transit reported
  SAFE/ACTIVE/READY, Selective classification was inactive in Transit, the
  restored Selective datapath passed all three routing checks, and
  `systemctl --failed` reported zero failed units.
- DEFERRED — RouterOS reboot persistence of the Netwatch automation while the
  test operator is remote and depends on the router for connectivity.

## 13. Release gate

Before tagging v1.2.0:

- [x] CI green at the RC3 Pi-code SHA used for hardware validation.
- [x] v1.1.0 -> v1.2.0 upgrade path PASS.
- [x] Selective reboot + FAIL-OPEN regression PASS.
- [x] Transit manual datapath PASS.
- [x] SSTP selected-client failover/failback PASS.
- [x] SSTP two-probe health logic PASS with the interface remaining RUNNING.
- [x] AWG failure while on backup proves FAIL-CLOSED.
- [x] Selective -> Transit -> Selective/Transit round-trip PASS.
- [x] Raspberry Pi reboot in Selective and Transit PASS.
- [x] diagnostics/status redact private, preshared and header-protection keys.
- [x] RC5 TUI contextual-help and invalid pasted-profile rejection PASS on real SSH.
- [x] RC6 clean fresh install completes final reload/diagnostics and defaults
  to Transit on clean media.
- [x] RC7 persistent TUI operating-mode indicator accepted on real SSH.
- [x] non-empty Selective state preservation/regression on real hardware:
  8/8 byte-for-byte upgrade checks PASS; RC8 DIRECT-parent precedence PASS; final
  Selective -> Transit -> Selective round-trip PASS with zero failed units.
- [x] CI green at the exact final release SHA after all release documentation is
  frozen.

RouterOS reboot persistence of the optional Netwatch automation is desirable but
is not a Pi release blocker when the configuration has been saved and backed up;
perform it before production rollout when a safe local recovery path is
available.
