# Installer-first change policy

**Mandatory rule for AWG Pi Gateway maintenance:** every successfully confirmed runtime correction, hotfix or new behavior must be incorporated into the version-controlled **installation and upgrade source** before the related task is considered closed. A fix that exists only on a Raspberry Pi, in a temporary file, a chat, or an issue comment is **not complete**.

This applies to both **Selective Gateway** and **MikroTik Transit / Backup VPN**.

## Workflow for every finding

1. **Observe and isolate.** Save a sanitized description of the original failure, a reproducible check, and the relevant operating mode. Distinguish assumptions, experimental work, and verified results. A passing localhost proxy check does not demonstrate TUN operation or forwarded LAN traffic.
2. **Confirm safely on the test stand.** Reproduce the failure, apply the smallest candidate fix, run a positive test and a negative/regression test, and capture the status after recovery. Explicitly check management access, selected node/transport, routing, DNS and rollback where relevant. Do not modify MikroTik/SSTP or a production Pi as a side effect of research.
3. **Make the change persistent.** Update the authoritative files tracked by the repo: `src/`, `scripts/`, `units/`, `extras/`, `install.sh`, generated configuration/templates and **the existing-install upgrade path**, as applicable. Installer artifacts must be installed with correct ownership, permissions and dependencies. Do not leave critical behavior in untracked helpers on the Pi. No credentials, subscription URLs, private keys or user-specific addresses in public commits.
4. **Test the installer path.** Add a regression test for the found bug and verify both a **fresh install** and an **upgrade** (preserving configured policies and private data). Run syntax/static tests plus all relevant CI/integration tests. Where hardware or live routing is needed, record that gate explicitly as pending until tested. A pending test is not a pass.
5. **Document and commit.** Update user-facing usage/recovery instructions and troubleshooting; link the finding, test evidence and relevant source/installer changes to the PR. A PR is not the final release: do not merge/promote until required acceptance and rollback checks pass. Preserve a practical rollback path.
6. **Confirm delivery.** Verify the exact Git commit/branch includes the change and that an actual future install/upgrade would deploy it. Close the item only after that verification. Distinguish **committed to a draft PR**, **merged**, **released** and **installed on a device** in reports.

## Acceptance checklist

- [ ] Verified behavior and reproducible original failure
- [ ] Source fix and every required installer/unit/template/upgrade change committed
- [ ] Regression tests added; existing tests checked
- [ ] Fresh-install and upgrade behavior assessed, including idempotence
- [ ] SSH, router management/SSTP, DNS, selected transport/node and fail-open/fail-closed semantics protected
- [ ] Guarded rollback and asynchronous route recovery checked where applicable
- [ ] Secret-free documentation updated
- [ ] Commit verified; PR status and remaining hardware gates reported accurately

## Owner-directed selection revision — 2026-10-24

Manual never gates on external reachability. AUTO uses fresh engine-native
fixed-Selector network assessment, independent of OpenAI/ipify/ChatGPT/YouTube,
for incumbent failure and candidate recovery. This latest owner instruction
supersedes the earlier local-only AUTO contract and older HTTPS/READY rules.
Distinguish negative engine network evidence from controller/infrastructure
unknown; preserve local core/profile/route/guard/management checks, quiesce,
retry and rollback. Engine delay is not proof of Pi TUN or LAN forwarding.
Independent hardware traffic tests remain required for release evidence.

## Ground rules specific to Mihomo

- **Backend/proxy availability**, **Pi-bound `mihomo0` HTTPS**, and **forwarded LAN-client success** are separate levels of evidence. Do not report one as another.
- For **Selective**, Raspberry Pi `dnsmasq` and `nftset` classify destination IPs based on client DNS requests that actually arrive at the Pi; this does **not** automatically pass hostnames to the Mihomo TUN. For **Transit**, DNS may be resolved elsewhere. Maintain DNS independence from VPN availability; never introduce hijacking, sniffing, fake-IP, router/DoH changes without targeted tests and approval.
- Under the current PR #165 scope, Hot Pool/READY and service eligibility are excluded from MANUAL/AUTO and release gates. Historical service/media experiments do not reinstate them. Preserve independent hardware forwarding evidence and local route/guard/identity safety checks; AUTO uses only the agreed native engine network assessment.
- Treat `iproute2` output semantically, not as an exact string sensitive to whitespace. Wait within bounded limits for policy routing to reappear after Mihomo restarts before judging restore failure or disarming independent recovery.
- Do not automatically promote an untested candidate to live service, merge a draft PR, or overwrite working provider/secret state. Keep a reversible plan for any test that changes the active VPN node.

**Recorded example (2026-10-17):** The active Shadowsocks node passed local proxy checks but failed actual Pi-bound TUN TLS; a reserve passed genuine `mihomo0` HTTPS without DNS or sniffing changes. The draft v1.3 installer gained an on-demand TUN verification helper, explicit proxy-bypass on its bound HTTPS checks, and warning-only first-start diagnostics. That confirms neither forwarded LAN clients nor automatic failover. Those acceptance tests remain pending.

**Policy status:** This document applies to new contributions and troubleshooting in the AWG Pi Gateway project. It is not proof that all earlier Pi-only helpers were already backported or that a draft PR has been released.
