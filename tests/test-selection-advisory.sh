#!/usr/bin/env bash
# Isolated advisory regression. No production route, service or node changes.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/run"
printf 'awg\n' > "$TMP/current"
printf 'SELECTION_MODE=auto\nSELECTION_PRIMARY=\nSELECTION_ORDER=mihomo,awg\n' > "$TMP/selection"
printf '{}\n' > "$TMP/snapshot"
: > "$TMP/select.log"
cat > "$TMP/common" <<'MOCK'
awg_transport_get(){ cat "$AWG_TRANSPORT_FILE"; }
awg_transport_backend_valid(){ [[ "$1" == awg || "$1" == mihomo ]]; }
MOCK
cat > "$TMP/bin/transport" <<'MOCK'
#!/usr/bin/env bash
case "$1" in
  check) exit 0 ;;
  select) echo "$2" >> "$MOCK_SELECT_LOG"; exit 0 ;;
  *) exit 2 ;;
esac
MOCK
cat > "$TMP/bin/observer.py" <<'MOCK'
import json
import os
import sys
with open(os.environ["MOCK_OBSERVER_CALLED"],"a") as f:
    f.write("called\n")
if os.getenv("MOCK_OBSERVER_FAIL") == "1":
    sys.exit(3)
print(json.dumps({"decision":{"mode":"DRY_RUN_ONLY","action":"SELECT_TRANSPORT",
                               "target":"mihomo"},"next_memory":{}}))
MOCK
chmod +x "$TMP/bin/transport"
run_cycle() {
  AWG_COMMON_FILE="$TMP/common" \
  AWG_TRANSPORT_FILE="$TMP/current" \
  AWG_SELECTION_FILE="$TMP/selection" \
  AWG_TRANSPORT_CLI="$TMP/bin/transport" \
  MIHOMO_NODE_POLICY_CLI=/bin/false \
  AWG_SELECTION_STATE_DIR="$TMP/run" \
  AWG_SELECTION_FAILURES="$TMP/run/failures" \
  AWG_LOCK_FILE="$TMP/maintenance.lock" \
  LOGGER_BIN=/bin/true AWG_SELECTION_ONCE=1 \
  AWG_ADVISORY_ENABLED="$1" \
  AWG_ADVISORY_SCRIPT="$TMP/bin/observer.py" \
  AWG_ADVISORY_SNAPSHOT="$TMP/snapshot" \
  AWG_ADVISORY_ROOT="$TMP/run/advisory" \
  MOCK_SELECT_LOG="$TMP/select.log" \
  MOCK_OBSERVER_CALLED="$TMP/observer.log" \
  MOCK_OBSERVER_FAIL="${MOCK_OBSERVER_FAIL:-0}" \
  bash "$ROOT/src/awg-selection-monitor"
}
run_cycle 0
[[ ! -e "$TMP/observer.log" && ! -e "$TMP/run/advisory/last.json" ]]
[[ ! -s "$TMP/select.log" && "$(cat "$TMP/current")" == awg ]]
echo 'PASS disabled by default: no advisory calls'
run_cycle 1
[[ -s "$TMP/run/advisory/last.json" && -s "$TMP/observer.log" ]]
grep -Fq 'DRY_RUN_ONLY' "$TMP/run/advisory/last.json"
[[ ! -s "$TMP/select.log" && "$(cat "$TMP/current")" == awg ]]
echo 'PASS opt-in: advisory did not execute suggested transport switch'
rm -f "$TMP/run/advisory/last.json"
MOCK_OBSERVER_FAIL=1 run_cycle 1
[[ ! -e "$TMP/run/advisory/last.json" ]]
[[ ! -s "$TMP/select.log" && "$(cat "$TMP/current")" == awg ]]
echo 'PASS advisory failure cannot interrupt old healthy transport'
