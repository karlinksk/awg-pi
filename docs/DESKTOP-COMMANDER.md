# Optional Remote Desktop Commander on a Raspberry Pi

Remote Desktop Commander (DC) is **not part of VPN dataplane, DNS, the transport selector, or gateway health**. It is an optional device agent for administration. A gateway must keep operating even when DC is offline or unpaired.

Official setup: https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/remote-device/README.md

## Installer components

Versioned in this repository and deployed to fresh installs **and upgrades**:

- `src/awg-dc` → `/usr/local/bin/awg-dc`: safe onboarding/diagnostics CLI.
- `units/awg-dc-remote@.service` → `/etc/systemd/system/awg-dc-remote@.service`: **disabled** systemd template; runs under a normal user, not root.
- `install.sh` stages both files and does not copy credentials, touch routing/SSTP, or authorize a device. After explicit `AWG_DC_AUTOSTART=1`, it **enables the persistent service only for an already-authorized ordinary user**. Otherwise the service remains inactive; existing enabled/disabled state is preserved during an upgrade.
- On a **fresh installation**, the installer uses Stage18's SHA256-verified Node.js `v22.16.0` and exposes it as the machine-wide `node` command at `/usr/local/bin/node`. Debian's APT-managed `/usr/bin/node` is retained, but no longer takes precedence for normal PATH resolution. DC runs with this verified system Node and native `WebSocket`; Stage18 keeps its separate pinned cache/RAM copy. `npm` itself is installed only when needed for DC or other npm tools. On **existing installations**, changing the Node runtime is gated behind explicit `AWG_SYSTEM_NODE_UPGRADE=1`, preserving live services and existing Node binaries by default.
- With explicit `AWG_DC_PREPARE=1` and `AWG_DC_USER=<your-Linux-user>`, `awg-dc prepare` checks Debian npm, prefetches the pinned DC agent into the ordinary user's **persistent local npm cache**, and verifies that an **offline/cache-only** launch can locate it. If the host has not yet migrated system Node 20, isolated `node@22` remains the compatibility fallback. Preparation failure warns and does not roll back the gateway.

