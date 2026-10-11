# AUTO SMART / SHADOW v2 — calibrated throughput ranking

**Status:** experimental observer, **not** production automatic node selection. AWG Pi Gateway v1.3.0 remains on its current `MANUAL/FIXED/AUTO` node policy. The SMART engine has no transport-selector, nftables, TUN, routing, or configuration mutators.

## Why the calibration is necessary

On 2026-10-11 the live Mihomo Hysteria2 node `hysteria2-1711051470` egress `3.123.42.12` measured through the production HTTP proxy:

| Download volume | Observed average | 
| --- | ---: |
| 1.5 MB | 11.37 Mbps |
| 5 MB | 89.71 Mbps |
| 20 MB | 126.23 Mbps |
| 30 MB | 120.40 Mbps |
| 1.5 MB second request | 17.83 Mbps |

The original shadow ranking used only 1.5 MB downloads and 300 KB uploads for each candidate, thus significantly penalizing protocols with slow startup and inaccurately ranking sustained throughput. These measurements are source-, time- and target-specific, **not** globally guaranteed node speed.

## Calibrated procedure (v2)

1. Reuse the existing verified health pool (max age 1h and unchanged provider checksum) and existing user region / protocol / cooldown constraints. Select up to 10 unique endpoints and protocol-diverse candidates, retaining the current node when eligible.
2. Run a loopback-only second Mihomo process. The runtime config with subscription secrets exists only in root-only `/dev/shm`, the production proxy is untouched, and there is no TUN.
3. Perform a short **reachability screening**, default 1.5 MB HTTPS download per candidate. This is **not** used as the final speed figure.
4. For up to three survivors, chosen with active-node priority and protocol diversity, perform an 8 MB download and 2 MB random upload. This is the first sustained throughput measurement.
5. Recheck the current node and best non-current competitor (if reachable) with an additional **20 MB** download each. The final download rate is the weighted result (one part 8 MB plus two parts 20 MB). Only rechecked nodes are eligible for a manual recommendation.
6. Remember up to five independent confirmation successes/failures **in root-only tmpfs**, keyed by provider hash and measurement version. A suggested change requires at least two separately confirmed cycles and at least 30% **and** 10 Mbps better download performance than the confirmed current node. Current-node changes mid-scan invalidate the recommendation.
7. No automatic switch is implemented: `SMART_SWITCHES_MADE=0` is invariant. Failures do not affect production. SMART's optional systemd timer stays **disabled**.

At ten selected candidates, the configured application-level test traffic cap is 85 MB (10×1.5 MB screening, 3×(8 MB download + 2 MB upload), 2×20 MB confirmation); HTTP/TLS and retransmission overhead may increase wire traffic. A full health scan of all 1869 nodes is **not** triggered. With ten failures, actual transferred bytes can be lower; nominal cap remains bounded by code. Do not enable the optional 3-hour timer until operator reviews real resource and data usage.

## Service and helper (after installation)

`awg-mihomo-smart.service` is a one-shot root service, CPU-quota and memory limited, protected home / filesystem, using independent loopback-only Mihomo. The existing `awg-gpt` sudo helper exposes allow-listed operations:

```sh
sudo -n /usr/local/sbin/awg-gpt smart-status
sudo -n /usr/local/sbin/awg-gpt smart-run
sudo -n /usr/local/sbin/awg-gpt smart-report
sudo -n /usr/local/sbin/awg-gpt smart-logs
sudo -n /usr/local/sbin/awg-gpt smart-disable
```

These commands are bounded to the observer. They do not give generic root shell or update permission; operator `sudo` is needed when replacing this program binary.

## Acceptance

- Verify 17+ unit/integration tests, including simulated end-to-end scans, current-node stickiness, protocol diversity, 2-confirmation rule and no switches.
- First real run must measure the active Hysteria2 and a competitor using multi-MB transfers. Compared with an independent large download through the same live node, avoid claiming exact equivalence because benchmark origins and connection conditions differ.
- Post-run verify production selected node/egress, `Health state up`, `Transit guard SAFE`, AWG available, running services, `table 100`, and SMART timer disabled.
- No promotion to automatic application without long-term comparisons, mobile/client measurements, premium IP geography policy, rollback tests and explicit approval.
- If root service fails, report `SMART_ADVICE` as inconclusive; existing AUTO remains the live fallback mechanism.

## Current scope and limitations

Speed.cloudflare.com is one measurement direction, not a comprehensive assessment of YouTube or Google services. ICMP latency, UDP/QUIC quality, packet loss, jitter, real client performance and Google geolocation are not yet part of the composite score. European filters fail closed when location verification is absent. No inference from proxy name to country is allowed.

**GitHub:** code is prepared and validated on Pi staging; do not claim a PR or merge until branch publication has actually succeeded.

## Calibrated confirmation fix

Cloudflare returns HTTP 403 for exactly 16,000,000 bytes on the observed Hysteria2 route, whereas an HTTP 200 response for 20,000,000 bytes measured approximately 137.6 Mbps. The confirmation size is now 20 MB. A failed confirmation followed by only one good cycle does not satisfy the required two **consecutive** successes.

## Low-traffic 48–72h observation variant

The optional observer timer runs 8h after the timer is activated and every **8h** after each service activation. With 10 short screens (1.5 MB each), only **three** sustained finalists (8 MB download + 2 MB upload each) and two 20 MB confirmations, nominal application test traffic is capped at **85 MB per cycle / 255 MB per day** at three runs a day, before transport overhead. The currently active node remains in the deep-test shortlist. Candidate protocol leaders rotate between 8h periods to mitigate selection bias.

The observer keeps up to **12** compact, root-only run records in `/run/awg-pbr/mihomo-smart/runs.json`, on tmpfs, with no subscription credentials and no persistent microSD logging. Inspect with `sudo /usr/local/sbin/awg-mihomo-smart history --count 12`. A reboot intentionally drops its transient measurement history. The versioned health success history is reset when upgrading the measurement method so invalid 16MB 403 outcomes cannot bias new scores.

The systemd timer is shipped **disabled by default**. Enable it only after explicitly approving the monitoring window; do not leave it running after the planned 48–72h trial. Historical records support daypart comparison, not automated switching. The present scoring still cannot establish which Google/YouTube destination or exit-IP geography will work best.

The already allow-listed `sudo -n /usr/local/sbin/awg-gpt smart-report` now includes this bounded daypart trend automatically; expanding sudo permissions for a new history command is unnecessary.
