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

- run the final release audit and final-candidate smoke check.

The real second-server transaction is now hardware-validated. A full migration
to a different LAN subnet/router address is intentionally deferred; the
in-subnet Pi-address migration remains the real-hardware coverage for
`network reconfigure` in v1.1.0.

Do not move the frozen RC2 branch to include later documentation-only commits.

## 1. Clean installation

- Raspberry Pi 4 Model B, Raspberry Pi OS Lite 64-bit, Ethernet only.
- Pi IPv4 is reserved on the LAN router before installation.
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

## 18. Interactive confirmation regression (after frozen RC2)

The frozen RC2 snapshot used buffered `open('/dev/tty', 'r+')`, which failed
on a non-seekable Linux terminal. The first post-RC2 fix changed confirmation
to separate UTF-8 input/output terminal streams and passed the real profile and
network maintenance tests on:

```text
187bb100701a8a17655cfe0fa1ca62a97db66408
```

A later DNS TUI hardware test exposed a second terminal edge case: after a
`dialog` screen returned to the maintenance prompt, an intermittent malformed
or orphaned byte could make the UTF-8 text reader raise `UnicodeDecodeError`.
A minimal real-terminal reproducer confirmed the failure at the
`dialog -> /dev/tty` transition while ordinary raw input remained `b'y\n'`.

PR #7 hardened confirmation by opening the controlling TTY in binary mode,
flushing pending input before the prompt, reading the completed answer as bytes,
and decoding it safely. Existing affirmative answers (`y`, `yes`, `д`,
`да`) and the distinct cancellation status remain unchanged. CI includes a
Linux PTY regression with an orphan `0xd0` byte before `y\n`.

Hardware confirmation for the hardened path:

```text
tested code SHA: 865097deb9cb5b4f25b0cddcf80dbe285ce00384
result: PASS
```

On the real Raspberry Pi, the previously failing DNS TUI confirmation completed
without `UnicodeDecodeError`; an explicit `n` cancellation was also reported
as `Операция отменена пользователем.` and left the managed files unchanged.

## 19. Hardware result: Pi IP change inside existing LAN

Tested on real Raspberry Pi hardware using code snapshot:

```text
187bb100701a8a17655cfe0fa1ca62a97db66408
```

The physical router had already been replaced with a MikroTik ax2 while keeping
the same IPv4 LAN and router address. The Raspberry Pi DHCP reservation was then
changed from `192.168.112.33` to `192.168.112.34` while keeping:

```text
LAN_CIDR=192.168.112.0/24
ROUTER_IP=192.168.112.1
LG client=192.168.112.28
```

Result: **PASS for an in-subnet Pi IP change**.

Observed and verified:

- after reboot, the Pi acquired `192.168.112.34/24` and the saved gateway
  configuration still contained `192.168.112.33`;
- `awg-route status` detected the saved/actual mismatch and did not alter
  configuration automatically;
- interactive `awg-route network reconfigure` displayed the old/new network
  values and the `n` answer cancelled cleanly;
- SHA-256 values of `/etc/awg-pbr/env`,
  `/etc/dnsmasq.d/99-awg-pbr.conf`, and
  `/etc/nftables.d/99-awg-pbr.nft` were unchanged after cancellation;
- a second run with answer `y` created backup
  `/var/backups/awg-gateway/network-20260929-103527-u8g6_ygj` and applied the
  discovered Pi address;
- after apply, `/etc/awg-pbr/env` contained `PI_IP=192.168.112.34`,
  `LAN_CIDR=192.168.112.0/24`, and `ROUTER_IP=192.168.112.1`;
- dnsmasq listened on both UDP/TCP `192.168.112.34:53`;
- the dnsmasq configuration hash changed as expected; the nftables template hash
  did not change because the LAN CIDR/router/interface did not change;
- `awg-route status` returned health `up`, policy ACTIVE, all services active,
  fresh AWG handshake, one retained client, and the enabled OpenCCK source with
  15318 cached entries;
- LG `192.168.112.28` remained in the client allow-list;
- during LG/YouTube playback, `awg0` RX increased from 135267579 to 168786873
  bytes (about 33.5 MB), confirming substantial real tunnel traffic after the
  Pi address change;
