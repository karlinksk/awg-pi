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

**Fresh clean installs:** \`install.sh\` installs both VPN engines, all READY guards, Hot Pool/Stage18, and media dependencies **before any VPN profile or subscription is provided**. It does **not** run the first-transport wizard or prompt for Mihomo provider URLs/AWG profiles. It finishes in \`Selective + transport=unconfigured\`; no VPN traffic or Transit mode is activated. READY priority and Hot Pool SHADOW timer are **armed but passive** while there is no subscription. Ordinary pool-refresh and update timers are independent. After successful installation, use \`sudo awg-menu\` to enter an AWG .conf or Mihomo subscription, select a node, choose AUTO or FIXED, and, if desired, explicitly disable Hot Pool via the AUTO strategy option **before** switching to FIXED. No installer rerun is needed. Do not assume that selecting FIXED alone automatically disables the independent Hot Pool timer.

**Existing-install upgrades:** installer preserves exact FIXED node order (or AUTO/MANUAL), READY mode, independent service-eligibility mode, plus Hot Pool timer enabled and running states; mismatch causes a failed upgrade instead of silent policy reset. The `awg-update` backup/rollback includes both the configured files and timer state. A FIXED chain only advances left-to-right after a repeated active-Mihomo failure, and it does not imply YouTube/OpenAI testing when the independent service gate is `off`.

Use **VPN routing → Mihomo → Mihomo node failover → AUTO strategy: Hot Pool / ordinary** in the menu to switch between the two AUTO strategies (only when the node policy itself is AUTO). The menu asks for confirmation and the CLI rolls back timer/priority state on systemd error:

```bash
sudo awg-mihomo-node-policy auto-strategy status
sudo awg-mihomo-node-policy auto-strategy classic  # stop + disable Hot Pool timer, READY=0
sudo awg-mihomo-node-policy auto-strategy ready    # start + enable Hot Pool timer, READY=1
```

Switching does not change the selected node, transport, independent DNS or routes; changing FIXED/MANUAL to AUTO requires a separate explicit node-policy choice. The selector is not a replacement for real Pi TUN, LAN, failover or reboot release tests. **The actual install/upgrade hardware gates remain pending** despite passing isolated installer policy tests.

The candidate service gate is `balanced` only within the node-selector execution when READY priority is enabled and no stricter gate was explicitly selected. The running selection monitor's active-node health criteria are **not silently changed**; in particular a ChatGPT 403 cannot itself trigger a switch.

## Acceptance conditions

1. Offline tests and script syntax pass, and a live rollback backup exists.
2. Test Pi enables ready-auto while retaining existing Mihomo node, DIRECT underlay and SSH.
3. Hot Pool eventually has at least one double-confirmed READY node from the current live provider.
4. Controlled, independently recoverable **real failover** confirms READY-first, exact-profile matching, postcheck, return/rollback, and client-forwarded traffic.
5. Set up standby AWG and prove Mihomo exhaustion -> AWG without touching the router's priority SSTP management link. Confirm behavior after reboot.
6. Periodic provider refresh currently **stages changed subscription data** pending review, not an unattended live promotion; do not confuse the running timer with fully autonomous subscription replacement.

This feature's PR stays **draft** until live tests and upgrade/reboot acceptance are complete. Do not promote the branch to stable solely from static tests.

## Installer acceptance: actual TUN is separate from local proxy health

`awg-transport check mihomo` and the currently running transport health monitor check the **local Mihomo proxy** and API. A positive result is **not** proof that the current node can carry real IPv4 HTTPS through `mihomo0`. For the selected node use:

```bash
sudo awg-mihomo-tun-check
```

The command is installed by `install.sh`, makes no network configuration changes, and invokes the existing guarded `awg-mihomo-ready-postcheck-tun`: check table 100 and fwmark `0x100`, then public IPv4 HTTPS egress and OpenAI API through the bound TUN interface. The HTTPS probes explicitly ignore curlrc and inherited HTTP proxies. `MIHOMO_TUN_CHECK=PASS` confirms **Pi-bound TUN only**; the user must still prove **LAN-client forwarding** separately. It is correct for `awg-transport check mihomo` to succeed while this probe fails.

For a newly configured active Mihomo transport, the installer performs the TUN acceptance check as a **warning-only** step after the selection monitor starts. This must not prevent fresh installation or rollback the network just because a provider or site is unavailable. An operator can rerun the command after selecting a different node. This distinction should be maintained in future status/TUI and health policies: `proxy healthy`, `Pi TUN PASS` and `LAN client PASS` are three different findings.

### DNS/Selective/Transit and October 17 live findings

In Selective, Raspberry Pi's `dnsmasq` answers client queries **when the client uses Pi DNS** and populates `nftset` with real IPv4 destinations, but does **not** feed an IP-to-name cache to Mihomo. The Pi OS itself may use MikroTik DNS; check each resolver path independently. In Transit, DNS may be handled on MikroTik/DoH and may not be visible to Pi. **Do not** silently move DNS into the VPN, turn on Fake-IP/DNS hijacking or enable TLS SNI sniffing by default as a speculative workaround.

On the TEST Pi, active `shadowsocks-1827968609` successfully proxied domain-based HTTPS but failed numeric-IP CONNECT and real TUN TLS. Reserve `shadowsocks-1827145438` passed numeric-IP HTTPS **with and without SNI sniffing**, then passed both an independently guarded real `mihomo0` postcheck and Google HTTP 204; the original node was restored. No DNS/sniffing changes were needed. A subsequent one-off script's exact route comparison failed transiently just after restoration; later inspection confirmed `fwmark 0x100 → table 100 → mihomo0`. Use bounded recovery polling and route-semantic checks, not whitespace-sensitive string equality, for further canaries.

Hot Pool's service `READY` currently qualifies hostname-based OpenAI/ChatGPT/decoded YouTube, **not** numeric-IP or TUN suitability. The separate `awg-mihomo-smart service-scan` requires numeric-IP HTTPS on candidates, and real node activation has a mandatory bound TUN postcheck. Do not confuse these levels of eligibility or reintroduce the rejected legacy YouTube HTTP prefilter. **Unattended failover, routed LAN client and healthy AWG fallback are still not accepted**; this PR remains draft.
