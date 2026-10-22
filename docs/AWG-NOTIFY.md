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

## Testing and current status

Isolated rootless contract tests (including daily/menu/pairing): `python3 -m unittest discover -s tests -p 'test_notify*.py' -v`.
To stage **only** AWG Notify on the isolated test Pi (not full installer),
copy the branch's `src/`, `units/`, `tests/`, `install.sh`, and `scripts/`
into a disposable fixture, then run as root `scripts/awg-notify-test-install.sh`.
This script refuses to overwrite installed AWG Notify units, verifies tests,
installs the tool and FOUR passive systemd units, verifies those units, and
leaves both timers disabled. If deployment fails, newly written files are
removed and daemon-reload is repeated. It never restarts a VPN.

Pending: real Bot API send, live installed-unit check, real MikroTik SSTP
proof, full installer clean-install and upgrade, real failover/boot/LAN checks.
Do not enable on production before gates are closed.
