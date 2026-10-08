#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/sys/awg0/statistics" "$TMP/sys/mihomo0/statistics" "$TMP/run" "$TMP/persist"

setc(){
  printf '%s\n' "$2" >"$TMP/sys/$1/statistics/rx_bytes"
  printf '%s\n' "$3" >"$TMP/sys/$1/statistics/tx_bytes"
}
setidx(){
  printf '%s\n' "$2" >"$TMP/sys/$1/ifindex"
}

run_traffic(){
  env     AWG_TRAFFIC_RUNTIME_DIR="$TMP/run"     AWG_TRAFFIC_PERSIST_DIR="$TMP/persist"     AWG_TRAFFIC_SYSFS_ROOT="$TMP/sys"     AWG_TRAFFIC_NOW_EPOCH="$NOW"     AWG_TRAFFIC_PERSIST_INTERVAL=21600     bash "$ROOT/src/awg-traffic" "$@"
}

echo "=== first sample counts existing interface bytes ==="
NOW="$(date -d '2026-10-08 10:00:00 UTC' +%s)"
setidx awg0 10
setidx mihomo0 20
setc awg0 1000 2000
setc mihomo0 300 700
run_traffic sample
# shellcheck disable=SC1090
. "$TMP/run/state.env"
[[ "$DAY_AWG_RX" == 1000 && "$DAY_AWG_TX" == 2000 ]]
[[ "$DAY_MIHOMO_RX" == 300 && "$DAY_MIHOMO_TX" == 700 ]]
[[ "$MONTH_AWG_RX" == 1000 && "$MONTH_MIHOMO_TX" == 700 ]]

echo "=== second sample adds deltas only ==="
NOW=$((NOW+60))
setc awg0 1600 2600
setc mihomo0 500 900
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_AWG_RX" == 1600 && "$DAY_AWG_TX" == 2600 ]]
[[ "$DAY_MIHOMO_RX" == 500 && "$DAY_MIHOMO_TX" == 900 ]]

echo "=== interface recreation is detected by ifindex even with larger counters ==="
NOW=$((NOW+60))
setidx awg0 11
setidx mihomo0 21
setc awg0 5000 6000
setc mihomo0 1000 1200
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_AWG_RX" == 6600 && "$DAY_AWG_TX" == 8600 ]]
[[ "$DAY_MIHOMO_RX" == 1500 && "$DAY_MIHOMO_TX" == 2100 ]]

echo "=== day rollover resets day but preserves month ==="
NOW="$(date -d '2026-10-09 00:01:00 UTC' +%s)"
setc awg0 5050 6050
setc mihomo0 1020 1230
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_KEY" == 2026-10-09 ]]
[[ "$DAY_AWG_RX" == 50 && "$DAY_AWG_TX" == 50 ]]
[[ "$DAY_MIHOMO_RX" == 20 && "$DAY_MIHOMO_TX" == 30 ]]
[[ "$MONTH_AWG_RX" == 6650 && "$MONTH_AWG_TX" == 8650 ]]
[[ "$MONTH_MIHOMO_RX" == 1520 && "$MONTH_MIHOMO_TX" == 2130 ]]
# Rollover forces a persistent checkpoint even before the normal 6h interval.
grep -Fq 'DAY_KEY=2026-10-09' "$TMP/persist/state.env"

echo "=== month rollover resets month counters ==="
NOW="$(date -d '2026-11-01 00:01:00 UTC' +%s)"
setc awg0 5100 6100
setc mihomo0 1040 1250
run_traffic sample
. "$TMP/run/state.env"
[[ "$MONTH_KEY" == 2026-11 ]]
[[ "$MONTH_AWG_RX" == 50 && "$MONTH_AWG_TX" == 50 ]]
[[ "$MONTH_MIHOMO_RX" == 20 && "$MONTH_MIHOMO_TX" == 20 ]]
grep -Fq 'MONTH_KEY=2026-11' "$TMP/persist/state.env"

echo "=== compact/full status are readable ==="
compact="$(run_traffic status compact)"
grep -Fq 'Today:' <<<"$compact"
grep -Fq 'Month:' <<<"$compact"
full="$(run_traffic status full)"
grep -Fq 'Pi transport interfaces only' <<<"$full"
grep -Fq 'AWG:' <<<"$full"
grep -Fq 'Mihomo:' <<<"$full"
grep -Fq '21600s' <<<"$full"

echo "=== daemon releases lock so status remains readable ==="
NOW="$(date -d '2026-11-01 00:02:00 UTC' +%s)"
env \
  AWG_TRAFFIC_RUNTIME_DIR="$TMP/run" \
  AWG_TRAFFIC_PERSIST_DIR="$TMP/persist" \
  AWG_TRAFFIC_SYSFS_ROOT="$TMP/sys" \
  AWG_TRAFFIC_NOW_EPOCH="$NOW" \
  AWG_TRAFFIC_INTERVAL=30 \
  AWG_TRAFFIC_PERSIST_INTERVAL=21600 \
  bash "$ROOT/src/awg-traffic" daemon &
daemon_pid=$!
sleep 0.3
timeout 2 env \
  AWG_TRAFFIC_RUNTIME_DIR="$TMP/run" \
  AWG_TRAFFIC_PERSIST_DIR="$TMP/persist" \
  AWG_TRAFFIC_SYSFS_ROOT="$TMP/sys" \
  AWG_TRAFFIC_NOW_EPOCH="$NOW" \
  bash "$ROOT/src/awg-traffic" status compact >/dev/null
kill -TERM "$daemon_pid"
wait "$daemon_pid"

echo "low-write traffic accounting: OK"
