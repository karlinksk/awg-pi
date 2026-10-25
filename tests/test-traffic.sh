#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/sys/awg0/statistics" "$TMP/sys/mihomo0/statistics" "$TMP/run" "$TMP/persist"
printf 'boot-A\n' >"$TMP/boot-id"

setc(){
  printf '%s\n' "$2" >"$TMP/sys/$1/statistics/rx_bytes"
  printf '%s\n' "$3" >"$TMP/sys/$1/statistics/tx_bytes"
}
setidx(){
  printf '%s\n' "$2" >"$TMP/sys/$1/ifindex"
}

run_traffic(){
  env     AWG_TRAFFIC_RUNTIME_DIR="$TMP/run"     AWG_TRAFFIC_PERSIST_DIR="$TMP/persist"     AWG_TRAFFIC_SYSFS_ROOT="$TMP/sys"     AWG_TRAFFIC_BOOT_ID_FILE="$TMP/boot-id"     AWG_TRAFFIC_PUBLIC_STATE="$TMP/public.env"     AWG_TRAFFIC_NOW_EPOCH="$NOW"     AWG_TRAFFIC_PERSIST_INTERVAL=21600     bash "$ROOT/src/awg-traffic" "$@"
}

echo "=== first sample establishes baseline without inventing historical traffic ==="
NOW="$(date -d '2026-10-08 10:00:00 UTC' +%s)"
setidx awg0 10
setidx mihomo0 20
setc awg0 1000 2000
setc mihomo0 300 700
run_traffic sample
# shellcheck disable=SC1090
. "$TMP/run/state.env"
[[ "$INITIALIZED" == 1 ]]
[[ "$LAST_BOOT_ID" == boot-A ]]
[[ "$DAY_AWG_RX" == 0 && "$DAY_AWG_TX" == 0 ]]
[[ "$DAY_MIHOMO_RX" == 0 && "$DAY_MIHOMO_TX" == 0 ]]
[[ "$MONTH_AWG_RX" == 0 && "$MONTH_MIHOMO_TX" == 0 ]]
[[ "$LAST_AWG_RX" == 1000 && "$LAST_AWG_TX" == 2000 ]]
[[ "$LAST_MIHOMO_RX" == 300 && "$LAST_MIHOMO_TX" == 700 ]]
grep -Fq 'INITIALIZED=1' "$TMP/persist/state.env"
grep -Fq 'LAST_BOOT_ID=boot-A' "$TMP/persist/state.env"
[[ "$(stat -c %a "$TMP/public.env")" == 644 ]]
grep -Fq 'DAY_AWG_RX=0' "$TMP/public.env"
! grep -Fq 'LAST_BOOT_ID' "$TMP/public.env"
! grep -Fq 'IFINDEX' "$TMP/public.env"

echo "=== second sample adds deltas only ==="
NOW=$((NOW+60))
setc awg0 1600 2600
setc mihomo0 500 900
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_AWG_RX" == 600 && "$DAY_AWG_TX" == 600 ]]
[[ "$DAY_MIHOMO_RX" == 200 && "$DAY_MIHOMO_TX" == 200 ]]

echo "=== interface recreation is detected by ifindex even with larger counters ==="
NOW=$((NOW+60))
setidx awg0 11
setidx mihomo0 21
setc awg0 5000 6000
setc mihomo0 1000 1200
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_AWG_RX" == 5600 && "$DAY_AWG_TX" == 6600 ]]
[[ "$DAY_MIHOMO_RX" == 1200 && "$DAY_MIHOMO_TX" == 1400 ]]

echo "=== day rollover resets day but preserves month ==="
NOW="$(date -d '2026-10-09 00:01:00 UTC' +%s)"
setc awg0 5050 6050
setc mihomo0 1020 1230
run_traffic sample
. "$TMP/run/state.env"
[[ "$DAY_KEY" == 2026-10-09 ]]
[[ "$DAY_AWG_RX" == 50 && "$DAY_AWG_TX" == 50 ]]
[[ "$DAY_MIHOMO_RX" == 20 && "$DAY_MIHOMO_TX" == 30 ]]
[[ "$MONTH_AWG_RX" == 5650 && "$MONTH_AWG_TX" == 6650 ]]
[[ "$MONTH_MIHOMO_RX" == 1220 && "$MONTH_MIHOMO_TX" == 1430 ]]
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

echo "=== reboot is detected even when ifindex is reused ==="
printf 'boot-B\n' >"$TMP/boot-id"
NOW=$((NOW+60))
setc awg0 9000 9100
setc mihomo0 3000 3100
run_traffic sample
. "$TMP/run/state.env"
[[ "$LAST_BOOT_ID" == boot-B ]]
[[ "$MONTH_AWG_RX" == 9050 && "$MONTH_AWG_TX" == 9150 ]]
[[ "$MONTH_MIHOMO_RX" == 3020 && "$MONTH_MIHOMO_TX" == 3120 ]]

echo "=== compact/full status are readable ==="
compact="$(run_traffic status compact)"
grep -Fq 'Сегодня:' <<<"$compact"
grep -Fq 'Месяц:' <<<"$compact"
full="$(run_traffic status full)"
grep -Fq 'трафик транспортных интерфейсов Pi' <<<"$full"
grep -Fq 'AWG:' <<<"$full"
grep -Fq 'Mihomo:' <<<"$full"
grep -Fq 'приём' <<<"$full"
grep -Fq 'передача' <<<"$full"
grep -Fq '21600 с' <<<"$full"

echo "=== status is read-only and does not require private state directories ==="
readonly_status="$(env \
  AWG_TRAFFIC_RUNTIME_DIR="/proc/awg-traffic-private-runtime-test" \
  AWG_TRAFFIC_PERSIST_DIR="/proc/awg-traffic-private-persist-test" \
  AWG_TRAFFIC_LOCK_FILE="/proc/awg-traffic-private-runtime-test/lock" \
  AWG_TRAFFIC_PUBLIC_STATE="$TMP/public.env" \
  bash "$ROOT/src/awg-traffic" status compact)"
grep -Fq 'Сегодня:' <<<"$readonly_status"
grep -Fq 'Месяц:' <<<"$readonly_status"
[[ ! -e /proc/awg-traffic-private-runtime-test ]]
[[ ! -e /proc/awg-traffic-private-persist-test ]]

echo "=== daemon releases lock so status remains readable ==="
NOW="$(date -d '2026-11-01 00:02:00 UTC' +%s)"
env \
  AWG_TRAFFIC_RUNTIME_DIR="$TMP/run" \
  AWG_TRAFFIC_PERSIST_DIR="$TMP/persist" \
  AWG_TRAFFIC_SYSFS_ROOT="$TMP/sys" \
  AWG_TRAFFIC_BOOT_ID_FILE="$TMP/boot-id" \
  AWG_TRAFFIC_PUBLIC_STATE="$TMP/public.env" \
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
  AWG_TRAFFIC_BOOT_ID_FILE="$TMP/boot-id" \
  AWG_TRAFFIC_PUBLIC_STATE="$TMP/public.env" \
  AWG_TRAFFIC_NOW_EPOCH="$NOW" \
  bash "$ROOT/src/awg-traffic" status compact >/dev/null
kill -TERM "$daemon_pid"
wait "$daemon_pid"

echo "low-write traffic accounting: OK"
