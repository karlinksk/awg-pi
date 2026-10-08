#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'sudo rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/run"
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"

cat >"$TMP/bin/transport" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${MOCK_TRANSPORT_STATE:?}"
log="${MOCK_TRANSPORT_LOG:?}"
case "${1:-}" in
  check)
    case "${2:-}" in
      awg) [[ "${MOCK_AWG_HEALTH:-up}" == up ]] ;;
      mihomo) [[ "${MOCK_MIHOMO_HEALTH:-up}" == up ]] ;;
      *) exit 2 ;;
    esac
    ;;
  select)
    printf 'select:%s\n' "$2" >>"$log"
    case "$2" in
      awg) [[ "${MOCK_AWG_HEALTH:-up}" == up ]] ;;
      mihomo) [[ "${MOCK_MIHOMO_HEALTH:-up}" == up ]] ;;
      *) exit 2 ;;
    esac
    printf '%s\n' "$2" >"$state"
    ;;
  get)
    cat "$state"
    ;;
  *)
    exit 2
    ;;
esac
MOCK

cat >"$TMP/bin/logger" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK
chmod +x "$TMP/bin/"*

run_policy(){
  sudo env     AWG_COMMON_FILE="$ROOT/src/awg-common"     AWG_TRANSPORT_FILE="$TMP/transport"     AWG_SELECTION_FILE="$TMP/selection.env"     AWG_TRANSPORT_CLI="$TMP/bin/transport"     MOCK_TRANSPORT_STATE="$TMP/transport"     MOCK_TRANSPORT_LOG="$TMP/log"     MOCK_AWG_HEALTH="${MOCK_AWG_HEALTH:-up}"     MOCK_MIHOMO_HEALTH="${MOCK_MIHOMO_HEALTH:-up}"     bash "$ROOT/src/awg-selection" "$@"
}

run_monitor(){
  sudo env     AWG_COMMON_FILE="$ROOT/src/awg-common"     AWG_TRANSPORT_FILE="$TMP/transport"     AWG_SELECTION_FILE="$TMP/selection.env"     AWG_TRANSPORT_CLI="$TMP/bin/transport"     AWG_SELECTION_STATE_DIR="$TMP/run"     AWG_SELECTION_FAILURES="$TMP/run/failures"     AWG_SELECTION_FAILURE_THRESHOLD=3     AWG_SELECTION_ONCE=1     LOGGER_BIN="$TMP/bin/logger"     MOCK_TRANSPORT_STATE="$TMP/transport"     MOCK_TRANSPORT_LOG="$TMP/log"     MOCK_AWG_HEALTH="${MOCK_AWG_HEALTH:-up}"     MOCK_MIHOMO_HEALTH="${MOCK_MIHOMO_HEALTH:-up}"     bash "$ROOT/src/awg-selection-monitor"
}

echo "=== manual is the safe default ==="
rm -f "$TMP/selection.env" "$TMP/run/failures"
: >"$TMP/log"
run_monitor
[[ ! -s "$TMP/log" ]]
out="$(run_policy status)"
grep -Fqx 'Selection mode: manual' <<<"$out"
grep -Fqx 'Automatic transport switching: disabled' <<<"$out"

echo "=== fixed policy validates explicit order ==="
out="$(run_policy mode fixed awg mihomo)"
grep -Fqx 'SELECTION_MODE=fixed' <<<"$out"
sudo grep -Fqx 'SELECTION_MODE=fixed' "$TMP/selection.env"
sudo grep -Fqx 'SELECTION_PRIMARY=awg' "$TMP/selection.env"
sudo grep -Fqx 'SELECTION_ORDER=mihomo' "$TMP/selection.env"
if run_policy mode fixed awg awg >"$TMP/out" 2>"$TMP/err"; then
  echo 'FAIL: duplicate transport accepted in fixed policy' >&2
  exit 1
fi
grep -Fq 'Duplicate transport' "$TMP/err"

echo "=== fixed failover requires repeated failures ==="
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
rm -f "$TMP/run/failures"
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx '2' "$TMP/run/failures"
out="$(MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=awg->mihomo' <<<"$out"
grep -Fqx 'select:mihomo' "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
grep -Fqx '0' "$TMP/run/failures"

echo "=== healthy fallback is sticky; no automatic return to primary ==="
: >"$TMP/log"
MOCK_AWG_HEALTH=up MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx mihomo "$TMP/transport"

echo "=== AUTO is availability-only and obeys explicit allowed order ==="
run_policy mode auto awg mihomo >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
printf '2\n' >"$TMP/run/failures"
out="$(MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=awg->mihomo' <<<"$out"
grep -Fqx mihomo "$TMP/transport"
status="$(run_policy status)"
grep -Fqx 'Selection mode: auto' <<<"$status"
grep -Fqx 'Performance optimization: disabled (conservative AUTO)' <<<"$status"
grep -Fqx 'Mihomo node auto-selection: disabled' <<<"$status"

echo "=== policy never silently moves a healthy transport not in allowed set ==="
run_policy mode auto awg >/dev/null
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"
MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx mihomo "$TMP/transport"

echo "=== unconfigured may activate first healthy explicitly allowed transport ==="
run_policy mode auto awg mihomo >/dev/null
printf '%s\n' unconfigured >"$TMP/transport"
: >"$TMP/log"
out="$(MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=unconfigured->mihomo' <<<"$out"
grep -Fqx mihomo "$TMP/transport"

echo "=== manual disables automatic switching immediately ==="
run_policy mode manual >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
printf '3\n' >"$TMP/run/failures"
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx awg "$TMP/transport"
grep -Fqx '0' "$TMP/run/failures"

echo "transport selection policy: OK"
