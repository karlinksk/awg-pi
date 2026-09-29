# AWG Pi Gateway

Raspberry Pi 4 gateway for selective AmneziaWG policy routing.

The normal Internet route stays **DIRECT** through the home router. Only selected
domains or address lists are marked for AmneziaWG. If the VPN health check fails,
the policy rule is removed and traffic falls back to the normal Internet route
(**FAIL-OPEN**).

## Stable release

Current stable release: **v1.0.1**

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/v1.0.1/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

## v1.1.0 hardware candidate

The stable `main`/release remains **v1.0.1** until the v1.1.0 hardware release
gate is complete.

The frozen RC2 snapshot is retained unchanged for traceability:

```text
branch: rc/v1.1.0-rc2
SHA:    43b5f01a97178ca6a5bfeb73e3839f0b2ca125d2
```

RC2 exposed a real Linux terminal confirmation bug in interactive
`network reconfigure` / `config replace`. PR #4 fixed the terminal handling
after RC2. The routing/profile transaction hardware tests were completed on:

```text
187bb100701a8a17655cfe0fa1ca62a97db66408
```

PR #5 then fixed the TUI-only cancellation status message. The current
post-test executable code snapshot is:

```text
2606a8560eaca05862400ae64e718cc6ded0a574
```

Install that exact snapshot for the final cancellation-UX hardware check:

```bash
TEST_SHA=2606a8560eaca05862400ae64e718cc6ded0a574
curl -fsSL "https://raw.githubusercontent.com/karlinksk/awg-pi/$TEST_SHA/install.sh" -o /tmp/awg-hw-test-install.sh
sudo env AWG_PI_REF="$TEST_SHA" AWG_PI_UPGRADE_AUTO=1 bash /tmp/awg-hw-test-install.sh
```

The existing Raspberry Pi has confirmed the post-RC2 interactive confirmation
path, an in-subnet Pi address migration, and the full second-server profile
transaction (replace, real traffic, manual rollback and automatic rollback).
A full migration to a different LAN subnet/router address is intentionally
deferred and is not part of the remaining v1.1.0 release gate. Later
documentation-only commits do not redefine the hardware-tested executable
snapshots.

v1.1.0 includes:

- SSH TUI control panel (`awg-menu`)
- bulk VPN/DIRECT domain import and export
- OpenCCK sources with last-known-good cache and automatic timer refresh
- domain, IPv4 and IPv4 CIDR source modes
- source/routing diagnostics and FAIL-OPEN health monitoring
- separate AWG Pi Gateway and AmneziaWG core updates
- transactional LAN reconfiguration with backup/rollback
- transactional native AmneziaWG profile check/replace/rollback
- AWG v3.1 native-profile compatibility and secret redaction
- CI regression tests for the hardware-discovered RC1/RC2 issues
- post-RC2 real Linux `/dev/tty` confirmation fix
- distinct TUI status for a user-cancelled maintenance operation

## Main v1.1.0 commands

```bash
sudo awg-route status
sudo awg-route vpn add example.com
sudo awg-route vpn import domains.txt
sudo awg-route direct add example.com

sudo awg-route source add opencck youtube
sudo awg-route source list
sudo awg-route source update

sudo awg-route diagnostics
sudo awg-route network reconfigure
sudo awg-route config check /etc/amnezia/amneziawg/awg0.conf
sudo awg-route config replace /path/to/new.conf
sudo awg-route config rollback
sudo awg-menu

sudo awg-update status
sudo awg-update gateway
sudo awg-update core
```

Interactive SSH logins open the TUI automatically after v1.1.0 installation.
Create `~/.no-awg-menu` to disable automatic TUI launch for that account while
keeping normal SSH access.

## Maintenance and upgrade

The RC2 line fixed CIDR validation under `set -u`, decimal ping marks
(including old hexadecimal values in saved env), installer version isolation
from Debian `/etc/os-release`, and skips underscore DNS service names in
OpenCCK domain sources. Malformed hostnames still reject the update and preserve
its cache.

`network reconfigure` discovers the current IPv4 LAN/default router, displays
old/new values, asks for confirmation, and backs up env, dnsmasq, nftables and
client settings before applying them. It updates gateway configuration for an
**already changed network**; it does not change Pi addresses, DHCP reservations,
router settings or client gateway/DNS. Ambiguous routes/addresses are rejected.
`status` warns about a mismatch. Clients outside the new subnet are retained
after explicit acknowledgement; add their new addresses before removing old
ones. Empty allow-list means all gateway clients. For unattended use:
`awg-route network reconfigure --yes --keep-clients`.

`config replace FILE` and `config rollback` also appear in the VPN menu.
Native gateway profiles need one peer, an IPv4 interface address and IPv4
default AllowedIPs (`0.0.0.0/0`). Additional IPv6 Address/AllowedIPs entries
are preserved; Table=off does not enable IPv6 policy routing. AWG v3.1
HeaderProtectionKey, timing ranges, padding and security options are supported;
legacy H1-H4 are not mandatory. DNS is stripped, Table is forced off, and
executable hooks/SaveConfig are rejected. Preflight uses `awg-quick strip` and
the installed AWG core on a temporary userspace interface in an isolated
network namespace (`unshare`, `amneziawg-go`, `awg`). Unsupported AWG
parameters fail before live changes. The kernel-only peer option
`AdvancedSecurity` is rejected by this userspace gateway, matching the
upstream tools' userspace transport restriction.

Keys are never printed. During switching the health monitor is stopped and
policy is DIRECT. A fresh handshake and marked, interface-bound transport probe
must pass before health monitoring resumes. Failure restores the old profile;
failure of that tunnel leaves DIRECT with health stopped. Restore connectivity,
then start `awg-pbr-health.service` manually. Manual rollback validates the
saved `.conf.previous` through the same transaction.

Use `sudo awg-route config check /etc/amnezia/amneziawg/awg0.conf` to validate
the current native profile with the installed core without switching the live
tunnel or restarting services. Status, diagnostics reports and installer AWG
failure output redact private, preshared and header-protection keys before
printing or saving them. Reports from older builds are not rewritten.

Backups are under `/var/backups/awg-gateway/{network,config}-*`, directories
mode 700/files 600. Operations handle command failures and catchable signals;
power loss/SIGKILL require recovery from the backup. They preserve VPN/DIRECT
lists, OpenCCK sources, requested VPN on/off state and DNS upstream settings.
Maintenance is exclusive; concurrent CLI/OpenCCK changes are refused.

For the existing Pi upgrade procedure and hardware validation, see
[TESTING-v1.1.0.md](docs/TESTING-v1.1.0.md#13-rc2-existing-pi-upgrade-first).


## Future v1.2.0

After the v1.1.0 release gate is complete, the planned next feature is an
independent **MikroTik Transit / Backup VPN** operating mode. MikroTik will keep
traffic classification and SSTP failover responsibility; the Pi will act as an
AmneziaWG transit gateway when MikroTik selects it as the backup next hop.

The existing Selective Gateway mode will remain available and mode selection
will be persistent and transactional. For the planned v1.1.0 -> v1.2.0 upgrade,
the default operating mode is **MikroTik Transit / Backup VPN**; the preserved
Selective Gateway configuration can be restored at any time from
`System -> Operating mode`.

Design note: [ROADMAP-v1.2.0-TRANSIT.md](docs/ROADMAP-v1.2.0-TRANSIT.md)
