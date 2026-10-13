# Stage27 — RAM-only Mihomo fallback candidate preview

**Status:** experimental. This helper never changes the installed Mihomo configuration, rules, routes, services, SSTP, or transport ownership. It is for isolated validation, not production activation.

## Explicit safe candidate generation

Run on Raspberry Pi after authenticating with the authorized admin helper. Use an owner-private directory under **/tmp** (confirmed tmpfs) and the exact IP and router details from the deployment. Example for the current development stand only:

```bash
sudo -n bash -c '
set -Eeuo pipefail
dir=$(mktemp -d /tmp/awg-fallback-preview.XXXXXX)
chmod 700 "$dir"
trap '\''rm -rf "$dir"'\'' EXIT
python3 -B /path/to/awg-mihomo-fallback-preview.py \
  --base /etc/awg-pbr/transports/mihomo/config.yaml \
  --provider /var/lib/awg-pbr/mihomo/providers/subscription.yaml \
  --node shadowsocks-1787606892 \
  --node shadowsocks-27307 \
  --iface eth0 --gateway 192.168.112.1 \
  --output "$dir/candidate.yaml"
/usr/local/bin/mihomo -t -d "$dir" -f "$dir/candidate.yaml"
'
```

The output is a private file containing live Shadowsocks passwords; never print it, commit it, persist it on microSD, attach it to PRs, or leave it on disk. The preview refuses any output path outside /tmp tmpfs and directories more permissive than 0700; files are created with 0600 and no-follow/exclusive protections. Clean up the private directory even when validation fails.

## Hard gates

- Precisely 2–4 unique names explicitly supplied, from the loaded subscription. Stage27 currently permits Shadowsocks with **literal public IPv4** endpoints only (no hostname / IPv6 resolution drift).
- Each endpoint must resolve via the supplied LAN interface and router gateway in the **unmarked** `ip -4 route get` output. Missing, VPN-derived, recursive and unexpected routes stop generation; **no route is inserted**.
- Candidate config has only explicitly selected nodes, with the original 1,800+ node subscription excluded. Group `AWG-MIHOMO` uses `fallback`, a 10-second health interval and HTTPS URL. Shadow ports 17931/17932 bind loopback. TUN, auto-route and auto-redirect are off. Production rules are never applied.
- The endpoint DIRECT check is a **necessary precondition, not a persistence guarantee**. It does not prove MikroTik forwarding, changes in the route after startup, endpoint DNS changes, or fwmark routes. Real deployment requires ongoing route assertions and a clean rollback if any prerequisite fails.
- Stage27 does not alter `AWG_MIHOMO_NATIVE_FALLBACK`. PR #85 makes that flag opt-in, but does not activate fallback groups.
- Stage27 is **not** compatible with automatic use of all provider nodes. Explicit allow-lists must be revised and revalidated after subscription updates.

## Test evidence (12 October 2026)

- Local Python tests: 8 passed, including duplicate/missing candidates, invalid endpoints, recursive route detection and output-file path controls.
- Real Raspberry Pi shadow preview with `shadowsocks-1787606892` → `shadowsocks-27307`: both endpoint routes verified DIRECT via `192.168.112.1 dev eth0`; Mihomo configuration validation passed; controller reported `Fallback` with the primary selected; HTTPS request returned 204 in approximately 219 ms. No production TUN or table 100 changes.
- Wrong gateway `192.168.112.254` was rejected before the candidate file was created.
- The earlier Stage22 one-process live shadow test observed native fallback and failback; Stage26 packet-level Linux namespace tests confirmed Transit FAIL-CLOSED against a DIRECT WAN bypass.
- Temporary ports, processes and secret files were removed.

## Remaining production gates

Do not enable unattended native fallback until integration includes persistent DIRECT route checks, compatible provider refresh/rollback, active node API state handling, bounded deployment changes with backup/restore, and live safeguards for unhealthy Mihomo, AWG recovery and Transit guard.
