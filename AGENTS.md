# Repository maintenance instructions — AWG Pi Gateway

**Mandatory installer-first policy:** Read [docs/INSTALLER-CHANGE-POLICY.md](docs/INSTALLER-CHANGE-POLICY.md) before changing this project. After any Raspberry Pi/RouterOS VPN finding is **confirmed by real tests**, incorporate the fix into the appropriate version-controlled `src/`, `scripts/`, `units/`, `extras/`, `install.sh` and existing-install upgrade path, with regression tests and documentation. A Pi-only hotfix, a temporary shell script, a chat conclusion or a PR comment does **not** finish a change.

Always distinguish these states explicitly: **experiment proposed**, **tested on the isolated Pi**, **committed to a draft PR**, **merged to main**, **released/tagged**, **installed on production**. Never call a draft or untested code a released fix. Do not merge a feature release before its real hardware/client/rollback acceptance criteria pass.

Protect network management: preserve SSH and the priority MikroTik SSTP channel; never change the router, production Pi, keys, subscription credentials or old read-only SD without explicit authorization. Keep Selective FAIL-OPEN and Transit FAIL-CLOSED semantics, current independent DNS policy, backups, rollback and node stickiness. Avoid unverified DNS hijacking, fake-IP, SNI sniffing, or blindly enforcing a new health gate.

Mihomo specific: **localhost proxy healthy != Pi-bound TUN HTTPS healthy != LAN-client forwarding healthy**. A node change must use a fresh candidate qualification, real `mihomo0` postcheck, independent recovery where disruption is possible, bounded policy-route readiness polling and correctly scoped evidence. Tests should prevent regressions such as whitespace-sensitive `ip route` matching or false successful `curl` via an inherited HTTP proxy.

For every completed fix, report the verified source/installer commit and tests; identify any pending clean-install, upgrade, reboot, LAN-client, failover or recovery gates. No secrets or user-private addresses in repository artifacts.

## Goal-first project continuity

Before implementing or suggesting further AWG Pi Gateway work, read [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) for the current **gateway completion goal, agreed invariants, known evidence, and next release gates**. Also consult [docs/TESTING-v1.3.0.md](docs/TESTING-v1.3.0.md). For ChatGPT project settings use [docs/CHATGPT-PROJECT-INSTRUCTIONS.md](docs/CHATGPT-PROJECT-INSTRUCTIONS.md).

Treat backup verification as a **completed supporting milestone**, not a reason to grow backup infrastructure. v1.3.0 is published; resume maintenance from the current product guide and latest verified project state. Reopen hardware only for a concrete new defect or material runtime change. Do not repeat accepted gates from historical checkboxes. Update project state only with verified facts; distinguish test Pi, old known-good SD, draft PR, merged code, released tag, and production deployment.


## Published product baseline

v1.3.0 is published at 5b1a8b802ce09a27c51f4e284f1a13207059a48e; production deployment is not implied. Read [the current guide](docs/PRODUCT-GUIDE-v1.3.0.md) and [documentation index](docs/README.md). Historical experimental statuses do not describe current release state. Preserve IMAGE_BOOT_ACCEPT=FAIL and the accepted full-media exception. Removed Hot Pool/READY/service gates and node FIXED editor must not return as release requirements; transport FIXED remains implemented. Documentation-only work does not authorize device/router/media changes.
