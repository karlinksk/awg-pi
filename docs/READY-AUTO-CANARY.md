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

[executed on device: awg-upgrade (7ff7c792-9f11-48ea-9b09-8734178c247a)]
## Second supervised trial — 2026-10-16: root cause isolated

- Exact failure now confirmed as `READY_AUTO=POSTCHECK_FAILED REASON=ROUTE_MISSING`; automatic return to the prior Shadowsocks node succeeded, no additional node attempts occurred and AWG remained healthy.
- Mihomo process started at **18:13:38** (Novosibirsk, UTC+7). The independent Transit health monitor applied the route at **18:13:51**, **13 seconds later**. The original short postcheck exhausted all three attempts before the Transit route was available; **do not blame the tested transport or interpret this as an OpenAI failure**.
- New draft postcheck explicitly waits for the marked default route in table 100, with bounded retry (12 polls, 2-second interval, max 22 seconds of sleeps) before making any network request. Only then does it perform up to three strict public-egress + OpenAI API 401 checks. A 403 remains non-passing; node drift aborts immediately. All errors use allowlisted codes.
- 27/27 selector, TUN and monitor isolated regressions PASS; current live Shadowsocks node passed the revised read-only check on first route poll and network attempt. **The revised route-grace code has not yet passed a real failover trial at the time of this note**.
