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

First hardware release candidate:

```text
rc/v1.2.0-rc1
```

For hardware testing, use the frozen RC ref explicitly so the installer does
not expect an unreleased v1.2.0 tag:

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/rc/v1.2.0-rc1/install.sh -o /tmp/install-v1.2.sh
sudo AWG_PI_REF=rc/v1.2.0-rc1 bash /tmp/install-v1.2.sh
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

Expected on a fresh install: `Mode ID: selective`.

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

Capture counters on MikroTik and:

```bash
sudo nft list table inet awg_pbr
sudo awg show awg0
```

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

## 9. Reboot persistence

Test one reboot in each mode.

After each reboot verify mode, services, nftables table, policy state, DIRECT
AWG endpoint path and connectivity.

## 10. v1.1.0 -> v1.2.0 upgrade

On a validated v1.1.0 machine, preserve copies of:

```bash
sudo cp -a /etc/awg-pbr /tmp/awg-pbr-v1.1
sudo cp -a /etc/amnezia/amneziawg /tmp/amnezia-v1.1
```

Run the v1.2 branch installer with the explicit ref. The upgrade prompt defaults
to Transit. The installer must preserve all Selective state.

If Transit preflight cannot succeed, v1.2 must remain/restored in Selective
rather than leave a partial Transit datapath.

## 11. Release gate

Before tagging v1.2.0:

- CI green at the exact release SHA;
- Selective regression PASS;
- Transit manual datapath PASS;
- SSTP healthy/failure/recovery PASS;
- AWG failure while on backup proves FAIL-CLOSED;
- Selective -> Transit -> Selective PASS;
- reboot in both modes PASS;
- v1.1.0 -> v1.2.0 upgrade PASS;
- diagnostics contain no private/preshared/header-protection keys.
