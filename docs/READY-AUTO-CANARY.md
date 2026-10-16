# READY-priority AUTO canary (v1.3.0 — review only)

This is an opt-in prototype, **not enabled by installation**. This code is **not enabled by the installer**. The actual live AUTO selector remains unchanged. A manually initiated, supervised trial on 2026-10-16 temporarily switched the Mihomo node and rolled it back; MikroTik/SSTP were not altered.

## Safety contract

- `MIHOMO_READY_AUTO_CANARY=0` is the default; existing failover output and order are preserved.
- When set to `1`, a READY candidate from the continuity Hot Pool is considered before ordinary health-pool fallback.
- An archived/staged profile is **not** selectable just because it is READY. The exact node name must exist uniquely in the live provider and **all transport parameters (including credentials)** must equal the union provider entry.
- Existing isolated ChatGPT/OpenAI plus YouTube video service-scan remains required (`balanced` or `require` mode); no browser-level ChatGPT success is claimed.
- Post-activation checker must be configured and executable, otherwise canary refuses to act.
- Confirmed failed READY activation/post-check quarantines the shared endpoint (including aliases). A failed post-check attempts a return to the previous node. A failed rollback stops attempts and reports failure to the transport monitor so AWG/FAIL-CLOSED policies remain responsible. In this canary, even a **successful** rollback after a postcheck failure ends the attempt immediately, preventing repeated disruptive live switches. A whitelisted postcheck failure stage is logged on stderr without exposing credentials.
- Emit exactly `MIHOMO_NODE_FAILOVER=OLD->NEW` on stdout when successful; monitor depends on this exact contract.

## Read-only postcheck limitations

`awg-mihomo-ready-postcheck-tun` checks node identity, interface UP, table 100, marked route, public IPv4 egress using `curl --interface mihomo0`, and OpenAI API HTTP 401 (unauthorized, not region denial).

**This checks Pi-bound TUN traffic, not a LAN client's forwarded TUN dataplane.** A controlled real-client end-to-end canary, transport fallback and independent rollback are required before production enablement. It does not redo the 24-frame YouTube decode; isolated candidate service-scan provides that evidence. The historic HTTP-only YouTube precheck is not restored.

## Validation performed on Pi, 2026-10-16

- 11 isolated selector/identity tests PASS, including default-off behavior, READY priority, missing READY, changed credentials, activation failure, quarantine, postcheck failure, rollback failure and exact selection-monitor stdout.
- 6 mock route/TUN postcheck tests PASS; one real read-only run on current Mihomo node PASS for Pi-bound TUN and API HTTP 401.
- Pre-existing Hot Pool and provider-continuity tests passed separately.
- Live supervised canary: the first READY candidate failed fresh `balanced` network preflight (`OPENAI_API_NOT_CONFIRMED`) and was skipped. A second candidate (`hysteria2`) passed `balanced` network eligibility and exact-live profile matching, was temporarily activated, but failed immediate Pi-bound TUN postcheck (specific failure stage was not logged by the original version). The built-in rollback restored the original Mihomo node; full postcheck of the restored original passed. The failed endpoint was quarantined in Hot Pool. The remaining canary attempts were explicitly stopped, and the independent recovery timer was canceled after verifying health. The actual AUTO selector and MikroTik/SSTP were not replaced.
- Following this failure, the draft canary was strengthened to stop after a failed postcheck and completed rollback and to emit a whitelisted error reason. 22/22 isolated selector, TUN and monitor regression cases PASS. **The modified draft has not been re-trialed live**.

## Open acceptance gates

