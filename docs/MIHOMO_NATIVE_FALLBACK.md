# Mihomo native fallback — Stage26 candidate

Status: **experimental, disabled by default**. The changes in this document do not authorize a production activation.

## Ownership

- Mihomo native `fallback` group `AWG-MIHOMO`: sole owner of active *node* choice. The order of its configured candidates defines priority. This feature is not installed/enabled by this PR.
- `awg-selection-monitor`: owner of *transport* health and Mihomo → AWG switching when all Mihomo nodes fail. With `AWG_MIHOMO_NATIVE_FALLBACK=1`, it must not invoke the legacy `awg-mihomo-node-policy failover`.
- `awg-mihomo-smart`: observer only (`SHADOW_ONLY`); may recommend candidates but must not change the active node, transport, routes or provider.
- `awg-transit-nft`: FAIL-CLOSED forward policy for Transit. Endpoint underlay DIRECT must be explicitly verified and protected against recursive tunnelling.
- Healthy AWG is sticky: no automatic AWG → Mihomo failback solely because Mihomo becomes available. AWG → Mihomo is permitted when AWG becomes unhealthy and Mihomo passes preflight.

## Status and compatibility

`awg-mihomo-configure status` keeps the legacy `Selected node:` field (persisted configured node) and adds `Active node (Mihomo API):` (runtime selection). A helper queries only a loopback `external-controller`. It requires the group's `now` value to be in the actual group's `all` or configured members; otherwise it reports `unknown`. An inaccessible controller is **not** interpreted as success. The helper cannot modify the controller. The helper can read an optional controller secret but never prints it.

`AWG_MIHOMO_NATIVE_FALLBACK` defaults to `0`. Changing it alone does not create the Mihomo fallback group. Production deployment requires a separate config-generation change and a runbook.

## Verified test evidence (2026-10-12)

- Stage22: a single isolated Mihomo selected the working primary, then selected the backup after a local proxy endpoint was disabled, then returned to the primary on recovery; HTTPS probe returned 204 throughout the sampled sequence. Observed sample times: fallback 2.9 s, recovery 5.3 s (not exact switching latencies).
- Stage25: mock `selection-monitor` cases confirm native node ownership, Mihomo → AWG, sticky healthy AWG, AWG → Mihomo after AWG failure, and no successful selection of an unhealthy candidate when both transports fail.
- Stage26: isolated four-namespace packet test using generated `awg-transit-nft` rules: client → VPN passes (2/2); client → direct WAN blocked both with VPN up and VPN interface down (0/2 each). The gateway itself could access the test WAN (1/1).
- Stage26 Python tests: 70 passed; the seven new active-node helper tests cover provider groups, selector, loopback-only controller, bearer auth, missing controller, unknown selected node and invalid config.
- Stage26 `test-selection.sh`, `test-mihomo-configure.sh`, `test-transit-nft.sh`, `test-transit-routing.sh` and `test-transit-preflight.sh`: passed.

## Prerequisites before enabling in production

1. Preserve full backups of Mihomo, AWG, routing and firewall. Leave MikroTik SSTP and remote management untouched.
2. Generate and verify `AWG-MIHOMO` native fallback config from an explicit allowed node order; never infer permission from performance scores alone.
3. Ensure **every** possible Shadowsocks/VLESS outbound endpoint has a verified, persistent DIRECT underlay route, avoiding a loop via Mihomo/AWG; recheck after candidate changes and router failover.
4. Prove end-to-end selection health probes, failed endpoint behavior, switching to AWG after all Mihomo candidates fail, and safe rollback with the current subscription.
5. Verify the Transit guard and nftables on the actual device again. Keep the production AUTO SMART timer disabled until its design is explicitly approved.
6. Activate the opt-in monitor mode only with working native fallback, then observe controlled failover before authorizing unattended use.

No credentials, subscription URLs, or private config files belong in Git history.
