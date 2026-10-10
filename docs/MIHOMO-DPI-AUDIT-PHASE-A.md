# Phase A: Mihomo passive failure audit (research only)

The script `src/awg-mihomo-dpi-audit.py` **reads a saved, already-completed health scan**.
It does not connect to hosts, call DNS, start Mihomo, modify routes, send packets,
modify nftables, install zapret2, or switch working transports. No changes to
SSTP, Transit FAIL-CLOSED or Selective FAIL-OPEN.

## Why this is necessary

The existing Mihomo scanner uses its local controller's `/delay` API to check
`https://www.gstatic.com/generate_204` with a 4500 ms default timeout.
A failed request does **not** establish whether the cause is DNS, IP filtering,
TCP handshake, QUIC, TLS/certificate validation, authentication, target server,
or DPI. The saved `error` field is often a generic Python exception class
from a request to the **local controller**, not an underlying remote error.

The passive script therefore explicitly classifies ambiguous failures as
`undifferentiated_probe_exception`, and never marks anything as DPI-confirmed.
An `http-NNN` error may be from the local Mihomo API, not the remote server.

## Safe test without production data

```bash
python3 src/awg-mihomo-dpi-audit.py --self-test
python3 -m unittest discover -s tests -p 'test_mihomo_dpi_audit.py' -v
```

## One-time read of the real pool

The snapshot lives at `/run/awg-pbr/mihomo-pool/live.json`, mode-restricted
to root. This is intentional: provider node data and endpoints must not be
exposed by changing directory/file permissions. Do not run as a scheduled service.

For an authorized administrator, after reviewing the source file, run:

```bash
sudo python3 /home/karlinks/awg-mihomo-dpi-audit.py \
  --input /run/awg-pbr/mihomo-pool/live.json
```

Or, in a source checkout:
```bash
sudo python3 src/awg-mihomo-dpi-audit.py --input /run/awg-pbr/mihomo-pool/live.json
```

The program sends only **aggregate counts** to stdout, including failure
categories by profile and endpoint-level all-failed/mixed/all-healthy counts.
It does not print node names, endpoint IPs, passwords, UUIDs, URLs, tokens or
the original error strings. JSON output is supported with `--format json`.

There is no persistent install and no sudoers/awg-gpt modification for
this experimental phase. Keep sudo scoped to this single invocation.

## Interpretation

- `scanned_profiles` = profile definitions tested, possibly duplicates.
- `unique_host_ports` = distinct textual host:port pairs, not unique IPs,
  datacenters or providers.
- `endpoints_mixed` = at least one profile passes and another fails at
  the same textual host:port; differences can include credentials, protocol,
  certificate settings or scan-time variability.
- `endpoints_all_failed` = no profile for that host:port passed the
  last health check; **not necessarily blocked**.
- `snapshot_age_seconds` should be inspected before conclusions.
- `dpi_confirmed=0` means DPI is **not determined** from the cached snapshot,
  not a claim that DPI is absent.

## Next phase, not implemented

Targeted, consented network tests of carefully sampled failing endpoints with
explicit checks for routing/DIRECT, DNS, TCP vs UDP, handshake and application
traffic, ideally comparing local Russian and independent foreign vantage points.
Only then examine zapret2 in isolated test namespaces, keeping production
failover and SSTP untouched.
