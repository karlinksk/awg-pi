# AWG Notify — Telegram notifications (experimental draft)

This independent, optional **disabled-by-default** notification subsystem is
not part of the v1.3.0 release gate and must never change transport state, PBR,
DNS, nftables, MikroTik configuration or the safety of SSH/SSTP.

## Transport routing

- `mihomo0`: bound IPv4 HTTPS connection through Mihomo TUN.
- `awg0`: bound IPv4 HTTPS connection through AmneziaWG.
- `eth0`: **disabled by default**. It can reach the LAN router (MikroTik),
  but is NOT proof of SSTP, and RouterOS might send it DIRECT if SSTP fails.
  The fallback is used only when a root-owned (0600) file
  `/etc/awg-pbr/notify/router-sstp-approved` has the exact content
  `SSTP_VERIFIED_FAIL_CLOSED=1`. That attestation is permitted only after
  actual RouterOS SSTP-UP and SSTP-DOWN route/egress acceptance; never create
  it based on IP reachability alone. The notifier does not change RouterOS.
- Selection tries the currently configured transport first, then other paths.
  It does not edit the route or mark a LAN/client packet. If no path can reach
  Telegram, the message remains queued for a later retry.

**Operator decision required before calling SSTP operational:** inspect
MikroTik routing policy/actual egress for Telegram Bot API and perform a
real send via eth0 while SSTP is known up, then repeat with SSTP unavailable.
Do not infer SSTP simply from an HTTPS 200 response via eth0.

## Configuration and secrets

Create a bot using Telegram BotFather and send `/start` to your bot.
The interactive `configure` command accepts an existing numeric chat ID, or
press Enter to use safer one-time private pairing: it prints `/pair <random>`,
which you send in the bot's private chat, and then press Enter to fetch the
message. The token is not persisted until the matching private chat is found. The bot token must never appear in a
command-line argument, GitHub, log or shared diagnostic output.

Commands (after installer deployment; requires root):
```sh
sudo awg-notify configure     # interactive prompt, token is hidden
sudo awg-notify status        # no secrets displayed
sudo awg-notify test          # queues and attempts one test notification
sudo systemctl enable --now awg-notify-flush.timer
```

If a mistaken numeric chat ID was saved as `1`, **do not send a test
message** and do not enable notification timers. Run the installed,
operator-invoked `sudo /usr/local/sbin/awg-notify-pair-repair`. This command
reads the existing root-owned bot token, verifies the actual bot public
username through Telegram `getMe`, shows the exact `t.me` link and
an ephemeral private `/pair` challenge, then polls available updates for
up to two minutes. It accepts only a matching private command sent by the
chat's own account. It only replaces the chat ID upon success and does not
send messages, consume updates, change webhook, or alter gateway routing.
It refuses to overwrite a configured chat ID other than the known erroneous
placeholder. The correction is not evidence of message delivery; follow
with `sudo awg-notify test` and personally confirm receipt.

The root-only token lives at `/etc/awg-pbr/notify/telegram.json` (0600);
the event queue lives at `/var/lib/awg-pbr/notify/events.sqlite3` (0700
parent). The installer installs the binary and units but does not activate
the timer. On upgrade, existing secrets and policies are not overwritten.

Emit a safe, non-secret event:
```sh
printf '%s' 'Mihomo failed over to AWG; postcheck passed' |
    sudo awg-notify emit --kind TRANSPORT_FAILOVER --severity warning --key mihomo-awg
```
Producer integrations must only emit an event **after verified postcheck**.
To avoid secret leakage, never put configuration files, keys, tokens, UUIDs,
provider URLs or raw stderr in events.

The SQLite store provides persistence and 120-second fingerprint
deduplication. At most 500 undelivered events are stored, preferentially
retaining critical events. This is at-least-once delivery: a lost Telegram
HTTP response can produce one duplicate after a retry. A failed send cannot
be called PASS. Only a received message is end-to-end verification.

## Russian menu and daily report

The installer stages both the delivery timer and the local 09:00 daily
snapshot timer **disabled**. After operator setup, use
`awg-menu → Системные функции → Telegram — уведомления`.
Configure the token and private chat directly on the Pi, send a test,
confirm it actually arrived, then enable message delivery and optionally
daily reports. Daily reports use the Pi's local timezone (currently set on
the test stand to Asia/Novosibirsk); the report reads thermal, disk, RAM,
uptime, selected transport identity and local systemd state. This is **not**
a proof of VPN egress or LAN/client availability.

The automatic delivery timer sends at most two queued messages per run;
remaining items wait for the next run. A queued event does not mean Telegram
received it. Real confirmation requires the human recipient.

## Watch service AF_NETLINK sandbox issue (2026-10-22)

