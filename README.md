# AWG Pi Gateway

Raspberry Pi 4 gateway for selective AmneziaWG policy routing.

The normal Internet route stays **DIRECT** through the home router. Only selected
domains or address lists are marked for AmneziaWG. If the VPN health check fails,
the policy rule is removed and traffic falls back to the normal Internet route
(**FAIL-OPEN**).

## Stable release

Current stable release: **v1.1.0**

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/v1.1.0/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

## v1.1.0 release validation

v1.1.0 completed the hardware release gate on Raspberry Pi 4 using a clean
Debian 13 (trixie) ARM64 microSD install and a reboot/persistence check.

The final frozen release candidate was:

```text
branch: rc/v1.1.0-rc4
SHA:    85fbd6a93361635051a2a5569cb8c1bec697ee69
```

The clean-install test used the unmodified RC4 installer, confirmed the default
upstream DNS pair `9.9.9.9,149.112.112.112`, verified `9.9.9.9` as the
first transport-health probe with `1.1.1.1` retained as fallback, and passed
post-reboot service, health, policy-routing, DNS, and watchdog checks.

Earlier RC snapshots remain in the repository for traceability. Detailed
hardware evidence is recorded in `docs/TESTING-v1.1.0.md`.
v1.1.0 includes:

- SSH TUI control panel (`awg-menu`)
- bulk VPN/DIRECT domain import and export
- OpenCCK sources with last-known-good cache and automatic timer refresh
- domain, IPv4 and IPv4 CIDR source modes
- source/routing diagnostics and FAIL-OPEN health monitoring
- separate AWG Pi Gateway and AmneziaWG core updates
- transactional LAN reconfiguration with backup/rollback
- transactional native AmneziaWG profile check/replace/rollback
- transactional upstream DNS change from CLI/TUI with validation and rollback
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
sudo awg-route dns status
sudo awg-route dns set 9.9.9.9,149.112.112.112
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

`dns status` displays the saved upstream list and the active `dnsmasq`
`server=` entries. `dns set IPv4[,IPv4...]` validates one to four IPv4
servers, checks that at least one answers directly, asks for confirmation,
updates both `UPSTREAM_DNS` and the managed `dnsmasq` config, validates
`dnsmasq`, restarts it and requires a successful query through the Pi. Failure
restores both files and attempts to restart the previous DNS configuration. The
same operation is available in `System -> DNS upstream` in the TUI.

Backups are under `/var/backups/awg-gateway/{network,config,dns}-*`, directories
mode 700/files 600. Operations handle command failures and catchable signals;
power loss/SIGKILL require recovery from the backup. They preserve VPN/DIRECT
lists, OpenCCK sources, requested VPN on/off state and DNS upstream settings.
Maintenance is exclusive; concurrent CLI/OpenCCK changes are refused.

For the existing Pi upgrade procedure and hardware validation, see
[TESTING-v1.1.0.md](docs/TESTING-v1.1.0.md#13-rc2-existing-pi-upgrade-first).


## v1.2.0 development

v1.2.0 is being developed on `develop/v1.2.0` with an independent
**MikroTik Transit / Backup VPN** mode in addition to the v1.1.0 Selective
Gateway.

The current implementation branch adds:

- persistent `selective` / `transit` operating mode;
- transactional mode switching with rollback;
- Transit preflight that verifies a healthy AWG path and keeps the AWG endpoint
  DIRECT through the normal LAN router;
- MikroTik-MAC-restricted Transit forwarding and NAT to `awg0`;
- Selective FAIL-OPEN and Transit FAIL-CLOSED health behavior;
- a Transit lockdown ruleset that is installed before router/MAC-dependent boot setup;
- mode-aware boot/reload setup;
- CLI and SSH-TUI mode selection;
- preservation of VPN/DIRECT/OpenCCK/client state while Transit classification
  is active; OpenCCK continues refreshing its persistent cache without
  reloading the live Transit datapath.

Core mode commands are:

```bash
sudo awg-route mode status
sudo awg-route mode selective
sudo awg-route mode transit
```

A fresh v1.2 install defaults to Selective. A v1.1.0 -> v1.2.0 upgrade offers
Transit as the default post-upgrade mode; if Transit preflight/activation fails,
the runtime is restored to Selective instead of leaving a partial Transit state.

v1.2.0 is **not yet the stable release**. Hardware validation must pass before
the stable tag is moved from v1.1.0.

Design: [ROADMAP-v1.2.0-TRANSIT.md](docs/ROADMAP-v1.2.0-TRANSIT.md)

Hardware release gate: [TESTING-v1.2.0.md](docs/TESTING-v1.2.0.md)

RouterOS template: [MIKROTIK-TRANSIT-v1.2.0.md](docs/MIKROTIK-TRANSIT-v1.2.0.md)
