# Hot Pool READY-first automatic Mihomo failover (v1.3.0 RC)

The user-facing meaning of **Mihomo AUTO** on a *newly installed* AWG Pi Gateway:
- The currently healthy active Mihomo node stays unchanged; there is no opportunistic optimization or automatic return.
- The shadow-only Hot Pool independently qualifies candidates by **OpenAI API, ChatGPT network response and a decoded YouTube 24-frame video**. An HTTP 403 from ChatGPT remains UNKNOWN rather than an authenticated success; medium-confidence network eligibility additionally requires OpenAI and YouTube to PASS.
- A READY entry needs **two successful independent evaluations at least 600 seconds apart**, within the freshness window. Hot Pool scans do not modify live routes, the selected Mihomo node, SSTP or MikroTik.
- On repeated active-node health failure, node AUTO first tries a fresh READY candidate. A candidate must match the **unique exact name and all transport credentials of the current live provider**, not just an archived/union item.
- On READY exhaustion, a candidate from the live network health pool is considered only after an **independent fresh medium-confidence service scan**. Low latency or a TCP connection alone is *not sufficient*.
- Every actual switch gets a bounded post-activation validation through `mihomo0`: interface UP, marked table 100, public IPv4 egress, OpenAI API HTTP 401. If it fails, attempt to restore the old node and stop further disruptive node switching for this cycle; transport-level AWG fallback is the independent second tier **if AWG is configured and healthy**.
- Quarantine applies only to proven endpoint failures; routing readiness races and ambiguous OpenAI responses do not become two-hour shared-endpoint bans.
- On reboot the root-protected `ready-auto.mode` setting survives; the Hot Pool and Stage18 units remain independently scheduled.

## Configuration / rollback

```bash
sudo awg-mihomo-node-policy status
sudo awg-mihomo-node-policy ready-auto status
sudo awg-mihomo-node-policy ready-auto enable
sudo awg-mihomo-node-policy ready-auto disable
```

**Fresh clean installs:** `install.sh` installs the guard, postcheck, Stage18 and Hot Pool prior to enabling `ready-auto`; initial VPN service and profile can still be configured later. **Existing installs:** preserved until the operator explicitly enables this setting. On fixed/manual node policy, READY priority remains inert.

The candidate service gate is `balanced` only within the node-selector execution when READY priority is enabled and no stricter gate was explicitly selected. The running selection monitor's active-node health criteria are **not silently changed**; in particular a ChatGPT 403 cannot itself trigger a switch.

## Acceptance conditions

1. Offline tests and script syntax pass, and a live rollback backup exists.
2. Test Pi enables ready-auto while retaining existing Mihomo node, DIRECT underlay and SSH.
3. Hot Pool eventually has at least one double-confirmed READY node from the current live provider.
4. Controlled, independently recoverable **real failover** confirms READY-first, exact-profile matching, postcheck, return/rollback, and client-forwarded traffic.
5. Set up standby AWG and prove Mihomo exhaustion -> AWG without touching the router's priority SSTP management link. Confirm behavior after reboot.
6. Periodic provider refresh currently **stages changed subscription data** pending review, not an unattended live promotion; do not confuse the running timer with fully autonomous subscription replacement.

This feature's PR stays **draft** until live tests and upgrade/reboot acceptance are complete. Do not promote the branch to stable solely from static tests.
