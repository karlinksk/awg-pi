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

Current hardware release candidate:

```text
rc/v1.2.0-rc5
```

RC5 keeps the hardware-tested Transit datapath from RC3/RC4 and adds the final
TUI usability work: native AmneziaWG profiles can be pasted directly into the
menu through a root-only temporary file in `/run`, every menu item has contextual
help, and higher-risk routing/network/power actions have expanded warnings.

For hardware testing, use the frozen RC ref explicitly so the installer does
not expect an unreleased v1.2.0 tag:

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/rc/v1.2.0-rc5/install.sh -o /tmp/install-v1.2-rc5.sh
sudo AWG_PI_REF=rc/v1.2.0-rc5 bash /tmp/install-v1.2-rc5.sh
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

CI includes `tests/test-menu.py` to enforce the secure paste path and require
`--item-help` on every dialog menu. Hardware validation is still required for
the actual terminal rendering and clipboard interaction.

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

- PENDING — RC5 TUI rendering/profile-paste smoke test on the real SSH terminal.
- PENDING — clean v1.2.0 fresh install on clean media with default Transit;
  requires physical access to the test microSD/Raspberry Pi.
- PENDING — full Selective regression with non-empty manual/OpenCCK/client lists
  preserved across the v1.1 -> v1.2 upgrade; the hardware run used empty lists.
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
- [ ] RC5 TUI contextual-help and pasted-profile workflow PASS on real SSH.
- [ ] clean fresh install defaults to Transit on clean media.
- [ ] non-empty Selective state preservation/regression on real hardware.
- [ ] CI green at the exact final release SHA after all release documentation is
  frozen.

RouterOS reboot persistence of the optional Netwatch automation is desirable but
is not a Pi release blocker when the configuration has been saved and backed up;
perform it before production rollout when a safe local recovery path is
available.
