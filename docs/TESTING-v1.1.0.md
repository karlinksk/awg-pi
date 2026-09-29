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

- hardware-check executable snapshot
  `5c26398c52fa39066547e84b8429146c846d0016` for the new transactional
  upstream DNS CLI/TUI path;
- complete remaining release-gate checklist items that have not yet been
  exercised on the frozen RC2 snapshot, including `--replace` bulk import where
  applicable and final release audit.

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

The frozen RC2 snapshot uses buffered `open('/dev/tty', 'r+')`, which
fails on a non-seekable Linux terminal. No-op network detection and
`config check` bypass confirmation, so their hardware results do not cover it.
The follow-up uses separate UTF-8 input/output terminal streams.

CI runs `python3 tests/test-confirm.py` on Linux without root. Real controlling
PTYs reproduce the old failure and verify affirmative answers (including
Russian), repeated prompts, rejection, empty input and EOF. Standard streams
are redirected to ensure confirmation still uses the controlling terminal.
Without a terminal, piped "yes" is rejected; explicit `--yes` remains supported.

Before hardware maintenance tests, use a build containing this fix.
Cancel an actual changed-network/profile proposal and verify no configuration
or services changed; then perform the approved switch and rollback checklist.
This follow-up does not move the frozen RC2 branch.

Hardware confirmation on the existing Raspberry Pi:

```text
tested code SHA: 187bb100701a8a17655cfe0fa1ca62a97db66408
result: PASS
```

The existing Pi was upgraded to that exact tested code SHA with its current
gateway configuration preserved. The installed `manage.py` contained separate
UTF-8 read/write handles for `/dev/tty`. A real interactive
`awg-route config replace` using the current native profile reached the
confirmation prompt, answer `n` cancelled cleanly, and no traceback/OSError
occurred. A subsequent `awg-route status` remained healthy: VPN policy
requested ON, health `up`, policy rule ACTIVE, all gateway services active,
client allow-list retained, OpenCCK source/cache retained, fresh AWG handshake,
and private/preshared/header-protection keys remained redacted.

This validates the cancellation path for the post-RC2 confirmation fix on real
Raspberry Pi hardware. The in-subnet LAN apply path and the second-server profile
transaction were subsequently completed on the same executable code snapshot.
Later documentation-only commits do not redefine that tested code snapshot.


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

Executable snapshot under hardware test:

```text
5c26398c52fa39066547e84b8429146c846d0016
```

The post-cancellation follow-up adds:

```text
awg-route dns status
awg-route dns set IPv4[,IPv4...] [--yes]
System -> DNS upstream
```

The change is transactional across `/etc/awg-pbr/env` and
`/etc/dnsmasq.d/99-awg-pbr.conf`. It accepts one to four unique IPv4 upstream
servers, rejects invalid/self/loopback/multicast values, checks direct DNS
reachability before confirmation, validates `dnsmasq`, restarts it, and
requires a successful DNS query through the Pi. An apply failure restores both
files and attempts to restart the previous dnsmasq configuration.

CI must cover successful replacement, invalid input, explicit cancellation,
rollback after an injected apply failure, and status reporting.

Real Raspberry Pi hardware test:

1. Confirm the current state reports `1.1.1.1,9.9.9.9`.
2. In the TUI open `System -> DNS upstream`, enter a temporary valid pair
   different from the current pair and accept.
3. Confirm the operation reports direct upstream checks, creates a `dns-*`
   backup, reports dnsmasq/query success, and `dns status` plus the managed
   file show the new values.
4. Confirm ordinary client DNS and LG/OpenCCK routing still work.
5. Change back to `1.1.1.1,9.9.9.9` through the TUI and verify status again.
6. Exercise one `n` cancellation and confirm no DNS files change.

This is a focused DNS maintenance test; it does not reopen the deferred
different-subnet LAN migration gate.