1. Validate service test before/after change and confirmed client-forwarded TUN path through a controlled LAN client.
2. Resolve the real canary postcheck failure (potential route-readiness, egress or OpenAI HTTP outcome); verify the new diagnostic before another live switch. Confirm client-forwarded TUN on a controlled LAN client. The primary rollback worked during the first real attempt, but real AWG fallback and shared-endpoint alias behavior remain untested in this trial.
3. Installer integration, unprivileged mocks on CI, reboot, migration and documentation review.
4. Merge dependencies (especially service-eligibility PR #106, Hot Pool PRs #108/#110 and safe periodic update PR #109).

Do not activate unattended AUTO based on this draft.

## Second supervised trial — 2026-10-16: root cause isolated

- Exact failure now confirmed as `READY_AUTO=POSTCHECK_FAILED REASON=ROUTE_MISSING`; automatic return to the prior Shadowsocks node succeeded, no additional node attempts occurred and AWG remained healthy.
- Mihomo process started at **18:13:38** (Novosibirsk, UTC+7). The independent Transit health monitor applied the route at **18:13:51**, **13 seconds later**. The original short postcheck exhausted all three attempts before the Transit route was available; **do not blame the tested transport or interpret this as an OpenAI failure**.
- New draft postcheck explicitly waits for the marked default route in table 100, with bounded retry (12 polls, 2-second interval, max 22 seconds of sleeps) before making any network request. Only then does it perform up to three strict public-egress + OpenAI API 401 checks. A 403 remains non-passing; node drift aborts immediately. All errors use allowlisted codes.
- 27/27 selector, TUN and monitor isolated regressions PASS; current live Shadowsocks node passed the revised read-only check on first route poll and network attempt. **The revised route-grace code has not yet passed a real failover trial at the time of this note**.

## Quarantine classification — third preflight, 2026-10-16

- Two endpoints had been quarantined by the earlier experimental canary under the undifferentiated reason `active-health-failed`. The second (`hysteria2-1827145588`) has an independently confirmed infrastructure-level `ROUTE_MISSING` failure, NOT a confirmed bad endpoint.
- Updated draft: infrastructure errors (`ROUTE_MISSING`, `MARK_MISMATCH`, `IF_DOWN`, node drift) never quarantine or cooldown the candidate. Bounded uncertain network or OpenAI response uses only a brief pool cooldown (180 seconds). Explicit invalid external IP remains quarantine-worthy. Actual activation failure still quarantines, subject to later review.
- Independent route-ready wait passes 11 fixture tests, including transient route recovery and expiry of the bounded deadline; full selector/TUN/selection-monitor suite passes **29/29**. No third disruptive live trial has been performed: the active shadow pool fell to one READY with two endpoints quarantined, so the safety precondition was not met.
- Live AUTO executable is unchanged. Production enabling and RC1 remain blocked pending a clean canary and forwarded LAN-client test.

## Verified quarantine correction (shadow only)

- Inspected the two shared endpoint quarantine entries without exporting credentials. `shadowsocks-1827146828` remained quarantined because its first live postcheck failure reason was not recorded precisely.
- The single `hysteria2-1827145588` quarantine from the **confirmed** second `ROUTE_MISSING` trial was backed up and removed under a paused Hot Pool timer. The timer was restarted. No READY service proofs were restored or fabricated: qualification requires two new PASS checks, 10+ minutes apart.
- One root-owned backup of the previous shadow state was retained on Pi in `/var/backups/awg-gateway/false-quarantine-route-20261016/`. The operational AUTO selector, live provider, routing and AWG were not changed by this correction.
- Full current Pi regressions: **74 Hot Pool + 18 continuity + 10 safe refresh + 29 READY/TUN/monitor = 131/131 PASS**. Production Mihomo `healthy`, Transit guard `SAFE`, standby AWG `healthy`.
- Acceptance gates remain: prove the revised route-aware postcheck with another guarded live canary when at least two freshly service-qualified READY candidates exist; test forwarded LAN-client TUN and true AWG failover. Do not merge/enable the draft meanwhile.

## Shadow follow-up, 2026-10-16 18:25 (+07)

- After the normal 1,677-profile live health-pool refresh ended, one Hot Pool `SHADOW_ONLY` cycle was run without live node selection. Result: `vless-1827156073` passed fresh OpenAI + 24-frame YouTube checks, while an additional VLESS candidate failed `connect_not_ready`. `HOT_POOL_READY=1` still: new/recovered nodes require two qualifying checks spaced at least 10 minutes, and no proof was fabricated.
- `HOT_POOL_QUARANTINED_ENDPOINTS=1` after correcting the demonstrably false route-race quarantine. The unrelated earlier quarantine remains in place pending natural expiry or additional evidence.
- Original production `awg-mihomo-node-policy` SHA unchanged; opt-in canary binaries refreshed to match the reviewed draft, **not attached to the running selector**.
- Final Pi gateway: Transit guard SAFE, Mihomo healthy on original Shadowsocks, AWG backup healthy, default table 100 via `mihomo0`, zero failed units. Emergency timer inactive.

## Guarded live acceptance — 2026-10-16 18:38–18:46 (+07)

### READY-priority AUTO — PASS on Pi

- Normal SHADOW_ONLY round recovered **2 READY** profiles; the top READY and second READY both matched the unique exact live-provider profile/credentials (no archived/staged-only activation).
- An independent root-owned recovery timer was armed (original node `shadowsocks-1827146201`) before triggering one opt-in canary; MikroTik and SSTP were not changed.
- Actual result: `READY_AUTO_POSTCHECK=PASS` and `MIHOMO_NODE_FAILOVER=shadowsocks-1827146201->shadowsocks-1827146133`.
- A separate post-activation `awg-mihomo-ready-postcheck-tun` returned `READY_TUN_CHECK=PASS` on the selected READY node, including marked table 100 and real TUN-bound HTTPS/OpenAI API 401, while Transit guard remained SAFE and standby AWG healthy.
- Restored `shadowsocks-1827146201` using production `awg-mihomo-configure node select-auto`. Original node passed independent TUN postcheck; backup AWG remained healthy. Canceled the recovery timer and removed the one-time recovery helper.
- An **8-second aggregate-only passive packet capture** found no usable forwarded LAN-client traffic. Accordingly **LAN-forwarded application reachability is NOT proven**; no packet content or user flows were collected.

### Real transport switch — PASS (manual AWG activation)

- A separate independent timed recovery was armed for the transition.
- `awg-transport select awg` succeeded with Transit preflight, fresh AWG handshake, DIRECT AWG endpoint, table 100 `default dev awg0`, `Transit guard: SAFE` and `Health state: up`.
- Independent HTTPS bound to `awg0` returned a public IPv4, and OpenAI API `/v1/models` returned HTTP 401. Thus real AWG dataplane and service network access were demonstrated on Pi.
- `awg-transport select mihomo` returned to original Mihomo node; activation recovery used the existing healthy node, TUN postcheck PASS, table 100 restored to `default dev mihomo0`, health up, Transit guard SAFE, zero failed systemd units. The timed recovery was canceled and temporary helper removed.
- **This is a manual transport activation/rollback test, NOT yet an automatic transport-selector failover caused by exhaustion of all Mihomo nodes.** The latter remains tested by mocks and earlier project history, not by this current canary.
- Running production `/usr/local/sbin/awg-mihomo-node-policy` was never replaced. The experimental canary and postcheck remain available separately, opt-in remains OFF.

### Remaining release gates

1. Run a real forwarded LAN-client service check via MikroTik → Pi → `mihomo0` and distinguish app service success from mere packet counters.
2. Verify full automated Mihomo-node exhaustion → AWG under controlled watchdog, without changing SSTP (or explicitly accept the existing historical test plus new mock).
3. Integrate opt-in components with safe installer/upgrade/uninstall and get a clean GitHub Actions CI result; reconcile stacked PRs #106/#108/#109/#110 before merging or creating RC1.

**Status:** READY-priority AUTO canary and manual AWG fallback are real-world PASS. Production enablement and RC1 remain blocked on the remaining acceptance gates above.

## One-shot automatic selection monitor integration — 2026-10-16 18:51 (+07)

- Recovery timer armed before test; original transport `mihomo`, original node `shadowsocks-1827146201`, AWG backup `healthy`, transport AUTO order `mihomo,awg`.
- Invoked **production** `awg-selection-monitor` once with **only this process** receiving an isolated, temporary mock `check mihomo = FAIL` and `Mihomo node failover = unavailable`; provider, transport daemons, existing node policy and persistent selector state were untouched.
- The first harness attempt from `/run/awg-pbr` failed `Permission denied` when trying to invoke its temporary command wrapper and **did not switch** the transport. It is **not** a successful test. Re-ran from an executable, isolated temporary directory with an assertion of the actual post-state.
- **PASS:** `REAL_AWG_SELECT_INVOCATION=YES`, `FAILOVER=mihomo->awg`, `ACTUAL_TRANSPORT=awg`, `TEST=REAL_MONITOR_FALLBACK_PASS`. The real transport selected AWG, table 100 became `default dev awg0`, Transit guard SAFE, health up.
- Restored original Mihomo using production `awg-transport select mihomo`; original node unchanged and TUN postcheck PASS, AWG backup healthy, table 100 `default dev mihomo0`, Transit guard SAFE, no failed systemd units. Canceled independent one-shot watchdog and removed recovery helper.
- **Scope qualifier:** selector behavior and real AWG activation are proven with an *injected* synthetic failure result. Genuine exhaustion of all subscribed Mihomo nodes was NOT created; no working server was blocked. SSTP/MikroTik untouched. The mock wrapper was not committed to installable production scripts.
- Remaining release gate: one real end-to-end **LAN-forwarded client application test**, plus green CI/install-upgrade review and integration of stacked dependencies. Do not enable canary by default or tag RC1 before those checks.

## iPhone LAN spot-check — 2026-10-16 19:13–19:16 (+07)

- Device reported DHCP IPv4 `192.168.112.21`. Passive captures of direct `192.168.112.21` ingress to Pi (`eth0`) observed **zero** packets in a 20-second interval.
- However, a passive 15-second sample captured **118** Internet-bound packets from the actual MikroTik source MAC, all with source IP `192.168.112.1`, consistent with MikroTik performing source NAT *before* forwarding to Pi. No packet content was retained. Thus the client's source IP may be hidden on Pi.
- A later simultaneous 12-second sample counted **98** Internet-bound packets from router MAC on `eth0` and **100** outbound IPv4 packets on `mihomo0`, while marked forwarding of source `192.168.112.1` resolved to table 100 / `mihomo0`. Gateway Mihomo healthy, Transit guard SAFE.
- **Interpretation:** actual router→Pi→Mihomo aggregate traffic is observed; it is NOT yet provably attributable to this iPhone because source NAT collapses client addresses. Safari showing router's public IP may be a separate DIRECT route for that domain, or another path. Remains to inspect MikroTik connection tracking/routing policy for the exact iPhone source IP during a simultaneous client request.
- No MikroTik, SSTP, policy, or Pi production configurations were modified.

## iPhone forwarded LAN service path — PASS (2026-10-16 ~19:10–19:20 +07)

- Client IPv4 `192.168.112.21`; router conntrack recorded **7** active source connections with SRCNAT. Reply-destination after NAT was **192.168.112.1** (router bridge LAN), explaining why Pi receives packets from the router IP rather than the iPhone IP.
- Active `r_to_vpn` default next hop was **192.168.112.34** (Pi); separate SSTP route was **disabled**. The installed `DNSAUTO-TO-VPN` prerouting mangle rule matches destinations in address-list `to_vpn_auto`, with per-client connections reporting `orig-fasttrack-packets=0` and `repl-fasttrack-packets=0`. The MikroTik srcnat masquerade rule covers outgoing interfaces, including the Pi LAN next-hop.
- iPhone ChatGPT connections in RouterOS conntrack included `104.18.39.85` (DNS address-list comment `ios.chat.openai.com.cdn.cloudflare.net`), `104.18.39.21` (`ws.chatgpt.com`), and `104.18.32.47` (`chatgpt.com`). Each destination existed in `to_vpn_auto` and the matching conntrack entries showed two-way traffic and reply destination `192.168.112.1`.
- iPhone's UDP 443 connection to `185.225.248.176` delivered about **2.9 MB** of reply data; destination present in `to_vpn_auto` with `rr5.sn-x2pm-f5fr.googlevideo.com` DNS comment. End user confirmed YouTube video playback and ChatGPT access on the phone.
- Pi independently observed a 12-second simultaneous sample of **98** Internet-bound router-source packets entering eth0 and **100** outbound packets on mihomo0. This is supporting *aggregate* evidence, not flow-level one-to-one correlation; client attribution is established from **MikroTik conntrack + NAT + destination list + active Pi next-hop**.
- The iPhone's direct public-IP test may still display the router public IP as selective policy does not necessarily include `api.ipify.org`. This is not a DNS leak or a failed service route.
- **Conclusion:** practical forwarded LAN client path for ChatGPT and YouTube through MikroTik → Raspberry Pi (Transit) → Mihomo is verified; end-to-end service use also reported by the user. No router, SSTP, Pi production or client network settings changed during this evidence gathering.

### Remaining gates after LAN verification

- READY→AUTO real supervised transition, Pi-bound route-aware postcheck and rollback: PASS.
- Manual Mihomo→AWG→Mihomo and selector-driven actual AWG activation with injected Mihomo failure: PASS (not a naturally occurring provider-wide failure).
- **Outstanding:** GitHub Actions CI result; installer/upgrade/uninstall integration of optional binaries, stacked PR dependencies and clean review before RC1. Keep `MIHOMO_READY_AUTO_CANARY=0` by default and PR draft until these pass.
