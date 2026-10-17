# Optional Remote Desktop Commander on a Raspberry Pi

Remote Desktop Commander (DC) is **not part of VPN dataplane, DNS, the transport selector, or gateway health**. It is an optional device agent for administration. A gateway must keep operating even when DC is offline or unpaired.

Official setup: https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/remote-device/README.md

## Installer components

Versioned in this repository and deployed to fresh installs **and upgrades**:

- `src/awg-dc` → `/usr/local/bin/awg-dc`: safe onboarding/diagnostics CLI.
- `units/awg-dc-remote@.service` → `/etc/systemd/system/awg-dc-remote@.service`: **disabled** systemd template; runs under a normal user, not root.
- `install.sh` stages both files; it does not pair a device, copy credentials, change network routing, alter SSH, or start DC automatically.
- With explicit environment variables `AWG_DC_PREPARE=1` and `AWG_DC_USER=<your-Linux-user>` on installation, `awg-dc prepare` checks Debian `nodejs`/`npm` and, when necessary, installs bootstrap packages. It then prefetches **isolated `node@22`** and the pinned DC agent in the ordinary user's npm cache, verifying native `WebSocket`. System `/usr/bin/node` and AWG/Stage18 runtimes are **not upgraded**. A preparation failure produces a warning and does not roll back the gateway. The default is `AWG_DC_PREPARE=0`.

This is an official third-party npm dependency: the remote agent and `node@22` runtime are obtained from npm, not vendored into the AWG repository. Only download and authorize software you trust. The system Node.js 20 on Debian 13 is enough to run npm, but is **not** adequate to execute DC 0.2.52: its startup fails with `native WebSocket not found`. The remote agent must use Node.js 22+. The gateway candidate pins the npm package to `@wonderwhy-er/desktop-commander@0.2.52` (publisher's npm release observed on 2026-10-17) instead of auto-following `@latest`. This prevents unreviewed changes on reboot. Debian 13 ARM64 pairing, autostart and reboot acceptance are still pending; update the pinned version only after compatibility testing.

## First pairing on the Raspberry Pi

Run the following **after** a gateway installation, substituting your local login username:

```bash
sudo awg-dc prepare gatewayuser
sudo awg-dc doctor gatewayuser
```

Then, from a terminal **logged in as that same ordinary user** (not as root):

```bash
awg-dc pair
```

DC prints a device verification URL and one-time code. The user must open the official page, verify that the code matches, and explicitly authorize the device. Close the foreground agent with Ctrl+C after it says it is connected. Credentials are stored privately in `~/.desktop-commander-device/device.json` under that user's home. **Never copy device session files, OAuth codes, passwords, or tokens into GitHub, chat logs, backups shared publicly, or shell scripts.**

Only **after successful user authorization**, enable automatic restart on reboot:

```bash
sudo awg-dc enable gatewayuser
sudo awg-dc status gatewayuser
```

The systemd unit is user-scoped (`User=%i`) and has no inbound firewall rule. Remote connectivity still depends on the Desktop Commander service and a connected, authorized ChatGPT plugin. `systemctl active` or a local session file does not by itself prove cloud connectivity; check the DC device dashboard and perform a benign read-only terminal test.

Stop DC remote access without revoking the device:

```bash
sudo awg-dc disable gatewayuser
```

To **revoke authorization**, use the Desktop Commander device dashboard. Disabling a systemd service only stops the local process; it does not revoke the cloud-side device token.

## Security and operating rules

1. Never run `remote` as root or automatically enable a remotely controllable agent before a user approves its OAuth device code.
2. DC executes as its Linux login user. Privileged AWG maintenance must use a separately audited **allowlisted helper**, for example an explicitly approved `awg-gpt` sudo wrapper; DC preparation itself must not install `NOPASSWD:ALL` or change `sudoers`.
3. The service does not need any input/WAN firewall openings. It connects outward; do not forward a TCP port from MikroTik.
4. DC downtime has no effect on Mihomo, AWG, Selective FAIL-OPEN, Transit FAIL-CLOSED, dnsmasq, SSTP or LAN routing. Never restart VPN services just to reconnect DC.
5. Raspberry Pi test agents currently may be paired to different devices; **do not transplant `device.json`** from one SD card/host to another. Pair each device independently.
6. Use `awg-dc doctor` to check Debian Node >=18, npm/npx, local-session presence and systemd status. Agent discovery from ChatGPT is a separate end-to-end check.

## Acceptance before release

- [ ] Syntax and installer regression tests pass.
- [ ] Fresh Debian 13 ARM64 clean install stages CLI and inactive unit without Node/npm unless opted in.
- [ ] Explicit prepare verifies isolated Node.js 22 native `WebSocket` and can prefetch the package without root-owned user cache, even when Debian system Node.js remains v20.
- [ ] Normal-user browser-based OAuth pairing works with Node.js 22 and an existing device session is reused; secret file is owner-only `0600`.
- [ ] Autostart is disabled before pairing, enabled after permission check, restarts successfully after reboot.
- [ ] Upgrade preserves existing authorization, user ownership and service enabled/disabled state.
- [ ] DC disable has no effect on AWG/Mihomo/DNS/SSH/SSTP, and a read-only connected tool call works.

As of the current PR, this is **draft code**, not proof that pairing/reboot tests have passed on the live Raspberry Pi.

### 2026-10-17 Node.js 20 failure, isolated Node.js 22 remediation

On `awg-upgrade-test`, `node v20.19.2` plus npm 9.2.0 with a saved DC session connected to both local MCP and Remote MCP but failed at startup with **`Node.js detected but native WebSocket not found`**. The previous installer check `Node >=18` was a false positive. The optional module now uses the separate `node@22` package (via npm's `--package` PATH isolation), leaving the Debian system Node.js unchanged, and checks for global `WebSocket`. The operating user's one-off recovery command is:

```bash
npm exec --yes --package=node@22 --package=@wonderwhy-er/desktop-commander@0.2.52 -- sh -c 'node --version && desktop-commander remote'
```

This intervention is a **proposed remediation until the user confirms the command and successful DC Remote reconnect**. Do not mark the Debian13 ARM64 live/reboot/upgrade checks complete yet.
