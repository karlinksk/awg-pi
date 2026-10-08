#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROUTE="$ROOT/src/awg-route"
INSTALL="$ROOT/install.sh"

echo "=== diagnostics fail-closed verification is pipefail-safe ==="
grep -Fq 'transit_status="$("$TRANSIT_ROUTING" status 2>&1 || true)"' "$ROUTE"
grep -Fq "grep -Eq '^Transit guard: (SAFE|LOCKDOWN)\$' <<<\"\$transit_status\"" "$ROUTE"
if grep -Fq "\"\$TRANSIT_ROUTING\" status 2>/dev/null | grep -Fqx 'Transit guard: SAFE'" "$ROUTE"; then
  echo 'FAIL: diagnostics still pipes a non-zero transit status into grep under pipefail' >&2
  exit 1
fi

echo "=== diagnostics restores Transit before returning ==="
grep -Fq 'Transit restore: OK' "$ROUTE"
grep -Fq 'Transit restore: FAIL' "$ROUTE"
grep -Fq 'return "$diag_rc"' "$ROUTE"

echo "=== diagnostics is transport-aware ==="
grep -Fq 'Active transport: $transport_id' "$ROUTE"
grep -Fq '"$TRANSPORT_CLI" status 2>&1 || true' "$ROUTE"
grep -Fq 'engine not installed' "$ROUTE"
grep -Fq 'AWG endpoint: not applicable' "$ROUTE"
grep -Fq 'Transit restore: OK (expected FAIL-CLOSED/not-ready)' "$ROUTE"

echo "=== installer publishes version before diagnostics ==="
version_line="$(grep -n -F "printf '%s\\n' \"\$AWG_PI_VERSION\" >/etc/awg-pbr/version" "$INSTALL" | head -1 | cut -d: -f1)"
diag_line="$(grep -n -F '"$ROUTE_CLI" diagnostics' "$INSTALL" | head -1 | cut -d: -f1)"
[[ -n "$version_line" && -n "$diag_line" ]]
(( version_line < diag_line ))

echo "=== stale v1.2 installer labels removed ==="
if grep -Fq 'CLI v1.2.0 + Transit + OpenCCK + SSH TUI' "$INSTALL"; then
  echo 'FAIL: stale v1.2 CLI stage label remains' >&2
  exit 1
fi
if grep -Fq 'IPv6: не использовать в Transit v1.2.0.' "$INSTALL"; then
  echo 'FAIL: stale v1.2 Transit IPv6 label remains' >&2
  exit 1
fi

echo "diagnostics hardening: OK"