DC is an official third-party npm dependency, not vendored into AWG. It requires a Node.js runtime with native `WebSocket`. The verified preferred runtime is the machine-wide pinned `v22.16.0` copied from Stage18's SHA256-checked cache; older existing installations can still temporarily use isolated npm `node@22`. Debian 13's Node.js 20 cannot start the tested DC 0.2.52 remote agent: it fails with `native WebSocket not found`. The gateway candidate pins the npm package to `@wonderwhy-er/desktop-commander@0.2.52` (publisher's npm release observed on 2026-10-17) instead of auto-following `@latest`. This prevents unreviewed changes on reboot. Debian 13 ARM64 pairing, autostart and reboot acceptance are still pending; update the pinned version only after compatibility testing.

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

The systemd unit is a **system** service (not a user-session unit) running under the non-root account (`User=%i`). It is enabled into `multi-user.target`, starts without an SSH login and does not require `loginctl linger`. The agent reuses the existing owner-only session file and the local npm cache. It has `Restart=always` with a 20-second delay for unexpected or clean exits, independent of AWG/Mihomo. Internet access to the DC cloud and a connected, authorized ChatGPT plugin are still required; no inbound firewall port is needed. `systemctl active` or a local session file does not by itself prove cloud connectivity; check DC dashboard and execute a harmless remote command.

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
6. Use `awg-dc doctor` to distinguish system Node 22 + native WebSocket from isolated Node fallback, npm/npx, local-session presence and systemd status. Agent discovery from ChatGPT is a separate end-to-end check.

## Acceptance before release

- [ ] Syntax and installer regression tests pass.
- [ ] Fresh Debian 13 ARM64 clean install installs verified machine-wide Node.js v22.16.0, confirms `node -v` and native WebSocket, and stages DC CLI and inactive unit without npm unless opted in.
- [ ] Explicit prepare uses the preferred system Node.js 22 runtime when present; on an older, unmodified upgrade it verifies an isolated Node.js 22 fallback and prefetches DC without a root-owned user cache.
- [ ] Normal-user browser-based OAuth pairing works with Node.js 22 and an existing device session is reused; secret file is owner-only `0600`.
- [ ] Autostart is disabled before pairing, enabled after permission check, restarts after close of original SSH window and after full reboot with no interactive session and **no npm registry access**. Confirm device Online by a real remote command.
- [ ] Upgrade preserves existing authorization, user ownership and service enabled/disabled state.
- [ ] DC disable has no effect on AWG/Mihomo/DNS/SSH/SSTP, and a read-only connected tool call works.

As of the current PR, this is **draft code**, not proof that pairing/reboot tests have passed on the live Raspberry Pi.

### 2026-10-17 Node.js 20 failure, isolated Node.js 22 remediation

On `awg-upgrade-test`, `node v20.19.2` plus npm 9.2.0 with a saved DC session connected to both local MCP and Remote MCP but failed at startup with **`Node.js detected but native WebSocket not found`**. The previous installer check `Node >=18` was a false positive. The optional module now uses the separate `node@22` package (via npm's `--package` PATH isolation), leaving the Debian system Node.js unchanged, and checks for global `WebSocket`. The operating user's one-off recovery command is:

```bash
npm exec --yes --package=node@22 --package=@wonderwhy-er/desktop-commander@0.2.52 -- sh -c 'node --version && desktop-commander remote'
```

This intervention is a **proposed remediation until the user confirms the command and successful DC Remote reconnect**. Do not mark the Debian13 ARM64 live/reboot/upgrade checks complete yet.

### Shared system Node.js policy (installer and upgrade)

The v1.3 installer uses `scripts/awg-system-node.sh` after Stage18's verified prefetch. It installs `/usr/local/bin/node` pointing to a checked, root-owned `v22.16.0` under `/usr/local/lib/awg-pi/node/`, using the exact Stage18 pinned SHA256 and native-WebSocket probe. It **does not overwrite** Debian's `/usr/bin/node` or touch unrelated existing `/usr/local/bin/node`; conflicts fail closed. Check it with `sudo awg-system-node status`. The prepared remote DC service launches `awg-dc agent` as a non-root user; the wrapper selects the validated system Node22 first, then the isolated `node@22` npm package only as fallback. With a populated DC login, npm 9.2.0 remains under APT ownership and uses the Node22 executable at the front of PATH.

**Upgrades are different from clean installs:** system Node changes are NOT silently imposed on a running gateway. Once other Node consumers are reviewed, upgrade Node explicitly with `sudo awg-system-node apply` (after installer has staged the helper and Stage18 runtime cache), or by invoking a reviewed upgrade with `AWG_SYSTEM_NODE_UPGRADE=1`. Existing DC pairing remains user-scoped, and no reauthorization should be necessary. Node.js 22 rollout and DC reconnect/reboot are separate acceptance checks; don't report complete until actually verified.

## Persistent remote access without an open SSH terminal (v1.3 requirement)

The standard workflow is **one-time**: provision the agent, authorize this Linux user once in the official DC OAuth screen, then enable the non-root `awg-dc-remote@USERNAME.service`. After that:

- The root-owned systemd service starts at OS boot under the regular account and survives logout/SSH window closure; no lingering user session or SSH tunnel is needed.
- It uses pinned DC `0.2.52` and `node@22` as fallback until system-wide verified Node `22.16.0` is installed. **All npm packages must already be cached; the system service uses `--offline` and never requests the npm registry on boot**.
- On remote agent exit it restarts with a 20-second backoff. Cloud connectivity still depends on power, usable Internet and DC service uptime, so no guarantee of uninterrupted remote control during outages.
- Normal gateway upgrades and systemd daemon reloads must not disable an already enabled DC service or lose `~/.desktop-commander-device/device.json`. The session remains outside the public GitHub code, installer configuration and publicly shareable backups.

For an existing authorized host where files were already installed:

```bash
sudo awg-dc prepare karlinks
sudo awg-dc enable karlinks
sudo awg-dc status karlinks
systemctl is-enabled awg-dc-remote@karlinks.service
systemctl is-active awg-dc-remote@karlinks.service
```

When the **installer** is invoked with `AWG_DC_PREPARE=1 AWG_DC_AUTOSTART=1 AWG_DC_USER=karlinks`, it prefetches and tests the agent, and **only enables** the service if this very same user already has an authorized, owner-only `0600` session. Without that file the installer reports a warning and leaves service off. First-time OAuth pairing cannot be safely automated; after pairing, `sudo awg-dc enable karlinks` is the one-time manual final step.

If the Pi is rebuilt from a blank OS, OAuth credentials cannot magically survive a wiped `/home` directory. A **verified full-media backup and restoration** preserves the user's credentials and service enablement. Do not publish, print, copy across different machines, or transfer `device.json` to another unrelated host. Reauthorize with the official interface when truly reinstalling from scratch without preserved user data.

**To stop or revoke access:** `sudo awg-dc disable karlinks` stops/unenables the service without deleting authorization; revoke authorization separately in the official DC device dashboard if desired. A service restart must never change DNS, policy routing, VPN services, SSH, MikroTik or SSTP.

### Verification required before stable release

1. Cached-only `npm exec --offline` start of DC under Debian Node 20 fallback and with verified system Node 22.
2. Enable through the service only after a pre-existing approved session and strict ownership/permissions checks.
3. Close the foreground SSH-started DC process and SSH terminal; device remains Online through systemd and executes a harmless remote command.
4. Restart/stop the service, simulate network outage and confirm recovery without reopening SSH.
5. Reboot test Pi and check DC device Online, unit `active/enabled`, correct Node process, same device identity and preserved OAuth authorization.
6. Perform a gateway version upgrade and an intentionally failed upgrade with rollback; verify the DC service and local npm cache are not lost. Validate no inbound firewall changes or impacts to routing/SSTP.

