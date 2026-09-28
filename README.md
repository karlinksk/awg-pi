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

## v1.1.0 development

The `develop/v1.1.0` branch adds:

- SSH TUI control panel (`awg-menu`)
- bulk VPN/DIRECT domain import and export
- OpenCCK sources with last-known-good cache
- automatic OpenCCK refresh via systemd timer
- domain, IPv4 and IPv4 CIDR source modes
- source/routing diagnostics
- separate AWG Pi Gateway and AmneziaWG core updates
- transaction-oriented gateway backup/rollback
- CI checks for Bash syntax, ShellCheck, OpenCCK validation and nftables syntax

**Do not use the development branch on the production Raspberry Pi unless you
are intentionally performing an RC test.** The stable `main`/release remains
v1.0.1 until v1.1.0 has passed Raspberry Pi hardware tests.

For an explicit development-branch test, helper downloads must be pinned to the
same branch:

```bash
curl -fsSL https://raw.githubusercontent.com/karlinksk/awg-pi/develop/v1.1.0/install.sh -o /tmp/install.sh
sudo env AWG_PI_REF=develop/v1.1.0 bash /tmp/install.sh
```

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
sudo awg-route config replace /home/pi/new.conf
sudo awg-route config rollback
sudo awg-menu

sudo awg-update status
sudo awg-update gateway
sudo awg-update core
```

Interactive SSH logins open the TUI automatically after v1.1.0 installation.
Create `~/.no-awg-menu` to disable automatic TUI launch for that account while
keeping normal SSH access.

## RC2 maintenance and upgrade

RC2 fixes CIDR validation under `set -u`, decimal ping marks (including old
hexadecimal values in saved env), installer version isolation from Debian
`/etc/os-release`, and skips underscore DNS service names in OpenCCK domain
sources. Malformed hostnames still reject the update and preserve its cache.

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
Only native IPv4 gateway profiles with one peer and `AllowedIPs=0.0.0.0/0` are
accepted. DNS is stripped, Table is forced off, and executable hooks/SaveConfig
are rejected. Preflight uses `awg-quick strip` and the installed AWG core on a
temporary userspace interface in an isolated network namespace (`unshare`,
`amneziawg-go`, `awg`). Unsupported AWG parameters fail before live changes.
Keys are never printed. During switching the health monitor is stopped and
policy is DIRECT. A fresh handshake and marked, interface-bound transport
probe must pass before health monitoring resumes. Failure restores the old
profile; failure of that tunnel leaves DIRECT with health stopped. Restore
connectivity, then start `awg-pbr-health.service` manually. Manual rollback
validates the saved `.conf.previous` through the same transaction.

Backups are under `/var/backups/awg-gateway/{network,config}-*`, directories
mode 700/files 600. Operations handle command failures and catchable signals;
power loss/SIGKILL require recovery from the backup. They preserve VPN/DIRECT
lists, OpenCCK sources, requested VPN on/off state and DNS upstream settings.
Maintenance is exclusive; concurrent CLI/OpenCCK changes are refused.

For the existing Pi upgrade procedure and hardware validation, see
[TESTING-v1.1.0.md](docs/TESTING-v1.1.0.md#13-rc2-existing-pi-upgrade-first).
