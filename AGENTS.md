# Repository maintenance instructions — AWG Pi Gateway

**Mandatory installer-first policy:** Read [docs/INSTALLER-CHANGE-POLICY.md](docs/INSTALLER-CHANGE-POLICY.md) before changing this project. After any Raspberry Pi/RouterOS VPN finding is **confirmed by real tests**, incorporate the fix into the appropriate version-controlled `src/`, `scripts/`, `units/`, `extras/`, `install.sh` and existing-install upgrade path, with regression tests and documentation. A Pi-only hotfix, a temporary shell script, a chat conclusion or a PR comment does **not** finish a change.

Always distinguish these states explicitly: **experiment proposed**, **tested on the isolated Pi**, **committed to a draft PR**, **merged to main**, **released/tagged**, **installed on production**. Never call a draft or untested code a released fix. Do not merge a feature release before its real hardware/client/rollback acceptance criteria pass.

Protect network management: preserve SSH and the priority MikroTik SSTP channel; never change the router, production Pi, keys, subscription credentials or old read-only SD without explicit authorization. Keep Selective FAIL-OPEN and Transit FAIL-CLOSED semantics, current independent DNS policy, backups, rollback and node stickiness. Avoid unverified DNS hijacking, fake-IP, SNI sniffing, or blindly enforcing a new health gate.

Mihomo specific: **localhost proxy healthy != Pi-bound TUN HTTPS healthy != LAN-client forwarding healthy**. A node change must use a fresh candidate qualification, real `mihomo0` postcheck, independent recovery where disruption is possible, bounded policy-route readiness polling and correctly scoped evidence. Tests should prevent regressions such as whitespace-sensitive `ip route` matching or false successful `curl` via an inherited HTTP proxy.

For every completed fix, report the verified source/installer commit and tests; identify any pending clean-install, upgrade, reboot, LAN-client, failover or recovery gates. No secrets or user-private addresses in repository artifacts.
