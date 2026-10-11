# AUTO SMART v2 — installation and recovery

This is an **experimental, opt-in, shadow-only** observer. Do not enable automatic SMART node switching: none is implemented. The separate Mihomo benchmark must not modify MikroTik, SSTP, the production Mihomo instance or AWG Transit guard.

## Reproducible source

The canonical staging files are in `research/auto-smart/`; `SHA256SUMS` is pinned to the six audited observer, test, documentation and unit files. Before use, check `sha256sum -c SHA256SUMS` from inside this directory.

Install prerequisites on a supported Raspberry Pi: an already working AWG Pi Gateway v1.3.x, Python 3 with PyYAML, curl, installed Mihomo at `/usr/local/bin/mihomo`, and the health-pool helper `/usr/local/sbin/awg-mihomo-pool`. A fresh installation is **not** supposed to expose subscriptions, tokens, keys or real `awg0.conf` in the repository.

## Installation (authorized operator)

From an explicitly reviewed checkout of this feature branch:

```sh
cd research/auto-smart
sha256sum -c SHA256SUMS
python3 -m unittest discover -s . -p 'test_auto_smart*.py' -v
sudo bash ./install-shadow.sh
# Optional supervised one-time benchmark:
sudo systemctl start awg-mihomo-smart.service
sudo /usr/local/sbin/awg-mihomo-smart show --count 10
```

Alternatively, `sudo bash ./install-shadow.sh --run-once` installs and runs a single cycle. The installer verifies the pinned payload, checks 23 offline tests, refuses to replace a running observer, stores root-only backups in `/var/backups/awg-pbr/auto-smart/observer-XXXXXXXX`, copies only the observer binary and its own systemd units, and automatically restores backups if the installation fails. The periodic `awg-mihomo-smart.timer` is **never enabled automatically**.

If `awg-gpt` has been separately configured with scoped allow-listed SMART operations, an authorized administrator can use `sudo -n /usr/local/sbin/awg-gpt smart-status`, `smart-run`, `smart-report`, `smart-logs` and `smart-disable`. The root-owned helper and its local sudoers entry are **not** installed or modified by this package. Generic passwordless sudo must not be granted.

## Manual rollback

Use the exact backup path printed by the installer and confirmed to exist. Example (replace `observer-XXXXXXXX`):

```sh
sudo bash research/auto-smart/rollback-shadow.sh /var/backups/awg-pbr/auto-smart/observer-XXXXXXXX
```

The rollback script restores only the SMART binary and its two systemd unit files; it leaves the observer timer disabled and does **not** touch the active Mihomo/AWG service, routing, firewall or SSTP.

## Current research limits

The default nominal budget is **85 MB per full cycle** (10×1.5 MB screening + 5×10 MB sustained download/upload + 2×20 MB confirmation), excluding protocol and retry overhead. A 3-hour timer would consume up to ~840 MB/day application data: **do not enable** that schedule as-is. Before routine 48–72h observation, tune sample counts and cadence, verify 20 MB sample compatibility, and check actual traffic, thermal and microSD impact. Histories are kept on tmpfs under `/run/awg-pbr/mihomo-smart` and reset on reboot.

Two successful 20 MB confirmations on 2026-10-11 favored retaining `hysteria2-1711051470` over `shadowsocks-27307`; that is **not** sufficient proof of long-term superiority or YouTube-specific performance. Shadow ranking is advisory. Keep Selective FAIL-OPEN, Transit FAIL-CLOSED and existing transport failover unchanged.

The upgraded `history --count 12` command displays a bounded RAM-only daypart trend. The 24 offline unit/integration tests now include data redaction, retention, protocol rotation and the history report.

## Time-bounded observation (operator-approved)

After the low-traffic observer is installed and its one-shot test succeeds, the optional timer can run at 8-hour intervals (up to ~85 MB per full run). Use the **bounded** helper rather than enabling the timer indefinitely:

```sh
# Perform one supervised test and start 72h observation in a single root action:
sudo bash research/auto-smart/deploy-observe72.sh
# Or, if already installed and checked:
sudo bash research/auto-smart/start-bounded-observation.sh 48
```

The scheduler verifies both root-installed systemd units and the installed observer against the pinned repository hashes. It writes a dedicated, persistent **one-time stop timer** for the local 48/72-hour deadline and enables the benchmark timer only after the stop timer is armed. A startup failure disables both. The stop service disables the observation timer automatically, even if the device was off at the deadline and later boots. Neither script changes the live node, transport, firewall, routes, AWG or MikroTik SSTP.

The observation timer uses `OnActiveSec=8h` and `OnUnitActiveSec=8h` so enabling it on a long-running Pi **does not immediately rerun** a benchmark. Data lives only in RAM; `history --count 12` displays the window, and normal reboot intentionally resets it. When the window closes, confirm the timer is disabled and inspect the history before considering any smart switching.

The existing allow-listed `sudo -n /usr/local/sbin/awg-gpt smart-report` prints the time-of-day history automatically after the current top nodes. No additional privileged helper permissions are necessary.