- `awg-route diagnostics` passed: router ping, direct DNS/Internet, DNS via Pi,
  services, marked route through `awg0`, VPN transport ping and FAIL-OPEN were
  all OK; FAIL-OPEN routed via `192.168.112.1`;
- private, preshared and header-protection keys remained redacted.

This closes the real-hardware **Pi IP change within the same subnet** case.
A full migration where `LAN_CIDR` and/or `ROUTER_IP` changes remains
untested on real hardware. That scenario is intentionally deferred and is not a
remaining v1.1.0 release-gate requirement; the automated transaction tests still
cover rollback/error paths.


## 20. Hardware result: second AmneziaWG server

Tested on the existing Raspberry Pi using the post-RC2 executable code snapshot:

```text
187bb100701a8a17655cfe0fa1ca62a97db66408
```

Primary server A endpoint:

```text
89.125.68.188:43302
```

Second real server B endpoint:

```text
81.31.244.136:35104
```

Result: **PASS** for the real profile transaction path.

Observed and verified:

- the new B profile passed `awg-route config check` without changing the live
  tunnel;
- interactive TUI replacement displayed old/new endpoints and answer `n`
  cancelled without changing the active A endpoint or service health;
- replacing A -> B created a transaction backup and reported fresh handshake
  and transport success;
- after A -> B, health was `up`, policy ACTIVE, all gateway services active,
  one client retained and the OpenCCK source/cache retained;
- real LG/YouTube playback over server B increased `awg0` RX from 2520 to
  80171870 bytes (about 80 MB), confirming real client traffic through B;
- manual `config rollback` returned B -> A with fresh handshake and transport
  success;
- manual rollback normalizes the saved native profile through the strict parser,
  so the restored A file need not be byte-identical to the original input even
  though it is functionally the same profile;
- a syntactically valid test profile using unreachable endpoint
  `203.0.113.1:35104` passed non-switching core validation;
- applying that unreachable profile failed the fresh handshake/transport gate,
  triggered automatic rollback, restored A, returned health to `up` and policy
  to ACTIVE;
- the active A config SHA-256 immediately before and after automatic rollback
  matched exactly:
  `041c7ec50985bcb3bd7585845bb07f99eed0279eb19f8debc7d274effe6bb719`;
- private, preshared and header-protection keys remained redacted.

The test also exposed a TUI-only UX issue: a deliberate `n` cancellation was
reported as `Операция завершилась с ошибкой (код 1)` even though the operation
was safely cancelled. The post-test fix gives user cancellation a distinct exit
status and renders it as a normal `Операция отменена пользователем.` result,
while preserving error reporting for genuine failures.

## 21. Deferred full-LAN migration

The user explicitly chose not to perform a real migration to a different
`LAN_CIDR`/`ROUTER_IP` before v1.1.0. The tested real-hardware network case
therefore remains the Pi address change inside `192.168.112.0/24`.

This is recorded as a known untested hardware scenario, not as a blocker for the
remaining v1.1.0 release work. A future disposable/controlled environment may
exercise the out-of-subnet client warning and a real different-subnet apply.


## 22. Cancellation UX fix after second-server hardware test

PR #5 changed only the user-facing classification of an explicit interactive
cancellation. The maintenance layer now uses a distinct cancellation exit status
and the TUI maps that status to:

```text
Операция отменена пользователем.
```

A genuine failed operation still prints the error status/code. CI regression
coverage verifies both paths and passed on the merged executable code snapshot:

```text
2606a8560eaca05862400ae64e718cc6ded0a574
```

Hardware result on the existing Raspberry Pi: **PASS**. After installing this
snapshot, a real TUI `config replace` was cancelled with `n`. The UI displayed
`Операция отменена пользователем.` rather than an error. The operation reported
that settings were unchanged. No full LAN migration is required.


## 23. Upstream DNS transaction

The upstream-DNS feature first landed in executable snapshot:

```text
5c26398c52fa39066547e84b8429146c846d0016
```

It adds:

```text
awg-route dns status
awg-route dns set IPv4[,IPv4...] [--yes]
System -> DNS upstream
```

