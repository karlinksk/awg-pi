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
sudo awg-menu

sudo awg-update status
sudo awg-update gateway
sudo awg-update core
```

Interactive SSH logins open the TUI automatically after v1.1.0 installation.
Create `~/.no-awg-menu` to disable automatic TUI launch for that account while
keeping normal SSH access.
