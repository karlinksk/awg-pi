# v1.1.0 Raspberry Pi RC validation

This checklist is intentionally run on real Raspberry Pi 4 hardware before
merging `develop/v1.1.0` into `main`.


## Current RC2 hardware status

Frozen candidate under test:

```text
rc/v1.1.0-rc2
43b5f01a97178ca6a5bfeb73e3839f0b2ca125d2
```

Validated on the existing Raspberry Pi 4 test gateway:

- upgrade of the existing RC test installation to the RC2 code while preserving
  AWG config, LAN settings, client allow-list and OpenCCK state;
- DIRECT Internet and manual domain PBR on the LG client;
- real OpenCCK `youtube` routing with video traffic observed on `awg0`;
- OpenCCK last-known-good cache behavior;
- FAIL-OPEN on stopping `awg0`, followed by automatic policy recovery;
- reboot/persistence of services, OpenCCK source and client state;
- interactive SSH TUI plus noninteractive SSH and SCP bypass;
- diagnostics including FAIL-OPEN simulation and secret redaction;
- additive bulk import/export with deduplication;
- invalid bulk import rejected transactionally without changing the live list;
- AWG v3.1 current-profile validation and regression coverage in CI.

Still required before the stable v1.1.0 release:

- controlled real-LAN `network reconfigure` test, including rollback behavior;
- real second-server `config replace`, manual rollback and automatic rollback
  from an unreachable/failed profile;
- complete remaining release-gate checklist items that have not yet been
  exercised on the frozen RC2 snapshot, including `--replace` bulk import where
  applicable and final release audit.

Do not move the frozen RC2 branch to include later documentation-only commits.

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

## 13. RC2: existing Pi upgrade first

CI does not replace testing the real Pi and LG. Do not reset or clean-install
the current test Pi. Preserve Pi `192.168.112.33`, LG `192.168.112.28`, AWG
profile, client allow-list, OpenCCK youtube, VPN/DIRECT lists, upstream DNS,
requested policy state and watchdog settings.

Resolve RC2 once to a commit and pin both the installer and helper downloads
to that same commit. Run in an interactive SSH shell (exit the TUI first):

```bash
set -e
RC2_SHA=$(git ls-remote https://github.com/karlinksk/awg-pi.git refs/heads/rc/v1.1.0-rc2 | awk '{print $1}')
test "${#RC2_SHA}" -eq 40
backup="/var/backups/awg-gateway/pre-rc2-$(date +%Y%m%d-%H%M%S).tgz"
sudo install -d -m 700 /var/backups/awg-gateway
sudo tar -C / -czf "$backup" etc/awg-pbr etc/amnezia/amneziawg etc/dnsmasq.d etc/nftables.d etc/sysctl.d etc/systemd/system usr/local/lib/awg-pi usr/local/sbin
sudo chmod 600 "$backup"
sudo tar -tzf "$backup" >/dev/null
curl -fLsS "https://raw.githubusercontent.com/karlinksk/awg-pi/$RC2_SHA/install.sh" -o /tmp/awg-rc2-install.sh
bash -n /tmp/awg-rc2-install.sh
sudo env AWG_PI_REF="$RC2_SHA" AWG_PI_UPGRADE_AUTO=1 bash /tmp/awg-rc2-install.sh
sudo awg-route status
sudo awg-route source list
sudo awg-route client list
sudo awg-route diagnostics
```

Record backup path and SHA. Installer must select upgrade mode, preserve the
AWG config byte-for-byte and not rebuild/update the AWG core. Compare env,
clients, source metadata/cache and domain files against the archive. Confirm
`/etc/awg-pbr/version` is `1.1.0`, never the Debian version, and marked ping
has no invalid-argument errors with the original `HEALTH_MARK=0x101` env.
Do not use `awg-update gateway` to select RC2: it follows stable releases.

If the upgrade fails, keep the backup and logs. To restore on this same Pi:

```bash
sudo systemctl stop awg-pbr-health.service awg-opencck-update.timer awg-opencck-update.service
sudo /usr/local/sbin/awg-pbr-failopen
sudo systemctl stop awg-quick@awg0.service
sudo tar -C / -xzf "$backup"
sudo systemctl daemon-reload
sudo systemctl restart awg-pbr-setup.service dnsmasq.service awg-quick@awg0.service
sudo awg-route reload
sudo systemctl start awg-opencck-update.timer
```

