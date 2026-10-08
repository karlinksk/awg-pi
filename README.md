# AWG Pi Gateway

Raspberry Pi 4 AmneziaWG gateway with **Selective Gateway** and
**MikroTik Transit / Backup VPN** operating modes.

In Selective mode, the normal Internet route stays **DIRECT** through the home
router and only selected domains/address lists are marked for AmneziaWG. If VPN
health fails, Selective removes the policy rule and falls back to the normal
Internet route (**FAIL-OPEN**).

In Transit mode, MikroTik selects traffic for the Pi and the Pi forwards that
traffic through AmneziaWG. Transit keeps the Pi management path and AWG endpoint
DIRECT, while selected transit traffic is **FAIL-CLOSED** if AWG becomes
unavailable.

## Stable release

Current stable release: **v1.2.0**

## v1.3.0 development track

v1.3.0 is the current multi-transport development line. It keeps the v1.2
Selective/Transit semantics and adds a transport abstraction with AmneziaWG and
Mihomo backends, transactional AWG <-> Mihomo switching, provider-cache
bootstrap/rollback, secure first-run onboarding, ordered exact-node failover,
conservative availability-only transport AUTO, and a provider adapter layer for
native Mihomo/Clash YAML, plain VLESS URI subscriptions and Base64 VLESS
subscriptions.

The fresh-install wizard can choose AWG or Mihomo as the first transport. When
Mihomo is chosen it interactively selects the first live node and may configure
an explicit one-way fallback chain (for example Finland -> Estonia -> Latvia ->
Sweden). Node failover never infers countries or wraps back to an earlier node.
Transport FIXED/AUTO policy is independent from the Mihomo node policy.

The SSH TUI also includes a system dashboard (clock/timezone, uptime, CPU
temperature/load, RAM and disk), timezone management, unified VPN
destination/OpenCCK entry, and low-write today/month transport traffic
accounting for awg0 + mihomo0. Traffic samples stay in RAM and persistent state
is checkpointed only periodically. On first activation the counter establishes
a baseline instead of attributing pre-existing interface bytes to the current
day; boot identity and interface identity are tracked so restarts/recreates do
not silently corrupt the deltas.

The v1.2.0 stable tag remains the updater target until the v1.3 hardware gate is
complete. Do not treat develop/v1.3.0 as a stable installation source without an
explicit ref and rollback plan.

Release/hardware gate: [TESTING-v1.3.0.md](docs/TESTING-v1.3.0.md)

## Install / upgrade

Use the stable tag for both a fresh install and an upgrade from an existing
AWG Pi Gateway installation:

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/v1.2.0/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

A fresh v1.2.0 install stages Selective safely while AWG is validated, then
defaults to **MikroTik Transit / Backup VPN** after a successful Transit
preflight.

When v1.1.0 is already installed, the same installer detects the existing
gateway, preserves the AWG profile, VPN/DIRECT lists, clients, requested VPN
state and OpenCCK state, and offers the v1.2.0 operating-mode choice. If Transit
preflight or activation fails, the installer keeps/restores Selective instead of
leaving a partial Transit state.

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

## Main commands

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

Interactive SSH logins open the TUI automatically after installation.
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

For full microSD/SSD imaging and bare-metal recovery, see
[BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md).

## v1.2.0

v1.2.0 adds an independent **MikroTik Transit / Backup VPN** mode alongside
the existing Selective Gateway.

v1.2.0 includes:

- persistent `selective` / `transit` operating mode;
- transactional mode switching with rollback;
- Transit preflight that verifies a healthy AWG path and keeps the AWG endpoint
  DIRECT through the normal LAN router;
- MikroTik-MAC-restricted Transit forwarding and NAT to `awg0`;
- Selective FAIL-OPEN and Transit FAIL-CLOSED health behavior;
- a Transit lockdown ruleset that is installed before router/MAC-dependent boot setup;
- mode-aware boot/reload setup;
- CLI and SSH-TUI mode selection;
- persistent TUI mode identification: the dialog backtitle, main-menu title and
  System/Operating mode screens visibly show SELECTIVE or TRANSIT, and the
  active choice is marked as current;
- context help for every existing and new TUI menu item, with expanded warnings
  before routing/network/power actions;
- AmneziaWG profile replacement from the TUI either by file path or by pasting
  the native .conf text into a root-only temporary file in /run; pasted profiles
  are validated before transactional replacement and automatic rollback remains
  available;
- preservation of VPN/DIRECT/OpenCCK/client state while Transit classification
  is active; OpenCCK continues refreshing its persistent cache without
  reloading the live Transit datapath;
- hierarchical manual DIRECT precedence in Selective mode: VPN/OpenCCK domain
  directives already covered by a manual DIRECT parent are omitted from the
  generated dnsmasq nftset rules, preventing a more-specific source entry from
  overriding the DIRECT exception.

Core mode commands are:

```bash
sudo awg-route mode status
sudo awg-route mode selective
sudo awg-route mode transit
```

A fresh v1.2.0 install defaults to **Transit**. During installation the Pi stages
the safe Selective ruleset while AWG is validated, then transactionally switches
to Transit after preflight succeeds. A v1.1.0 -> v1.2.0 upgrade also offers
Transit as the default post-upgrade mode. If Transit preflight/activation fails,
the runtime is restored to Selective instead of leaving a partial Transit state.

v1.2.0 is the current stable release. The final frozen release candidate was
`rc/v1.2.0-rc10`; hardware and CI evidence is recorded in the testing guide.

Design: [ROADMAP-v1.2.0-TRANSIT.md](docs/ROADMAP-v1.2.0-TRANSIT.md)

Hardware release gate: [TESTING-v1.2.0.md](docs/TESTING-v1.2.0.md)

RouterOS template: [MIKROTIK-TRANSIT-v1.2.0.md](docs/MIKROTIK-TRANSIT-v1.2.0.md)