The transaction updates both `/etc/awg-pbr/env` and
`/etc/dnsmasq.d/99-awg-pbr.conf`, validates one to four unique IPv4 upstream
servers, rejects invalid/self/loopback/multicast values, probes proposed
upstreams directly, validates and restarts dnsmasq, and requires a successful
DNS query through the Pi. Apply failure restores both managed files and attempts
to restore the previous dnsmasq service state.

CI covers successful replacement, invalid input, explicit cancellation,
rollback after an injected apply failure, status reporting, and the TTY
regression described in section 18.

### Real Raspberry Pi result

Result: **PASS** after the PR #7 TTY hardening on exact code snapshot:

```text
865097deb9cb5b4f25b0cddcf80dbe285ce00384
```

Observed on the existing Raspberry Pi gateway:

- the original state was `1.1.1.1,9.9.9.9`;
- direct DNS to `1.1.1.1` timed out on the current network path, while
  `9.9.9.9`, `149.112.112.112`, `8.8.8.8`, and `8.8.4.4` answered;
  no cause for the Cloudflare-specific failure was assumed;
- CLI replacement to `9.9.9.9,149.112.112.112` passed, created a transaction
  backup, restarted dnsmasq, and passed the DNS-through-Pi validation;
- the first TUI apply on the pre-PR #7 build exposed the terminal
  `UnicodeDecodeError`, which was reproduced independently and fixed as
  documented in section 18;
- after installing SHA `865097deb9cb5b4f25b0cddcf80dbe285ce00384`, the TUI
  successfully changed upstream DNS to `8.8.8.8,8.8.4.4` and created backup
  `/var/backups/awg-gateway/dns-20260929-135802-931b0m1p`;
- with the Google pair active, real LG/YouTube playback increased
  `awg0` RX from `29207482` to `52339977` bytes, a gain of
  `23132495` bytes (~23.1 MB), confirming client DNS, OpenCCK/PBR and tunnel
  traffic remained operational;
- the TUI then restored the selected working pair
  `9.9.9.9,149.112.112.112`, creating backup
  `/var/backups/awg-gateway/dns-20260929-140410-e1wp4g1j` and again passing
  dnsmasq plus DNS-through-Pi validation;
- an explicit TUI cancellation with `n` reported normal user cancellation;
  SHA-256 values of both managed files were identical before and after:
  `aaba67a708a2ea6574af60f8bda425f1fd1884377621e2a043a6220d1177cdb3`
  for `/etc/awg-pbr/env` and
  `fee5feeafce101fbecdf0ad2b71215178dcd1be3c359ebf0f9c2dc571700f08d`
  for `/etc/dnsmasq.d/99-awg-pbr.conf`.

The active hardware-tested upstream pair at completion is:

```text
9.9.9.9,149.112.112.112
```

The subsequent PR #8 changes only installer/test-document wording from the old
router/TV-specific labels to generic `LAN router` / equipment wording and adds
the DNS commands to the installer summary; it does not change routing, DNS,
firewall or AWG behavior.



## 24. Hardware result: VPN bulk import --replace

The remaining real-hardware bulk replacement path was exercised on the existing
Raspberry Pi gateway.

Initial manual VPN list state was empty. Export and live file had the same
SHA-256:

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

A replacement input containing:

```text
replace-one.example
replace-two.example
replace-one.example
```

was applied with:

```text
sudo awg-route vpn import --replace /tmp/vpn-replace-test.txt
```

Result: **PASS**.

Observed:

- dnsmasq syntax validation returned OK;
- import reported exactly two unique domains;
- the active manual VPN list contained only
  `replace-one.example` and `replace-two.example`;
- duplicate input was collapsed as expected;
- both temporary domains were removed through normal `awg-route vpn del`
  commands;
- dnsmasq validation passed after each removal;
- the restored manual VPN list was empty again;
- the final SHA-256 of `/etc/awg-pbr/vpn-domains.txt` returned exactly to the
  original empty-file hash shown above.

This closes the v1.1.0 real-hardware `vpn import --replace` release-gate item.


## 25. Hardware result: v1.0.1 -> v1.1.0 upgrade