## 14. RC2: network transaction

- Run `sudo awg-route network reconfigure` on unchanged LAN: no changes.
- On a controlled test network, change Pi lease/subnet/interface/router first.
  Confirm `status` warns and shows saved/actual values. Ensure SSH access to
  the new Pi address before applying gateway changes.
- Check the old/new preview and cancel: all files/services remain unchanged.
- Accept and verify env, dnsmasq listen/interface, nftables LAN/NAT rules, DNS
  query via Pi and DIRECT connectivity. Check sources/static sets are restored.
- Old LG allow-list address must prompt a separate warning; `--yes` alone must
  fail if out-of-subnet clients exist. No automatic deletion or remapping.
- Add the new LG address before deleting the old one. Recheck selective PBR.
- Inject a dnsmasq/nftables failure on a disposable Pi image. Verify rollback
  restores files and attempts service restoration; a failed restoration leaves
  health stopped and policy DIRECT. This cannot undo the external DHCP change.

## 15. RC2: AWG profile transaction

- Prepare a second valid native IPv4 profile. Test CLI and VPN TUI replacement.
- Cancel confirmation and try invalid keys, missing AWG fields, hooks,
  unsupported core fields: live config and services must remain untouched.
- Set DNS and Table=auto in the input; installed result must remove DNS and
  contain Table=off with permissions 600.
- Confirm DIRECT during switching and a fresh handshake plus tunnel transport
  before policy restoration. VPN-off must stay off.
- Try an unreachable server: automatically restore the previous profile and
  recheck its handshake/transport. If neither server works, retain DIRECT and
  stop health. Confirm no keys appear in output/logs.
- Run `sudo awg-route config rollback` and the equivalent TUI item. Confirm
  previous config becomes active and the replaced one becomes previous.
- Compare env, clients, OpenCCK metadata/cache and domain lists byte-for-byte.
- Reboot and repeat LG playback, OpenCCK offline/timer, import/export,
  noninteractive SSH/SCP and diagnostics checks above.

## 16. Automated RC2 coverage

CI runs the existing suites plus `tests/test-rc2.sh` (actual installer CIDR
functions under nounset, version isolation and actual emitted transport
function with decimal-only ping), OpenCCK service-record fixtures and
`tests/test-maintenance.py` (discovery, sanitization, cancellation, transactional
file preservation, injected apply failures, health gating and auto/manual
rollback). Service/network calls are mocked in Python; real AWG core preflight
and end-to-end packet routing must pass the hardware checklist above.

Create `rc/v1.1.0-rc2` only at the exact successful `develop/v1.1.0` CI SHA.
No release/tag or changes to main/RC1 are part of this gate.

## 17. Follow-up from the RC2 hardware test

The existing Pi upgrade and reboot were tested with LG playback working,
the saved LAN/client addresses and OpenCCK youtube cache retained. Health
initially showed DIRECT after reboot and later recovered to ACTIVE; its
transient cause was not established from logs.

AWG tools v3.1.20260812 revealed an unmasked header-protection key in human
`awg show` output. Gateway output now masks it before the diagnostics tee and
installer log; `WG_HIDE_KEYS=never` cannot bypass the gateway helper. Old
reports are not rewritten and should not be shared without redaction.

Native v3.1 import/rollback now accepts HeaderProtectionKey and the additional
core fields without requiring legacy H1-H4. IPv6 AllowedIPs such as `::/0`
are preserved alongside the required IPv4 default. IPv6 PBR remains unsupported.
Tests use synthetic keys only, never the real Pi profile.

CI additionally builds the exact upstream versions reported by the Pi:
tools v3.1.20260812 (`ee0f0a9aa34ff0a0da4b3433b9512781cfe02843`) and
go v3.1.20260828 (`b5928efb6ca19f0153958460c3d141f04abc5c2e`). It runs real
`awg-quick strip` and `awg setconf` preflight in isolated network namespaces,
including a v3.1 profile, legacy profile and invalid core parameter.

After installing the follow-up build, first run the non-switching check:

```bash
sudo awg-route status
sudo awg-route config check /etc/amnezia/amneziawg/awg0.conf
```

Check that key values are hidden and profile validation succeeds with LG still
playing. Do not attempt profile replacement/network migration until that passes.
CI does not establish real-server replacement/rollback transport behavior.
