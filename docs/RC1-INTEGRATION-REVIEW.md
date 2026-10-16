# AWG Pi Gateway v1.3.0 — RC1 integration review (16 October 2026)

**Status: DRAFT. Not an RC1 release or production migration.**

This integration branch combines, by ancestry, PR #106 (ChatGPT/YouTube eligibility),
PRs #108/#110 (Hot Pool shadow and continuity), PR #109 (staged-only periodic
subscription update), and PR #111 (READY-first AUTO canary). None of the
upstream draft PRs were merged into `develop/v1.3.0` or `main`.

## Safety defaults

- `MIHOMO_READY_AUTO_CANARY=0` remains the default. No unattended READY
  selection is enabled by the installer.
- Hot Pool binaries and its continuity wrapper are installed **passively**
  on a fresh installation. The systemd timer is not enabled/started. The
  Hot Pool itself always runs in **SHADOW_ONLY**.
- If a separate Hot Pool deployment already has an active service or enabled
  timer, the gateway installer **preserves it untouched**, instead of replacing
  a running scanner. Such deployments require a separately reviewed upgrade.
- No host or provider credentials, subscription URLs or cached secret profiles
  are committed to GitHub. The root-only continuity vault is backed up in the
  private gateway archive with file permissions retained.
- During rollback, the previous Hot Pool timer enabled/disabled state is
  restored; a previously disabled timer must remain disabled.
- Services use `ProtectSystem=strict`, `NoNewPrivileges=true`, limited
  `CPUQuota=70%` and `MemoryMax=900M`. Continuity state writes are restricted
  to the approved RAM and private vault paths.
- RouterOS, SSTP, AWG and production node-selection binaries are not modified
  by the source-only integration or its offline tests.

## Components

Installed (passive Hot Pool only):
`awg-mihomo-hot-pool`, `awg-mihomo-hot-service-scan`,
`awg-hot-pool-continuity.py`, `awg-mihomo-hot-continuity-run`,
`awg-mihomo-hot-pool.service`, `awg-mihomo-hot-pool.timer`.

READY exact-live credentials guard and TUN postcheck are installed before
the revised Mihomo selector, with Python/Bash syntax verification.

The external continuity vault is under
`/var/lib/awg-pbr/hot-pool/continuity`; temporary union profiles and
qualification proofs are under `/run/awg-pbr/hot-pool/continuity`.
Historical READY status never replaces fresh qualification.

## Reproducible review checks

- `bash tests/test-ready-install-integration.sh`
- `bash tests/test-hot-pool-packaging.sh`
- `bash tests/test-upgrade-mode.sh`
- `bash tests/test-mihomo-configure.sh`
- `python3 -B -m unittest discover -s tests -p 'test_ready*.py' -q`
- `python3 -B extras/mihomo-hot-pool-shadow/test_hot_pool.py -q`
- `python3 -B extras/mihomo-hot-pool-shadow/test_hot_pool_continuity.py -q`
- `python3 -B extras/mihomo-hot-pool-shadow/test_hot_scan.py -q`
- `python3 -B extras/mihomo-hot-pool-shadow/test_network_gate_contract.py -q`
- `python3 -B tests/test-mihomo-periodic-review.py -q`
- `systemd-analyze verify extras/mihomo-hot-pool-shadow/awg-mihomo-hot-pool.{service,timer}`

GitHub Actions runs the full existing shell suite, integrated Hot Pool tests,
and AWG v3.1 pinned build. Release remains blocked until latest commit CI passes.

## Real-network evidence from earlier acceptance

An iPhone client behind MikroTik used the selective `to_vpn_auto` policy,
source-NAT to router LAN IP, then Pi Transit/Mihomo. ChatGPT and YouTube
destination IPs were matched to MikroTik connection tracking with reply
traffic, while Pi saw router ingress and Mihomo TUN egress. READY-priority
switch and rollback worked live in opt-in canary. The selection monitor
switched to AWG under an injected Mihomo health failure, and independently
AWG HTTPS/OpenAI egress worked after a manual switch.

These real tests were performed on the prior canary staging; **they do not
constitute production acceptance of this new bundled installer**.

## Remaining review and release criteria

1. Entire integrated GitHub CI `shell` and `awg-v31` jobs green for the
   current branch head; no stale success from a prior commit.
2. Review the new install/upgrade and rollback against active externally
   managed Hot Pool and check safe failure of partially installed components.
3. Verify a truly fresh isolated install/upgrade/rollback (prefer disposable
   Debian 13 VM or Pi test partition) before tagging RC1. Source fixture tests
   and systemd static validation do not replace that system-level test.
4. Keep service enablement explicitly opt-in and preserve SSTP management.
5. After code review, resolve or merge the existing draft PR dependency stack
   in a reviewed sequence. Only then prepare/tag `v1.3.0-rc1`.

**Do not tag or install on the working Raspberry Pi solely because static
tests and CI pass.**
