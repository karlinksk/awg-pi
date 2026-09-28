# v1.1.0 Raspberry Pi RC validation

This checklist is intentionally run on real Raspberry Pi 4 hardware before
merging `develop/v1.1.0` into `main`.

## 1. Clean installation

- Raspberry Pi 4 Model B, Raspberry Pi OS Lite 64-bit, Ethernet only.
- Pi IPv4 is reserved on the Archer C64 before installation.
- IPv6 default route is disabled for this v1 architecture.
- Use a dedicated AmneziaWG native `.conf` profile for the Pi.
- Install from `develop/v1.1.0` with `AWG_PI_REF=develop/v1.1.0`.
- Confirm every critical installer check passes.
- Confirm `/etc/awg-pbr/version` is written only after final diagnostics.

Expected after install:

```bash
sudo awg-route status
sudo systemctl --failed
sudo systemctl status awg-pbr-setup.service --no-pager
sudo systemctl status awg-pbr-health.service --no-pager
sudo systemctl status awg-opencck-update.timer --no-pager
sudo systemctl status dnsmasq.service --no-pager
sudo systemctl status awg-quick@awg0.service --no-pager
```

## 2. DIRECT baseline

Configure one test client with:

- Gateway = Raspberry Pi IPv4
- DNS = Raspberry Pi IPv4
- IPv6 disabled for the test

With empty VPN/OpenCCK lists, verify ordinary browsing works and public IPv4 is
the ISP address.

## 3. Manual domain PBR

```bash
sudo awg-route vpn add <test-domain>
sudo awg-route test <test-domain>
```

Verify the domain is learned into `vpn4`, receives mark `0x100`, and routes
through `awg0`. Verify an unrelated site remains DIRECT.

Then:

```bash
sudo awg-route direct add <exception-domain>
sudo awg-route test <exception-domain>
```

Verify DIRECT overrides VPN marking for matching resolved addresses.

## 4. Bulk import/export

Test additive import, replacement import, comments, blank lines, duplicates,
URLs, wildcard prefixes and invalid input.

```bash
sudo awg-route vpn import domains.txt
sudo awg-route vpn export /tmp/vpn-export.txt
sudo awg-route vpn import --replace replacement.txt
```

An invalid file must be rejected without changing the active list.

## 5. OpenCCK domains

```bash
sudo awg-route source add opencck youtube
sudo awg-route source list
sudo awg-route source show opencck youtube
sudo awg-route source update youtube
```

Verify downloaded domains are stored separately from manual rules and DNS
queries populate `vpn4`.

Disconnect OpenCCK access temporarily and confirm:

- existing cached source remains usable;
- update reports an error;
- Internet and AWG policy routing remain operational.

## 6. OpenCCK IPv4/CIDR

Add a small test IP/CIDR source where practical. Confirm overlapping networks
are collapsed before loading the nftables interval set and that `source4`
loads without duplicate/overlap errors.

## 7. FAIL-OPEN

With a VPN-routed test domain working:

```bash
sudo systemctl stop awg-quick@awg0.service
```

Within the health interval, confirm policy rule priority 100 disappears and the
client continues to reach the Internet DIRECT.

Restore:

```bash
sudo systemctl start awg-quick@awg0.service
```

Confirm the health state returns to `up` and policy rule is automatically
restored.

Also test:

```bash
sudo awg-route vpn off
sudo awg-route vpn on
```

## 8. SSH TUI

Reconnect with normal interactive SSH. Confirm `awg-menu` opens automatically.

Test every main menu section. In particular:

- exiting to Shell returns to the normal unprivileged user;
- terminating the menu terminates the SSH session;
- `scp` and noninteractive SSH commands do not launch the menu;
- creating `~/.no-awg-menu` bypasses auto-launch;
- deleting it restores auto-launch.

## 9. Reboot and persistence

Reboot the Pi. Confirm:

- normal DIRECT Internet is available;
- dnsmasq is active;
- awg0 starts;
- health monitor starts;
- policy returns only after successful tunnel health;
- OpenCCK timer is active;
- lists, sources and manual VPN on/off state survive reboot.

## 10. Upgrade path

On a separately backed-up test installation of v1.0.1, run the v1.1.0
development installer with `AWG_PI_REF=develop/v1.1.0`.

Confirm it preserves:

- AmneziaWG config and keys;
- Pi/router/LAN settings;
- VPN and DIRECT domain lists;
- client allow-list;
- requested VPN policy state;
- existing watchdog choice.

Gateway upgrade must not update AmneziaWG core automatically.

## 11. Diagnostics and logs

```bash
sudo awg-route diagnostics
sudo awg-route logs
```

Verify reports include routing, services, OpenCCK and FAIL-OPEN state, while
excluding private keys, preshared keys and credentials.

## 12. Release gate

Do not merge/release v1.1.0 until all of the following are true:

- branch CI is green;
- clean hardware install passes;
- v1.0.1 -> v1.1.0 upgrade passes;
- DIRECT, VPN routing and DIRECT exceptions pass;
- OpenCCK success and failure-cache cases pass;
- FAIL-OPEN passes;
- SSH/TUI escape and noninteractive SSH pass;
- reboot/persistence passes;
- no secrets appear in diagnostics.
