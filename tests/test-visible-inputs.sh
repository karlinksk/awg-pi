#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== setup input must remain visible ==="

# The project intentionally shows values while the user is configuring them.
# Redaction still applies to status/diagnostics after values are stored.
if grep -RInE -- 'passwordbox|--insecure|secret_input|secret_ask|read[[:space:]]+-[^[:space:]]*s([^[:space:]]*)?[[:space:]]' src install.sh; then
  echo 'FAIL: masked input primitive found in setup/runtime sources' >&2
  exit 1
fi

grep -Fq -- '--inputbox "$prompt" 11 110 "$initial"' src/awg-menu
grep -Fq -- '--editbox "$PASTE_TMP" 30 110' src/awg-menu
[[ "$(grep -Fc -- '--editbox "$PASTE_TMP" 30 110' src/awg-menu)" -eq 2 ]]
grep -Fq 'Вставьте полный URL подписки (ввод отображается)' src/awg-first-run

# Do not regress post-apply secret redaction.
grep -Fq 'provider_url_redacted(){' src/awg-mihomo-configure
grep -Fq "printf '%s/[redacted]" src/awg-mihomo-configure

echo "visible setup input UX: OK"
