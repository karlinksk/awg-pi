# Stage30 — RAM-only preflight and rollback rehearsal

**Status: development tool only; cannot activate or install native fallback.**

This stage adds `awg-mihomo-stage30-rehearsal.py` for a *bounded, read-only* live-host preflight. It deliberately has **no apply/commit/install/route command**. Run it only on an authorized AWG Pi Gateway host. No production SSTP/Mihomo/AWG service is stopped or restarted.

## What is exercised

1. Require `/tmp` to be `tmpfs`, make a private 0700 temporary directory, and snapshot the existing readable Mihomo, provider and policy files into 0600 RAM-only files. Missing optional mode markers are recorded as absent.
2. Before the test, read the active Mihomo transport state, table 100, IPv4 policy rules, nftables Transit forward chain and selected service states. Refuse to continue unless Mihomo is healthy, table 100 points to `mihomo0`, and the forward guard defaults to drop.
3. Build a two-node inline native fallback candidate from explicitly named nodes. Validate all candidate endpoint underlay routes against the supplied DIRECT gateway and LAN interface.
4. Validate a **TUN-enabled production-shaped** candidate with `mihomo -t` (configuration validation only). **Never start that TUN** and never replace the installed config.
5. Make a *private replica* of the file snapshots in RAM, corrupt the first replica, restore it from the backup, and compare all restored files by SHA-256. Check that the actual source files and observed network/service states remain unchanged.
6. Remove the temporary snapshots and all sensitive config material even when a test fails.

Example on the current test stand (node names must be reverified before future use):

```bash
sudo python3 -B src/awg-mihomo-stage30-rehearsal.py \
  --node shadowsocks-696792830 --node shadowsocks-27307 \
  --iface eth0 --router 192.168.112.1
```

The tool prints only anonymized status, counts and error class names. No password, subscription URL or key is printed or stored in Git.

## Results (2026-10-13, Raspberry Pi)

- `STAGE30_PREFLIGHT=PASS nodes=2 routes=DIRECT config=MihomoValidated`
- `STAGE30_SNAPSHOT=RAM_ONLY entries=8` (ninth optional mode marker absent)
- `STAGE30_ROLLBACK_REPLICA=PASS`
- `STAGE30_PRODUCTION_MODIFIED=false` based on pre/post file hashes, routes, rules, nftables and service states
- Invalid router `192.168.112.254` rejected with exit status 2 and RAM cleanup.
- Six focused unit tests cover snapshot integrity, private file permissions, symlink rejection, missing required inputs, optional absence, source mutation detection.

## Critical distinction

**This is NOT a production rollback drill.** The corruption and restoration happen **only inside the RAM replica**, not against installed files or running services. It does not snapshot ownership, all network/RouterOS state, or perform a real service rollback. Before production activation, the actual installer must implement an independently reviewed atomic transaction, persistent protected backup, verified one-shot timeout, rollback on health failure, and control-plane connectivity checks. Underlay DIRECT routing and selection policy must be checked again immediately before and after live activation, including reboot recovery.

This stage changes neither MikroTik SSTP nor the production `mihomo0`, `awg0`, nftables, table 100, nor subscription auto-refresh policy.
