# AWG Pi Gateway v1.3 — release-test safety gate (A07–A09)

**STATUS: SOURCE PLAN ONLY — ROOT BACKUP AND TIMED RECOVERY NOT YET ARMED.**
Applies to test host awg-upgrade-test and one chosen LAN test client. Main Pi,
MikroTik router-wide routes and SSTP are out of scope for modifications.

## Required before real mode/transport/node failure injection

1. Verify separate management paths: direct LAN SSH to test Pi, persistent
   nonroot Desktop Commander via systemd, and priority MikroTik SSTP from the
   actual remote administrator. Pi-to-router ping alone does not prove SSTP.
2. Validate a current full-media backup and restore-boot on spare media.
   Preserve the original SD read-only; an unmounted mountpoint directory
   is not proof of a read-only mount.
3. Freeze the code commit and capture sanitized baseline: mode, active transport,
   exact Mihomo node, policy/READY settings, DNS, ip rules, tables 100/101,
   routing and systemd status. No secrets in reports.
4. Obtain a **private root-only backup** of gateway config, AWG config, Mihomo,
   DNS rules and new Node/DC/Stage18 components, with directory 0700 and
   archive 0600. Verify archive integrity and actual rollback, not just presence.
5. Isolate one explicitly selected MikroTik LAN client/prefix. Preserve existing
   RouterOS SSTP priority and management path throughout.
6. Before touching a live network policy, arm and test a **local root-owned timed
   recovery** which restores exactly the original mode, transport, node,
   guard, routes and DNS. It must not depend on ChatGPT, DC or open SSH,
   and must not execute user-writable code or accept arbitrary file paths.
7. Test watchdog expiration harmlessly on an unchanged baseline; verify
   idempotence and no secrets printed. In Transit, an unsuccessful recovery
   MUST stay FAIL-CLOSED, without a DIRECT leak.
8. Perform actual failure injection only with timed rescue armed. Do not cancel
   rescue until baseline and real client/DNS/HTTPS path are independently
   confirmed restored. Save a sanitized report.
9. For unattended administrative work, use a separately reviewed fixed
   allowlist helper; NEVER grant generic NOPASSWD:ALL, arbitrary root shell,
   unrestricted systemctl or sudo of user-editable scripts.
10. STOP before any disruptive action if SSH/SSTP control, backup, timed
    recovery, DIRECT endpoint routes or client isolation is not proven.

## Non-disruptive evidence, 17 October 2026

- Test host Debian 13 ARM64; Pi LAN IP 192.168.112.34, router
  192.168.112.1 reachable directly via eth0 (one ICMP reply).
- ssh.service and per-user DC system service both active and enabled.
  Mihomo, selector, health and dnsmasq active.
- Private /var/backups/awg-gateway and gateway config directories are
  root-owned 0700; presence does NOT prove a complete restorable backup.
- Source redaction, diagnostic-hardening and visible-input unit tests passed;
  DC OAuth file owned by karlinks with mode 0600.
- No actual sudoers policy review was possible through DC's restricted command
  channel; user-approved root review still required.
- Old SD is not mounted after reboot; it was not mounted or written in audit.
- No independent timed failsafe is installed by this step. This document is
  NOT authorization to inject transport, mode or route failures.

## Status

A07: PARTIAL (source tests and file permission checks PASS; full sudo audit PENDING).
A08: PARTIAL (LAN and DC paths PASS; actual remote SSTP path not tested here).
A09: PENDING (root-owned verified backup, timed rescue arm/trigger and restore test).

Hardware failover tests must remain BLOCKED until A08 and A09 gates pass.