The optional `awg-notify-watch.service` runs `awg-transport check`, which
uses `ip link show`. `iproute2` obtains link state through `AF_NETLINK`.
The first draft service restricted the socket families to UNIX/INET/INET6,
which makes the `ip link show` preflight fail inside the systemd sandbox
while root-shell checks can still return healthy. This produced spurious
`NOTIFY_WATCH=suspect/down`, despite healthy Mihomo API, proxy and OpenAI
TUN checks. **Do not report a confirmed outage from this historical alarm.**

The corrected unit permits `AF_NETLINK` *only* for the optional watch
service, without altering routing, PBR, DNS, SSH/SSTP or any VPN selection
logic. The standalone passive probe must demonstrate a failing
old-sandbox `ip link show` and a passing revised-sandbox invocation before
re-enabling `awg-notify-watch.timer`. Until then, leave only watch disabled,
with Telegram delivery/daily timers unchanged. A valid fix in code or tests
does not equal a real runtime validation.

## v1.3.0 menu integration and test-Pi staging (2026-10-22)

The main AWG menu includes a latest deployed Russian dialog theme (white
breadcrumbs, high-contrast windows, no torn scrollbar), unified Mihomo/Xray
node views, and the existing Desktop Commander helper under system item **9**.
Telegram is system item **10**, with delivery configuration, test, daily
reports, Watch/boot toggling and one-time pairing repair. The older
installer branch had competing item **9**; replacing the deployed menu wholesale
would discard recent UI and DC functions. The tracked `src/awg-menu` now
reconciles the deployed UI with Telegram and restores the draft installer
first/secondary transport onboarding handlers for **clean installs**.

`install.sh` installs this exact `src/awg-menu`, the `src/awg-notify.py`
sender, `scripts/awg-notify-pair-repair.py`, and all seven optional systemd
units; notifier timers remain disabled by default on a clean install.
Existing installations must retain the root-owned token, SQLite queue,
selected node, DNS, SSH/SSTP and active VPN. Isolated test-Pi staging
must verify pinned source checksums and preserve a rollback copy of the
existing menu. Do not treat isolated rootless tests or staging as proof of
real clean-install or production readiness.

## Testing and current status

Isolated rootless contract tests (including daily/menu/pairing): `python3 -m unittest discover -s tests -p 'test_notify*.py' -v`.
To stage **only** AWG Notify on the isolated test Pi (not full installer),
copy the branch's `src/`, `units/`, `tests/`, `install.sh`, and `scripts/`
into a disposable fixture, then run as root `scripts/awg-notify-test-install.sh`.
This script refuses to overwrite installed AWG Notify units, verifies the
SHA256 checksums of the reviewed files (the tests must be run as an ordinary
user first), installs the tool and SEVEN passive systemd units, verifies those units, and
leaves both timers disabled. If deployment fails, newly written files are
removed and daemon-reload is repeated. It never restarts a VPN.

Pending: real Bot API send, live installed-unit check, real MikroTik SSTP
proof, full installer clean-install and upgrade, real failover/boot/LAN checks.
Do not enable on production before gates are closed.


## Test-Pi menu installation and gateway update safety (2026-10-22)

- A pinned, audit-diffed menu-only installer was run by the operator on
  `awg-upgrade`. Installed `/usr/local/sbin/awg-menu` SHA-256
  `bcc82ecbf97cc0c1d61fdec8529180e41f3a4f4596c202a3797a3ce3bf155057`.
  The difference from the preinstall menu was restricted to Telegram
  integration and navigation. Existing Desktop Commander remains at system
  entry 9; Telegram is entry 10. Bash syntax is valid. The previous menu
  is backed up under `/var/backups/awg-gateway/notify-menu.sxSqWZdh/awg-menu`.
- Installed the interactive repair helper root-only with mode 0700;
  operator's SHA-pinned installation confirmed `PAIR_HELPER_INSTALLED=YES`.
  Existing notifier, SSH, DNS, Mihomo and gateway health services were not
  restarted. Both policy route tables remain routed over mihomo0.
- At 16:18 +07, AWG Notify Watch had completed consecutive scheduled
  `NOTIFY_WATCH=up` checks, all three notification timers were enabled,
  and the latest flush queue state was 0. This confirms healthy observation
  **without** simulating a genuine VPN outage/recovery.
- The draft `install.sh` installs the same menu, Telegram helper, notifier
  binary and seven passive systemd units on a future clean install.
  The `src/awg-update` rollback manifest now includes notifier binaries,
  seven units, persistent SQLite queue and preserves opt-in enablement states
  of delivery, watch, daily and boot service after rollback.
- Source syntax and **52 isolated notify/installer tests** passed on the
  isolated Pi. A complete clean install, actual gateway upgrade/rollback,
  reboot, genuine failover, LAN forwarded traffic and SSTP proof remain
  **unverified**. Source is only in draft PR #158 stacked on draft #115;
  the active menu was installed separately on the test Pi, not production.