A separate microSD was used on the same Raspberry Pi 4 so the primary working
installation remained untouched. The test OS was Debian 13.7 (trixie), ARM64,
kernel `6.18.50+rpt-rpi-v8`, using `eth0` at `192.168.112.34/24`.

The stable v1.0.1 tag resolved to:

```text
cf1b8838c5fa204c84d5081594493e23883177a5
```

### v1.0.1 baseline compatibility note

The historical v1.0.1 installer itself required two local compatibility fixes
to complete a fresh install on the current Debian/iputils environment:

1. `valid_cidr4()` declared `x`, `ip`, and `p` in one `local` statement,
   causing `set -u` to report `x: unbound variable`;
2. health/diagnostic probes passed hexadecimal `HEALTH_MARK=0x101` directly to
   `ping -m`, while the current iputils build requires the mark as a decimal
   value. Evaluating the shell arithmetic expression yields `257`.

These patches were applied only to the temporary local v1.0.1 installer used to
create the baseline. The v1.0.1 tag/release was not modified. Once installed,
the baseline runtime was healthy: AWG handshake fresh, health `up`, policy
ACTIVE, and all core services active.

The historical v1.0.1 installer also does not create
`/etc/awg-pbr/version`; this was confirmed from the tagged installer and on the
fresh baseline.

### Preserved test state

Before upgrade, the baseline was given explicit persistent state:

```text
VPN domain:    upgrade-vpn.example
DIRECT domain: upgrade-direct.example
Client:        192.168.112.250
VPN policy:    ON
Watchdog:      PRESENT
```

The pre-upgrade state hashes were:

```text
f9f8fd734e992eb7268cabeb4bffb67499abbb87144ed1c4039c68162b6eda96  /etc/amnezia/amneziawg/awg0.conf
cc1d76b83145d2b6b51e45bfeed2ea71788cb912713a8168915771c34eb64038  /etc/awg-pbr/env
4380c3c1b8f62d9ab86df707d442dce142fcc86310f6f2ea6fbfbdfc476068d3  /etc/awg-pbr/vpn-domains.txt
01e3cbad100a543405235ba02a7d40ca3aa7c158dea8638631a6f90bc3c2fcd8  /etc/awg-pbr/direct-domains.txt
07ba6e5aea2d34452d86dd3d920049d2742ecbd878a51195b2be8dc493cbb92d  /etc/awg-pbr/clients.txt
4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865  /etc/awg-pbr/vpn-enabled
```

The AWG binaries before upgrade were:

```text
ccdbf2a44f8b2ca5934c72a0609f91ea3d608e7119fcbadddbb855d6c78191e0  /usr/bin/awg
f4bb0f5d63665ade87f0cb9f2185c43515cff09868637eb311f98f65a318722c  /usr/bin/awg-quick
db18a6bfe12f7c284f36184adf10c830012db9722ad5a554befc6a78470532a6  /usr/bin/amneziawg-go
```

A verified backup was created at:

```text
/var/backups/awg-gateway/pre-v110-upgrade-20260929-154718.tgz
```

### Upgrade result

The actual upgrade used the unmodified v1.1.0 development installer pinned to:

```text
4666018dc4ab4c17062c0f9068f986416430f25e
```

Result: **PASS**.

After upgrade:

- `/etc/awg-pbr/version` contains `1.1.0`;
- all six state/config hashes listed above are byte-for-byte identical;
- the AWG config is unchanged;
- the VPN and DIRECT test domains remain present;
- client `192.168.112.250` remains present;
- requested VPN policy remains ON;
- watchdog remains PRESENT;
- runtime health is `up`;
- policy rule priority 100 is ACTIVE with `fwmark 0x100 lookup 100`;
- all three AWG binary hashes are unchanged, confirming Gateway upgrade did not
  rebuild or replace AmneziaWG core/tools;
- installer output uses the final generic `LAN router` / equipment wording and
  includes the upstream-DNS commands in its command summary.

This closes the v1.0.1 -> v1.1.0 hardware upgrade-path release-gate item. The
historical v1.0.1 fresh-install compatibility fixes above are recorded as a
baseline limitation, not as changes to the released v1.0.1 tag.
