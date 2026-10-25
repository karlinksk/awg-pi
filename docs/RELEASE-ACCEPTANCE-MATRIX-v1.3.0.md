# AWG Pi Gateway v1.3.0 — complete release acceptance matrix

**Status: GATE OPEN / NOT RELEASE-READY** (reconciliation 2026-10-26, draft PR #165; #115 closed/superseded).

## Current release ledger — supersedes the historical checklist below

Apply the owner-directed 2026-10-24 contract in `TESTING-v1.3.0.md` and the
latest entries in `PROJECT_STATE.md`. The old 150-case list is retained as
historical audit detail, not 150 new mandatory experiments. Hot Pool, READY,
editable FIXED chains, ChatGPT/OpenAI availability, YouTube and 24-frame decode
are excluded release gates. MANUAL uses local eligibility; AUTO uses native
engine network assessment, never individual service eligibility.

| Required area | Evidence and exact scope | Current disposition |
| --- | --- | --- |
| Current HEAD CI | Installed runtime base `443bfa5` remains historically tested. Repair source `f00c93e` has complete runs 40221601725 / 40221605679 SUCCESS (shell + awg-v31), plus 7/7 boot regression, 31/31 AUTO, 5/5 policy and original selector suite. Subsequent documentation HEAD requires its own CI. | Runtime and repair-source CI PASS in stated scope; recheck docs HEAD |
| Installed source / delivery | Fresh read-only privileged audit of all 75 literal installer helper/unit deliveries against `5466a73`: 75 byte matches, all root-owned; helpers 0755, common library/units 0644. Eight network helpers and accepted numeric menu also match exact Git blobs. Test-only repair changes none of these files. | PASS for audited delivery set; not an installer execution |
| Transit IPv4 LAN | Windows Mihomo correlated ingress/TUN/return; installed dynamic-MSS AWG 22/22 HTTP200, outgoing MSS1380, zero target-bound direct egress. | Existing bounded hardware PASS credited |
| Transit FAIL-CLOSED | Both backends stopped under recovery: 26 target ingress, zero matching direct egress/VPN traffic; six contained client attempts timed out; baseline recovered. | Existing target-scoped IPv4 negative PASS credited; no all-path/IPv6 claim |
| Selective FAIL-OPEN/re-arm | Real iPhone Mihomo and AWG forwarding, backend-down DIRECT, restored VPN forwarding, independent recovery. | Existing bounded hardware PASS credited |
| Manual/AUTO recovery | Guarded Mihomo/AWG switching; endpoint failure to later native; native/Xray/native; old-card 13-profile exhaustion to sticky AWG. Preserve dated revision/provider scope in PROJECT_STATE. | Existing scoped PASS credited; no repeated pool/outage trials |
| Clean install / onboarding | Actual fresh Debian13.7 ARM64 installation pinned to `443bfa5`, 75/75 delivered bytes/owners/modes match. Owner subsequently imported AWG and Mihomo profiles; both validate, both independent Pi-bound HTTPS requests HTTP200/curl0, Selective/AWG healthy, DNS/SSH active, failed units0. | Exact-candidate clean install and new-card Pi-TUN onboarding PASS; not a new forwarded LAN proof |
| Upgrade / gateway restore / reboot | Earlier actual `07d8e0d` preserving upgrade/snapshot restore remains scoped evidence (installer/updater unchanged). Exact `443bfa5` empty-state reboot15/15 and configured reboot18/18 private entries,75/75 deliveries. Configured boot independently checked by root timer: HEALTHY_NO_RESTORE, controls/routes/DNS healthy; both Pi TUN HTTPS200 after boot, AWG remains selected, temporary units removed. | Exact-candidate empty and configured reboot PASS; earlier upgrade/actual snapshot-restore scope remains explicit |
| Full-media recovery | Owner-approved same test card restored from private cold image and booted. Full read-back differed by two Windows FAT access-date bytes only; Linux partition exact. First as-captured acceptance failed (AUTO AWG->Mihomo); fixed monitor `f00c93e` survived a separate actual reboot with AWG stable. | PARTIAL / GATE OPEN: physical boot proven; no as-captured acceptance PASS or reimaged post-fix release snapshot |
| Promotion | PR targets integration branch, not main. Inspect integration/release path and final checks before any merge/tag/release. | Draft, unmerged, unreleased |

### 2026-10-26 — actual full-media card restore and subsequent boot repair (scope-separated)

1. **Card integrity and boot:** image restored to the owner-approved same test card. Full read-only comparison of 31,927,042,048 bytes differed at precisely two FAT directory *last-access date* bytes (Windows metadata); root filesystem and all other bytes matched. Imager exit 0 is not whole-card bitwise SHA equality. Restored Debian 13 and DC remote execution actually booted; image remains private. **Physical restore/boot observed; bit-exact digest gate false.**
2. **Unmodified as-captured restored runtime:** first boot's root acceptance checker ran and **failed** (`19/20` state entries; `75/75` delivered files; `11/11` enabled states). AUTO switched AWG to Mihomo at boot +61 seconds, before the +90 second acceptance. Transit stayed `SAFE/ACTIVE/READY`; do not upgrade failed image acceptance to PASS. NTP jumped wall-clock at +37 seconds; handshake-age misclassification is plausible but not proven from a cycle-level trace.
3. **Corrected candidate and narrowly scoped actual reboot:** `f00c93e` protects at most the first 120 monotonic seconds against AWG handshake false negatives while service and interface are present; real service/link failures retain AUTO fallback. Installed exactly on the approved test Pi with guarded rollback and independent management/routing checks. Regression 7/7, AUTO 31/31, installer-policy 5/5 and original selector shell test PASS. Both GitHub runs `40221601725` / `40221605679` are complete success (`shell`, `awg-v31`). Second boot ID `0a85e146...` retained healthy AWG beyond 200 seconds and later, zero automatic switches and failed units, Transit `SAFE/ACTIVE/READY`, SSH/DC/DNS healthy. This tests **post-fix boot**, not a newly flashed `f00c93e` image.
4. **Operator change and handback:** `xray-auto.mode` was **manually enabled by the owner** after image capture and preserved as `MIHOMO_XRAY_AUTO=enabled`. The one original delivery difference after patch was the deliberately replaced selection monitor. Old root acceptance failed; exact temporary units were retired, receipts retained. Telegram sender reported first boot 2 and second boot 1 notifications, pending 0, without owner-side receipt attestation; no external SSTP/eth0 delivery claim.
5. **Gate:** `Full-media recovery = PARTIAL / NOT ACCEPTED for unmodified candidate`. Credit physical boot and repaired-AUTO reboot separately. Other previously accepted scope-limited LAN/Selective/Transit/failover and configured clean-install gates remain credited; do not retest simply to close historical boxes. New docs HEAD requires **its own CI** and final release review. PR #165 is draft/unmerged/unreleased; no release tag or production installation.

Pre-swap receipt reconciliation also confirmed actual reboot boot-ID change,
`BOOT_RESCUE=HEALTHY_NO_RESTORE`, 13 policy matches and removed temporary units;
the restore receipt records 13 policies, bound HTTP200 and guard SAFE. These
are historical results. Today's comparison to that archived private baseline
is **12/13**, with `provider.env` changed (both versions present); cause not
established. Do not restore old provider state or claim current 13/13 equality.
At that pre-swap checkpoint native Mihomo and standby AWG were healthy, DNS resolved, controls were
active, Transit SAFE/ACTIVE/READY, failed units0 and no rescue/recovery timer
listed. Read-only storage inventory shows only the boot microSD, loop and
zram; no spare restore target is attached. No live gateway or media changes
were made during that audit.

After the owner swapped media, the hardware CID and root UUID matched the
original-card guard recorded on24 Oct. Installation was paused; owner explicitly
confirmed this card may be used and working media is retained separately.
Do not describe it as a newly identified third physical card or an image restore.
Owner executed the verified pinned installer; independent postflight confirmed
Debian13.7 ARM64, empty profiles and75/75 delivery. A standard gateway backup
of124028899 bytes was created, copied off Pi to a private workstation directory
and SHA256 matched (`caa6138ac6c0c6763404b5f16591dab73b55176e7bb9461ed166f76c22f5701a`).
This is an archive-integrity/copy PASS, not actual snapshot or full-media restore.
Actual reboot at22:55 +07 succeeded; privileged postboot comparison confirmed
15/15 baseline entries and75/75 deliveries. Node22/WebSocket recovered, pinned
Stage18 disk-cache hashes matched. Stage18 RAM runtime is absent as expected
before subscription import (provider ConditionPathExists); no media test ran.
No network failure injection, MikroTik or working-media change was performed.

Configured follow-up: owner imported profiles through normal onboarding. AWG
was selected, both transports locally healthy, tables100/101 viaawg0, both
bound example.com HTTPS requests returned200/curl0. A configured standard
backup124037544 bytes was verified, safe archive member paths checked and
privately copied off-device with matching SHA256
`6e4575a1dd3c6af3c471ff6a91d6306ee60efccefba919a6913ce5c5b3e42b86`.
Root-only baseline18 entries and75 delivery hashes protected the next boot;
independent5-second timer rehearsal returned success on unchanged healthy
state. A fixed root-owned120-second boot recovery used the exact tracked
updater restore function as fallback; it actually ran after reboot and reported
HEALTHY_NO_RESTORE,18/18 settings,75/75 deliveries, active controls, AWG routes,
DNS and no failed units. Boot changeda3f377af→c31862ed at23:16:34 +07.
Both bound HTTPS checks again returned200/curl0. Temporary recovery service
and timer were removed only after success; independent SSH confirmed absence.
No actual restore occurred in this new trial, no profile values were printed,
and no broad outage, forced switch or new client/media acceptance was claimed.

Owner then requested DC, Telegram and Transit before the whole-media image.
Pinned DC0.2.52 cache was prepared with offline startup resolution; owner
completed OAuth as ordinary user. Pairing foreground job was identified exactly
and ended with SIGINT, then the persistent nonroot karlinks service was enabled.
Separate connected-DC command execution succeeded after service handover.
Owner configured Telegram privately; test delivery returned sent1/pending0 via
awg0 before and after Transit. Flush/watch/daily timers and boot notification
enabled according to existing preferences; next daily09:00 Asia/Novosibirsk.
Router/SSTP fallback attestation remains absent; no eth0 fallback was enabled.

Transit preflight passed. Standard pre-transition backup124033091 bytes was
privately copied off-device with matching SHA256
`5566db4ea57f80e1f2fa9e0ebf39d285b4fa22115f6a6347d033fcfe3a48e6aa`.
Independent5s timer exercised the fixed standard return to already-selected
Selective harmlessly;19/19 protected settings and all controls remained healthy.
Then300s rescue armed and standard mode transition ran in an independent unit,
exit0. Postcheck: Transit SAFE/ACTIVE/READY,19/19 non-mode invariants unchanged,
activeAWG, both bound HTTPS200/curl0, SSH/DNS/DC healthy, actual DC execution
and Telegram test succeeded, failed units0. Rescue was stopped only afterward;
no test timer remained. MikroTik unchanged. This is configured Transit activation,
not a repeated outage, new LAN-client proof or full-media restore acceptance.

Reopen hardware only for a concrete uncovered required behavior or a material
network-code change. A stale unchecked box is not a reason to repeat a fault
trial. Safe read-only reconciliation does not authorize a new reboot, installer
run or media write without verified independent recovery and protected controls.

## Historical 2026-10-17 checklist (superseded where inconsistent)

The unmarked boxes preserve their original evidence status; they do not erase
the later scoped acceptance above. Older blockers and plans below are dated
history, not the current release queue.

## Acceptance rules and evidence

- Preserve MikroTik SSTP management; do not modify production Pi. Back up test media, configuration, router policy and rollback state before disruptive tests. Keep old SD read-only; use one designated LAN client and independent timed recovery for risky tests.
- Record for each case: candidate commit SHA, Raspberry Pi hostname/OS, gateway mode, selected transport and node, transport/node policies, command and sanitized result, WAN egress/proxy/TUN and client evidence as applicable, state before/after, and rollback result.
- Distinguish service/API **proxy PASS**, **Pi-bound TUN HTTPS PASS**, **actual LAN-client forwarding PASS**, and **end-to-end application PASS**. They are not interchangeable.
- Passing criteria: Selective FAIL-OPEN; Transit FAIL-CLOSED with source/MAC guard; management/control endpoints DIRECT; sticky healthy transport/node; no unexpected switches; correct fallback; no credential disclosure; ability to restore previous installation.
- The two mandatory gateway modes and both actual transports are a **4-cell network matrix**; test both directions of mode and transport switching, not merely four static statuses. Invalid/unconfigured and degraded combinations require independent negative tests.

## A. Revision, safety and CI (A01–A12)

- [ ] A01. Freeze one exact v1.3.0 candidate commit/ref and install/test from that same ref; reject a moving default release URL.
- [ ] A02. GitHub Actions `shell` and `awg-v31` succeed **on candidate HEAD**; do not reuse an older commit's success.
- [ ] A03. Bash syntax, ShellCheck errors, Python AST/compile and systemd unit verification cover **all installed scripts and service units**, including DC, Node, Stage18, READY and continuity.
- [ ] A04. CI executes all shipped applicable regression files, including the 16 current test files not referenced in `.github/workflows/ci.yml`; confirm names/results and absence of fixture-only passes.
- [ ] A05. Build pinned AmneziaWG v3.1 tools/core; run isolated real-profile preflight and mismatch/missing-dependency checks.
- [ ] A06. Detect required external tools and Debian 13 ARM64 packages/versions (Go, nft, dnsmasq with nftset, ffmpeg/ffprobe, curl, jq, iproute2, Python, XZ and runtime dependencies).
- [ ] A07. No shared `NOPASSWD:ALL`; root/private data remains protected, and logs/status never display private key, UUID, subscription token, Reality key or user HWID.
- [ ] A08. Confirm SSH access from LAN and SSTP management path BEFORE/DURING/AFTER each disruptive test; no changes to cloud MikroTik or production router-wide routing.
- [ ] A09. Independent timed recovery and saved current state are ready before activating any experimental node, changing gateway mode or disrupting a transport.
- [ ] A10. Every confirmed fix is committed to authoritative source, fresh installer, upgrade/rollback path, regression tests and docs; verify commit includes it.
- [ ] A11. Review open dependency PRs #106, #108, #109, #110 and #111; reconcile merge order and behavior, with no stale file/overwrite of independently managed services.
- [ ] A12. Confirm a fresh install sets **READY OFF** (`ready-auto.mode=0`) and Hot Pool timer **disabled/inactive**, even when no subscription exists. Stage18 and base pool-refresh may remain provider-guarded; upgrades preserve pre-existing READY/timer preferences.

## B. Fresh installation, provisioning and onboarding (B01–B16)

- [ ] B01. Destructive fresh Debian 13 ARM64 install on separate boot media; retain original SD for verified restoration.
- [ ] B02. Preflight CPU architecture, Debian version, IPv4 interface/router/static IP/DHCP conflict, connected route and sufficient disk/free RAM; reject unsupported IPv6-default architecture safely. Confirm **fresh** installer sets `Asia/Novosibirsk` after installing `tzdata`, accepts an explicit alternative IANA timezone, rejects invalid zones, and **upgrades preserve** the existing zone.
- [ ] B03. Fresh installer builds AWG and installs verified Mihomo engine even when no subscription/profile supplied.
- [ ] B04. **After installer completion**, import AWG from an operator-provided config file via `awg-menu`; validate format, protected permissions, endpoint DIRECT, handshake and HTTPS. The clean installer must not require or import AWG credentials.
- [ ] B05. **After installer completion**, import a pasted AWG config via `awg-menu`; protect input and rollback an invalid profile without overwriting a good one.
- [ ] B06. **After installer completion**, configure Mihomo with a subscription URL via `awg-menu`; select and preflight an exact node, with no implicit change of gateway operating mode.
- [ ] B07. **After installer completion**, configure Mihomo from a local provider file or pasted subscription; verify local input itself requires no remote subscription fetch.
- [ ] B08. With **no profiles at all during installation**, finish in `Selective + unconfigured`, Xray OFF, READY OFF and Hot Pool timer DISABLED/INACTIVE. Verify all engines/media dependencies installed, SSH/DNS/menu safe, no AWG start without config, and no subscription-backed scan/selector thrashing.
- [ ] B09. Safely resume an interrupted, unversioned first installation **without profiles**, distinguish it from a real upgrade, and still finish `Selective + unconfigured` without forcing a first-transport wizard.
- [ ] B10. Verify the operator can configure the first transport **and then optionally change Selective/Transit and opt in to Hot Pool/READY through `awg-menu` after installation**. Neither a VPN profile, Transit nor Hot Pool/READY is activated during clean install.
- [ ] B11. Wrong/cancelled/no-TTY input does not silently select arbitrary transport, alter router or corrupt private state.
- [ ] B12. All deployed scripts, systemd units, their executable/ownership permissions and service enablement match the tracked candidate commit.
- [ ] B13. System-wide `node` resolves to pinned SHA256-verified v22.16.0, global `WebSocket` exists; Debian APT-owned `/usr/bin/node` remains intact.
- [ ] B14. No unexpected overwrite of preexisting unmanaged `/usr/local/bin/node`; APT updates and npm continue to work.
- [ ] B15. Correct Stage18 pinned Node/yt-dlp and 24-frame decoder prefetch/boot cache; no source/network dependency when restoring validated cache after reboot.
- [ ] B16. Installer's warning-only TUN probe distinguishes unproven route/provider from fatal installer errors; a bad subscription cannot wipe recoverable management.

## C. Four gateway-mode/transport dataplanes (C01–C16)

- [ ] C01. Selective + AWG: marked VPN destinations reach `awg0`; unrelated traffic goes DIRECT via MikroTik.
- [ ] C02. Selective + Mihomo: marked VPN destinations reach `mihomo0`; unrelated traffic stays DIRECT.
- [ ] C03. Transit + AWG: one MikroTik-routed LAN client uses Pi→`awg0` and real external HTTPS.
- [ ] C04. Transit + Mihomo: one MikroTik-routed LAN client uses Pi→`mihomo0` and real YouTube + ChatGPT.
- [ ] C05. Selective `vpn off` removes VPN policy; `vpn on` restores only correctly classified traffic.
- [ ] C06. In Selective, client allow-list empty/one/many behaves correctly; no wildcard leak to excluded devices.
- [ ] C07. In Selective, VPN domains/OpenCCK IP sets and explicit DIRECT exceptions have verified precedence for overlapping destinations.
- [ ] C08. Selective VPN outage removes `fwmark 0x100` policy and actual client internet returns via direct route (FAIL-OPEN).
- [ ] C09. Transit VPN outage removes active forwarding policy but leaves MAC-restricted `nftables` guard: no direct egress, no leak (FAIL-CLOSED).
- [ ] C10. Transit guard SAFE, table 100 default active TUN and `fwmark 0x100` rule only when backend is healthy; broken backend yields LOCKDOWN/safe guarded state.
- [ ] C11. Table 101/`fwmark 0x101` health probes use selected backend without routing management/control traffic into the VPN.
- [ ] C12. Pi main default route, transport endpoints, provisioning/control downloads and management SSH stay DIRECT through correct LAN gateway.
- [ ] C13. Router MAC matching: only actual MikroTik-sourced Transit traffic may forward; unsolicited LAN/direct spoof attempts blocked.
- [ ] C14. Transit source-NAT on MikroTik may hide client source IP; prove client attribution via concurrent MikroTik conntrack, address list, selected Pi next hop and Pi ingress/TUN counters.
- [ ] C15. Transit allows only operator-selected client/prefix; unselected LAN clients retain original routing; SSTP management unaffected.
- [ ] C16. IPv6 remains unsupported; no accidental IPv6 bypass, RA/default route ambiguity or unintended IPv6 gateway path.

## D. Gateway mode switching (D01–D08)

- [ ] D01. Selective→Transit while AWG selected and healthy: preflight, nftables, source MAC, forwarding, table 100, rollback.
- [ ] D02. Transit→Selective while AWG selected: rules rebuild, verified DNS/classification, management and direct route preservation.
- [ ] D03. Selective→Transit while Mihomo selected and healthy: verified marked TUN traffic/guard and client forwarding.
- [ ] D04. Transit→Selective while Mihomo selected: correct domain/client classification and DIRECT exceptions.
- [ ] D05. Selective→Transit with `unconfigured`: explicit LOCKDOWN, SSH available, no traffic leak.
- [ ] D06. Transit→Selective with `unconfigured` or down VPN: safe DIRECT, correct later recovery behavior.
- [ ] D07. Mode switch interrupted by unhealthy transport/preflight/systemd/nft/ip-rule errors: original mode and policies restored; no management loss.
- [ ] D08. Repeating active mode command, concurrent health/selector/installer, multiple restarts and reboot does not change selected mode unexpectedly.

## E. AWG profile, version and health (E01–E12)

- [ ] E01. On current test Pi configure an operator-approved `awg0.conf` (AWG has NOT yet been connected here), with protected backup and keys `0600`.
- [ ] E02. AWG engine version/build and native v3.1 profile fields are accepted; incompatible/plain WireGuard variants handled according to documented support.
- [ ] E03. `awg0` starts/stops/restarts and has fresh handshake under correct endpoint IPv4 route.
- [ ] E04. AWG egress IPv4 HTTP(S), OpenAI API and test site HTTPS work through interface; not merely ICMP or handshake.
- [ ] E05. AWG may block ICMP to 9.9.9.9/1.1.1.1; verified HTTPS fallback plus fresh handshake still yields healthy.
- [ ] E06. Missing/stale handshake, invalid key, DNS failure, unreachable endpoint and tunnel-up/no-data produce safe unhealthy results.
- [ ] E07. AWG endpoint stays DIRECT even when Mihomo is active, Transit selected, SSTP present, or source IP changes.
- [ ] E08. AWG `config check/replace/rollback`: atomic install, invalid profile rejected, old working config restored.
- [ ] E09. AWG is healthy standby for Mihomo; backend can start from stopped standby during failover.
- [ ] E10. Selected AWG survives reboot; `awg-quick@awg0`, `awg-pbr-health`, policy routes and handshake recover.
- [ ] E11. AWG premium/geo-restricted endpoint (when supplied) proves actual ChatGPT/YouTube service availability independently of location label; no claim based on handshake alone.
- [ ] E12. AWG recovery after a deliberately terminated backend never leaks Transit traffic or causes unrequested return from healthy Mihomo.

## F. Mihomo engine, node protocols, TUN and health (F01–F16)

- [ ] F01. Pinned ARM64 Mihomo binary integrity, service sandbox and config validation (`mihomo -t`) pass.
- [ ] F02. TUN `mihomo0` UP, host default route remains DIRECT; Mihomo `auto-route` and `auto-redirect` stay disabled as specified.
- [ ] F03. TUN via `curl -q -4 --noproxy '*'` and bound interface reaches public IP and HTTPS/OpenAI; inherited HTTP proxy is excluded.
- [ ] F04. Distinguish local 127.0.0.1:7890 proxy/API healthy from actual numeric-IP / TUN TLS failure, and from forwarded LAN client success.
- [ ] F05. Update active-node transport health/selection to detect confirmed sustained TUN failure without false positives, excessive probes or Cloudflare 403 misclassification.
- [ ] F06. Node IPv4 endpoint and related DNS resolution stay DIRECT to router, not via SSTP or own TUN.
- [ ] F07. Live nodes activated individually for VLESS, Trojan, Hysteria2, Shadowsocks and VMess, using at least one working node per protocol.
- [ ] F08. Per-protocol filtering, pool health/cooldown, protocol=all cross-protocol AUTO, and failed-node/quarantine handling.
- [ ] F09. MANUAL node selection respects exact chosen name and is stable when faster/READY alternatives exist.
- [ ] F10. FIXED exact node chain advances strictly forward, never wraps to earlier node or infers country; skips failed candidates.
- [ ] F11. AUTO node policy selects qualified live candidates, supports cross-protocol changes, and never changes healthy active node for speed.
- [ ] F12. Node/API/provider removal, duplicated/renamed name, changed server/credentials or stale cache cannot activate archived READY profile.
- [ ] F13. Failure during node write, backend restart, transport preflight or postcheck restores original node/config/provider and correctly re-enables health.
- [ ] F14. Async `fwmark 0x100`/table 100 recovery after Mihomo restart has bounded semantic checks; route/mark failures do not falsely quarantine good nodes.
- [ ] F15. OpenAI/ChatGPT/YouTube service checks distinguish PASS, FAIL, UNKNOWN, 401 expected unauthenticated API, 403 challenge, bot/network denial and real video decode.
- [ ] F16. Failed direct IP HTTPS, DNS-only service success, fake HTTP proxy success and TLS EOF are negative cases; do not promote to READY or TUN healthy.

## G. Transport selection and exhaustive failover (G01–G16)

- [ ] G01. MANUAL transport: AWG healthy stays AWG, Mihomo healthy stays Mihomo; no automatic transport switch.
- [ ] G02. MANUAL transport still permits Mihomo **node** AUTO/FIXED if explicitly configured; isolate the two policy levels.
- [ ] G03. FIXED `awg,mihomo`: AWG repeated failure→start healthy Mihomo standby→Mihomo; no switch for one transient failure.
- [ ] G04. FIXED `mihomo,awg`: Mihomo chain exhausted→start healthy AWG standby→AWG.
- [ ] G05. FIXED: healthy fallback stays selected after primary recovers; define/test what happens if fallback later fails and primary has recovered (code currently may reconsider primary).
- [ ] G06. AUTO `awg,mihomo`: AWG failure→Mihomo if allowed, no performance optimization.
- [ ] G07. AUTO `mihomo,awg`: Mihomo failure→AWG, with sticky healthy fallback and no unrequested failback.
- [ ] G08. AUTO with one allowed transport or unconfigured state: no forbidden fallback or switching loop.
- [ ] G09. Manual AWG→Mihomo transition while mode Selective and again Transit; verify router and client state.
- [ ] G10. Manual Mihomo→AWG transition while mode Selective and again Transit; fresh handshake/TUN checks.
- [ ] G11. Both backends unavailable: Selective returns DIRECT; Transit remains fail-closed; management unaffected.
- [ ] G12. Three (configured threshold) or more repeated health failures trigger selector, success resets counter, transient recovery resets; record latency from traces.
- [ ] G13. Maintenance lock during provider/node/mode/config transaction suppresses false failover; concurrent timers cannot override.
- [ ] G14. Failed candidate transport preflight/health leaves previous transport selected, enabled and usable; rollback is atomic and repeatable.
- [ ] G15. Stopped standby backend can start; failed start does not disable original backend; after successful AWG selection inactive Mihomo shutdown is safe.
- [ ] G16. Full real chain: primary Mihomo node→next eligible node(s)→exhaustion→AWG; no rollback loops; restore original baseline at end. Distinguish genuine failures from injected mock results.

## H. READY Hot Pool, service gate, Stage18 and subscriptions (H01–H18)

- [ ] H01. Fresh-install/upgrade defaults are unambiguous: READY canary, balanced gate, Hot Pool SHADOW_ONLY, timers and node AUTO are exactly as documented and safe.
- [ ] H02. Hot Pool scanner never changes active transport, node, router, DNS or live provider; controls CPU/RAM/bandwidth use.
- [ ] H03. READY requires two independent successful checks spaced ≥600s; no fabricated proofs on reboot/retention.
- [ ] H04. API, ChatGPT web network response and actual 24-frame YouTube decode participate; the rejected initial HTTP-only YouTube prefilter is absent.
- [ ] H05. Service eligibility `off`, `balanced` and `require` are exercised under Mihomo MANUAL/FIXED/AUTO and READY on/off; 403/challenge/unknown/TLS errors never become authenticated ChatGPT success or unconditional node failure.
- [ ] H06. Numeric IPv4 endpoint HTTPS check rejects broken domain-only proxies; test multiple clean public IPs and no private IP targets.
- [ ] H07. Hot Pool READY candidate equals a unique exact *current live provider* node including credentials, endpoint and transport options.
- [ ] H08. READY candidate accepted→live node activation→true `mihomo0` postcheck→verified client application success.
- [ ] H09. READY exhaustion→fresh independent balanced service-scan of health-pool alternative; no latency-only promotion.
- [ ] H10. Active postcheck fails→rollback once, no repeated disruptive attempts in same cycle; failing rollback delegates to transport fallback.
- [ ] H11. Infrastructure route-not-ready errors are not endpoint quarantine; proven invalid endpoint failures are classified correctly.
- [ ] H12. Quarantine/cooldown and alias/server sharing work without hiding good nodes after subscription update.
- [ ] H13. SHADOW service/timers survive missing provider, forbidden user paths, service crashes and reboot; no unbounded RAM/log growth.
- [ ] H14. Continuity vault retains qualifying candidate across provider churn, but never silently promotes archived provider credentials to live.
- [ ] H15. Provider refresh `unchanged` is no-op, changed subscription stages safely; no unreviewed auto-promotion while active.
- [ ] H16. Native Clash/Mihomo YAML, plain VLESS URI and URL-safe/Base64 VLESS import; forced/auto format detection, unsupported network/TLS/Reality options reject safely.
- [ ] H17. DIRECT-first fetch, blocked DIRECT→explicit healthy transport bootstrap, offline cache behavior; expired/empty/malformed provider never destroys working state.
- [ ] H18. Provider URL/token/HWID redaction; imported Citadel/Remnawave identity does not leak into generic provider switching; safe candidate commit/recovery.

## I. DNS, IP sets, OpenCCK and domain precedence (I01–I10)

- [ ] I01. dnsmasq service binds Pi LAN DNS (UDP/TCP 53), upstream resolver available independent of VPN; no recursive self-resolution.
- [ ] I02. Selective client DNS leads to expected `nftset` entries (vpn4/direct4/source4); verify specific domain+subdomain.
- [ ] I03. DIRECT domain exception beats overlapping VPN/OpenCCK; rule add/delete/import/replace/export updates nftsets correctly.
- [ ] I04. Client allow-list applies only where configured; Transit is determined at MikroTik, not silently by Selective domain state.
- [ ] I05. DNS redirects apply only when explicitly enabled for Selective; Transit has no unwanted DNS interception or fake-IP route.
- [ ] I06. DNS upstream change, cancellation, malformed/duplicate/self IP and transaction rollback; existing resolvers preserved on error.
- [ ] I07. DNS DoH on MikroTik and local client DNS paths tested independently, with no claim of leak merely from public IP tests.
- [ ] I08. DNS caches/sets expire/repopulate; reconnect/refresh and domain IP changes do not misroute indefinitely.
- [ ] I09. OpenCCK sources domains/IPv4/CIDR, enable/disable/update failure, stored cache and periodic timer; no corruption of explicit DIRECT.
- [ ] I10. Under DNS failure, management SSH remains reachable; Selective/Transit retain their required fail-open/fail-closed semantics.

## J. Updates, backup, crash/reboot recovery and diagnostics (J01–J16)

- [ ] J01. Upgrade stable 1.2.0→1.3.0 preserves AWG private config, mode, active transport, node policy, DNS, OpenCCK, client list, subscriptions and private state.
- [ ] J02. Upgrade an already deployed v1.3 RC, including paused/enabled Hot Pool timer, preserves exact enablement state; never overwrites running externally managed scanner.
- [ ] J03. Gateway backup contains **every** newly installed component: Node22 links/binary, `awg-system-node`, `awg-dc`, DC unit, TUN helper, Stage18 service/timers/path and continuity vault, as well as older scripts.
- [ ] J04. Restore does not destroy a system Node symlink target under `/usr/local/lib/awg-pi` or leave a broken `/usr/local/bin/node`; preserve APT-owned Node and npm usability.
- [ ] J05. Interrupted download, package build, permission error, disk full, unit failure and bad config perform correct rollback without leaking or deleting last-good state.
- [ ] J06. AWG and Mihomo service enablement, active transport, selection mode, exact node, cache and timer policy remain stable after reboot.
- [ ] J07. Node 22, Stage18 RAM restore, 24-frame decoder and DC non-root agent recover on boot without external GitHub/npm reachability when validated cache exists.
- [ ] J08. Test DC initial OAuth authorization and pre-existing 0600 user session reuse; never pair or enable remote control as root or automatically.
- [ ] J09. DC systemd autostart after explicit user approval, read-only remote command, link failure and recovery; no inbound firewall rule.
- [ ] J10. Test system-wide Node 22 on clean install and opt-in migration from Debian Node 20, with existing npm/system consumers and no unmanaged overwrite.
- [ ] J11. Mode-specific nftables, table 100/101, DNS, Transit guard, health state, WAN egress and endpoint DIRECT correct after reboot.
- [ ] J12. Daily/monthly traffic counters survive interface recreate, restart, day/month rollover and reboot, checkpoint in low-write mode without double counting.
- [ ] J13. TUI/status: version, mode, selected transport/node, node/transport policies, handshake age, CPU temp/load, RAM, storage, clock/timezone, traffic and diagnostics accurate.
- [ ] J14. TUI cancel/invalid menus, domain list, client allow-list, profile replace/rollback, LAN reconfigure, node-chain editor and subscription candidate handling safe and SSH-accessible.
- [ ] J15. 24h or longer guarded soak crossing scan/update timers; measure load, memory, temperature, network traffic, file writes, disk/SD wear and actual media/app continuity without reboot.
- [ ] J16. Restore from validated full-media image; fresh boot of restore medium has working LAN/SSH, configured transport, DNS and previous state.

## K. End-to-end scenarios / exit gate (K01–K10)

- [ ] K01. Selective/Mihomo/working node→user VPN domain PASS→stop Mihomo→actual client DIRECT fallback→restore→selective VPN recovered.
- [ ] K02. Selective/AWG/working handshake→VPN domain PASS→stop AWG→DIRECT fallback→restore.
- [ ] K03. Transit/Mihomo/client ChatGPT+YouTube PASS→fail node→READY or fixed fallback→client applications recover; no DNS or direct leakage.
- [ ] K04. Transit/AWG/client HTTPS+service PASS→fail AWG→guarded fail-closed→healthy Mihomo takeover if configured.
- [ ] K05. Transit/Mihomo→AWG fallback after exact-node exhaustion, check AWG handshake, client external IP and no transport recursion.
- [ ] K06. Both VPN transports fail while Transit active→internet test client blocked, SSTP/router/Pi management unaffected; restore one transport recovers correct guard.
- [ ] K07. Full reverse migrations Transit→Selective→Transit and Mihomo→AWG→Mihomo with one real client each, including negative cases.
- [ ] K08. Provider changes mid-scan, IP/DNS changes mid-health, and maintenance lock conflicts do not trigger bad node/transport switching.
- [ ] K09. Clean install→first-time setup→working configured mode→reboot→upgrade→rollback→reboot, with no secrets leaked and no broken Node/DC/unit paths.
- [ ] K10. All mandatory P0 cases pass on SAME frozen candidate; full CI green; draft dependencies reconciled; update release docs, then merge/tag/promote v1.3.0; keep stable v1.2.0 until then.

## Specific static audit findings to close

1. `src/awg-transport:check_mihomo` treats local proxy health as transport health; the selector/health monitor rely on it. A genuine TUN-only failure can be hidden. Separate TUN gate and safe retry policy require a real test.
2. `src/awg-selection-monitor:try_failover` reconsiders any listed transport other than current. Clarify FIXED transport semantics if a fallback fails after earlier advance (distinct from one-way FIXED node chain), then test backward/forward behavior.
3. The new `install.sh` fresh path enables READY priority and the Hot Pool timers; older RC1/READY docs describe OFF/passive defaults. Make the release contract explicit, consistent and verified with negative startup cases.
4. `src/awg-update` backup/restore currently lacks some newly added DC/Node/Stage18/TUN files and might delete the Node symlink target under `/usr/local/lib/awg-pi`. Extend and test complete transactional rollback.
5. `.github/workflows/ci.yml` references 53 of 69 named tests in `tests/` and `extras/`; 16 new Python test files are not referenced and five installed Bash helper scripts do not have an explicit CI `bash -n` line. Extend mandatory CI gate before release.
6. Current Pi is in Selective, Mihomo active; its system Node remains Debian 20; AWG is not configured and current-install Transit is not accepted. Historical successes from October 9/16 belong to prior configurations and are useful but not replacement current-install evidence.

**Out of this release scope unless explicitly added to v1.3 installer:** IPTV/Lampa playlist content and monitoring, separately scheduled MikroTik NAS backup job, experimental browser/Stage20 tests, and unrelated VPS procurement. Preserve existing operation; do not attach their unrelated acceptance requirements to the core gateway release.

## Execution log — Step 1, 2026-10-17 (source-only)

- **A03/A04 PARTIAL:** CI candidate now explicitly includes previously omitted 16 Python regression modules and five new Bash syntax-check targets, plus one new backup-coverage module; evidence in `.github/workflows/ci.yml` commits `9e31ba3`, `efc0def`. **CI result on final HEAD has not been observed**, so these are not PASS.
- **J03/J04 PARTIAL:** backup/restore path for user-scoped DC CLI/service, managed Node v22 symlink and binary, Stage18, Mihomo TUN checker and other installed helpers has been extended in `src/awg-update` (commit `a5df21a`). Static manifest comparison found all 16 newly inventoried runtime files/units represented; `tests/test_release_backup_coverage.py` added (commit `0bad3a9`). This does **not** prove an actual backup+rollback or symlink recovery.
- **A08 BLOCKED:** `awg-upgrade-test` and `awg-upgrade` are both Offline in Desktop Commander as observed when beginning this step. No Pi, MikroTik, SSTP, VPN, DNS, or routing changes made. Reconnect test Pi before live/system-level checks.
- PR #115 must remain DRAFT. No full case is marked PASS until its acceptance evidence is complete.

## DC persistence implementation — 2026-10-17 (source/cached-runtime checks)

- Non-root **system** service `awg-dc-remote@.service` now uses `Restart=always` (20s backoff), `multi-user.target` and a saved-user-session condition. It runs independently of SSH/linger and does not open inbound ports or touch AWG/Mihomo/MikroTik.
- The version-pinned agent is prefetched into `karlinks`'s user npm cache and its **offline** launch path was proven from a live user session: `npm exec --offline --yes --package=node@22 --package=@wonderwhy-er/desktop-commander@0.2.52 -- sh -c 'node --version && node -p "typeof WebSocket" && desktop-commander remote --help'` returned Node `v22.23.3`, native WebSocket and valid agent help.
- Installer opt-in `AWG_DC_PREPARE=1 AWG_DC_AUTOSTART=1 AWG_DC_USER=karlinks` prefetches/checks cache and enables the daemon **only if** that user's previously authorized private `0600` session exists. Upgrades preserve existing service enablement. A first-time OAuth pairing remains interactive/explicit.
- From **GitHub head `bb3a73331a1a`**, source-only Pi checks: 10/10 DC installer tests + 6/6 Node tests + 6/6 release-backup tests PASS, `bash -n` PASS. `systemd-analyze verify` found the service binary not installed at the system path — expected until the user performs the one-time privileged install; **boot/reconnect tests are PENDING**. The current OS Node stays `v20.19.2` pending the separately controlled system Node migration.
- Do not mark J07/J08/J09/B13 as PASS until system service is installed, connected without the foreground terminal, verified after reboot and same-instance OAuth reuse confirmed.


## DC boot persistence — live test completed on 2026-10-17

- **PASS for persistent DC agent reboot sub-gate** on `awg-upgrade-test`. The user issued `sudo systemctl reboot` after verifying systemd `awg-dc-remote@karlinks.service` survives closing the foreground SSH DC process. Reboot proved by boot-ID transition `d34252b4-31e4-4793-bba1-ca8ce5e66433` → `8442dea4-8a94-4a8c-90a5-9095b7b18b8d`, boot time `2026-10-17 22:27:35 +07`.
- Post-boot remote tool connection directly executed successfully while DC device was Online. `systemctl is-enabled` and `is-active` both verified; main process PID 821, parent PID 1, nonroot `karlinks`, `Restart=always`, `NRestarts=0`. Saved user OAuth file retained owner `karlinks` and mode 0600, no new pairing needed.
- After reboot `awg-mihomo.service`, `dnsmasq.service`, `awg-pbr-health.service`, `awg-selection-monitor.service` and Hot Pool/Stage18 timers were active, `/run/awg-pbr/health.state=up`, `ip -4 route show table 100=default dev mihomo0`, no failed systemd units. Node.js remains `v20.19.2` system-wide; DC uses pre-cached isolated Node22. This is **not** system Node22 migration acceptance.
- **Storage note:** previously read-only-mounted old microSD at `/mnt/awg-old-sd` was NOT mounted after reboot (mount point directory exists; removable `/dev/sdb2` visible). No writes or mount operations performed. Verify intended removable-media mounting separately if needed; do not silently remount writable.
- Remaining DC-specific negatives (forced agent failure/reconnect, external network outage, gateway upgrade/rollback) and clean installer verification remain PENDING. Do not mark all J07–J09 or J11 as passed from this single reboot.

### A03/A06/A07/A11/A12 source and host preflight — 2026-10-17

**All operations here are read-only or confined to a disposable RAM-only Git clone. No live VPN, routes, MikroTik/SSTP or production Pi change.**

- **A03 PARTIAL:** test device `awg-upgrade-test` Debian 13 ARM64: `systemd-analyze verify` on **8 deployed representative gateway/DC service/timer units** returned no warnings. The deployed service list shows health, selector, Mihomo, timers and DC registered, `systemctl --failed` is empty. **Remaining:** automate static systemd validation for every candidate unit in CI plus fresh install verification. `shell` CI Bash/ShellCheck and pinned AWG build were PASS at prior candidate HEAD; rerun on final HEAD.
- **A06 PARTIAL:** tested device has `python3`, Bash, Git, curl, jq, nft, dnsmasq 2.91 with **nftset**, dig, ffmpeg, ffprobe, xz, Go, Node, npm/npx, AWG tools/core and Mihomo available. `NTPSynchronized=yes`. System timezone read-only inspection currently `Asia/Novosibirsk`; installer fresh default separately verified by 8 isolated tests. **Remaining:** clean Debian install with exact version/architecture/space/capability preflight and runtime operation, rather than mere binary presence.
- **A07 PARTIAL:** root-owned `/etc/awg-pbr` and `/etc/amnezia/amneziawg` both 0700; private DC session belongs to regular user `karlinks`, 0600; actual DC systemd unit active as non-root. `/etc/sudoers.d` filename listing displayed no catch-all custom root grant; **actual sudo policy and secret redaction require a separate authorized audit**. No secrets were opened or printed.
- **A11 ANCESTRY/POTENTIAL MERGE CONFLICTS PASS:** using a disposable full-history `/dev/shm` Git clone of PR #115, fetched draft PR heads #106/#108/#109/#110/#111; `git merge-base --is-ancestor` confirmed **each exact PR head is an ancestor** of PR #115 and `git merge-tree --write-tree` reported clean/already-included for all 5. No PR merged/pushed. The dependency code is physically present in #115 even though original PRs remain open/draft. **Remaining:** behavior-level stack review, installer/upgrade overwrite policy and merge/close decision; still do not release.
- **A12 DOCS UPDATED, ACCEPTANCE PENDING:** latest PR #115 fresh-install path now persists `ready-auto` node priority and arms provider-guarded Hot Pool/Stage18 timers, while Hot Pool itself is SHADOW_ONLY; upgrades preserve operator's state. Updated previously outdated `docs/RC1-INTEGRATION-REVIEW.md` and annotated `docs/READY-AUTO-CANARY.md` to distinguish historical optional/OFF canary from current fresh-install behavior. **Remaining:** real clean-install inspection confirms enabled timers are inert without a subscription, no premature active node/route switching.

### A03/A07/A08/A09 follow-up — 17 October 2026

- **A03 source/unit verification PASS on candidate before following documentation commit**: a new six-test suite, tests/test_systemd_units.py, validates all **13** shipped service/timer/path units using systemd-analyze verify in a disposable sandbox root with innocuous executable stubs and the host's systemd base unit definitions. Tests also compare installer staging, custom ExecStart paths, internal AWG dependencies, nonroot persistent DC and provider-gated shadow Hot Pool. 6/6 PASS on test Pi. Added to mandatory GitHub Actions (CI latest HEAD must be checked again).
- **A07 partial**: tests/test-redaction.sh, test-diagnostics-hardening.sh and test-visible-inputs.sh all PASS from read-only source checkout. Sensitive gateway configuration and backup paths root:root 0700; nonroot DC 0600 session; no broad privilege grants detected in tracked executable sources. Real sudo policy remains unreviewed because DC blocks direct sudo commands. Do not claim A07 full PASS.
- **A08 partial**: LAN route to MikroTik and ICMP verified, test Pi SSH and DC persistent systemd service active/enabled. Remote SSTP management via actual independent external client NOT VERIFIED. The Pi's healthy services and remote DC are not proof of independent recovery.
- **A09 not armed**: backup path exists root-owned 0700, but current backup contents, timed rescue mechanism and restore procedure have not been proven. The former removable SD is no longer mounted. No destructive tests authorized until an independent watchdog and restoration are actually verified.
- Detailed stop/go requirements: [RELEASE-TEST-SAFETY-v1.3.0.md](RELEASE-TEST-SAFETY-v1.3.0.md). No live VPN/MikroTik/SSTP edits in this step.
