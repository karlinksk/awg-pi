#!/usr/bin/env bash
# TEST PI ONLY; simulated native-pool exhaustion; real monitor/TUN/AWG.
set -Eeuo pipefail
umask 077
backend=/usr/local/sbin/awg-transport
drop=/run/systemd/system/awg-selection-monitor.service.d/95-xray-selective-canary.conf
dir="$(mktemp -d /dev/shm/awg-xray-auto-test.XXXXXXXX)"
timer=awg-xray-auto-test-recover.timer
up(){ systemctl is-active --quiet "$1"; }
die(){ echo "ABORT=$1";exit 1; }
api(){ [[ "$(curl -q -4 --noproxy '*' --interface "$1" --connect-timeout 5 --max-time 13 -sS -o /dev/null -w '%{http_code}:%{ssl_verify_result}' https://api.openai.com/v1/models 2>/dev/null)" == 401:0 ]]; }
[[ $EUID == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_TESTPI_ROOT
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die NOT_SELECTIVE
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == auto ]] || die NOT_NODE_AUTO
[[ "$(cat /etc/awg-pbr/transports/mihomo/ready-auto.mode)" == 0 ]] || die READY_ON
[[ "$("$backend" get)" == mihomo ]] || die NOT_MIHOMO
[[ ! -e "$drop" ]] || die OVERRIDE_EXISTS
[[ ! -e /run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf ]] || die XRAY_BRIDGE
[[ ! -e /etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf ]] || die XRAY_BRIDGE
[[ ! -e /var/lib/awg-pbr/xray-vless/selected.json ]] || die XRAY_SELECTED
! up "$timer" && ! up awg-xray-vless || die OLD_TEST_RUNNING
for u in ssh dnsmasq awg-mihomo awg-quick@awg0 awg-selection-monitor awg-pbr-health;do up "$u" || die "SERVICE_$u";done
for t in 100 101;do ip -4 route show table "$t" | grep -Eq '^default +dev +mihomo0' || die "ROUTE_$t";done
for b in mihomo awg;do [[ "$("$backend" check "$b")" == healthy ]] || die "HEALTH_$b";done
api mihomo0 && api awg0 || die HTTPS_NOT_READY
# Cross-core AUTO consumes Xray evidence for only 600 seconds. Refuse an
# expired/changed profile before arming a fault; no stale cache->AWG false PASS.
# Run the isolated HTTPS check while both existing VPN paths are healthy.
echo '=== REFRESH_XRAY_HEALTH_CACHE ==='
/usr/local/sbin/awg-mihomo-unified-nodes probe-vless-all >/dev/null || die XRAY_PASSIVE_SCAN_FAILED
xray_candidate="$(/usr/local/sbin/awg-mihomo-unified-nodes best --engine XRAY 2>/dev/null)" || die XRAY_NO_FRESH_NETWORK_OK
[[ -n "$xray_candidate" ]] || die XRAY_NO_CANDIDATE
unset xray_candidate
echo 'XRAY_FRESH_NETWORK_OK=CONFIRMED'
[[ "$("$backend" get)" == mihomo ]] || die TRANSPORT_CHANGED_DURING_SCAN
api mihomo0 && api awg0 || die HTTPS_LOST_AFTER_SCAN
root="$(cd "$(dirname "$0")/.." && pwd -P)"
for file in src/awg-mihomo-node-policy src/awg-xray-live-backend.py src/awg-mihomo-unified-nodes.py;do
  name="$(basename "$file" .py)"
  cmp -s "$root/$file" "/usr/local/sbin/$name" || die "SOURCE_DIFFERENT_$name"
done
receipts=0
for snap in /var/backups/awg-gateway/xray-passive-*;do
  [[ -f "$snap/state" ]] || continue
  [[ "$(cat "$snap/state")" == COMMITTED ]] || continue
  for name in awg-mihomo-node-policy awg-xray-live-backend awg-mihomo-unified-nodes;do
    [[ -s "$snap/old/$name" ]] || die "BACKUP_INCOMPLETE_$name"
  done
  receipts=1
done
[[ $receipts == 1 ]] || die NO_VERIFIED_PASSIVE_BACKUP
echo 'PREFLIGHT=PASS BACKUP=VERIFIED'
cp -a /etc/awg-pbr/transports/mihomo/node-name "$dir/old-node"
cat >"$dir/recover" <<'RECOVER'
#!/usr/bin/env bash
set -Eeuo pipefail
drop=/run/systemd/system/awg-selection-monitor.service.d/95-xray-selective-canary.conf
if [[ -e "$drop" ]];then
  grep -Fq AWG_XRAY_TEST_OWNED "$drop" || exit 1
  rm -f "$drop"
  systemctl daemon-reload
fi
if [[ "$(/usr/local/sbin/awg-transport check awg 2>/dev/null || true)" == healthy ]];then
  if [[ "$(/usr/local/sbin/awg-transport get 2>/dev/null || true)" != awg ]];then
    /usr/local/sbin/awg-transport select awg
  fi
  echo RESTORE=AWG
else
  /usr/local/sbin/awg-pbr-failopen
  echo RESTORE=SELECTIVE_FAILOPEN
fi
systemctl restart awg-selection-monitor
RECOVER
chmod 700 "$dir/recover"
cat >"$dir/native-exhausted" <<'POOL'
#!/usr/bin/env bash
case "$1" in ensure|cooldown)exit 0;;best)exit 1;;*)exit 2;;esac
POOL
chmod 700 "$dir/native-exhausted"
# One-shot only: trace Node AUTO eligibility and return codes. Secrets stay
# inside a root-only tmpfs file and are never logged.
cat >"$dir/trace-node-policy" <<'TRACE'
#!/usr/bin/env bash
set -u
real=/usr/local/sbin/awg-mihomo-node-policy
dir="$(cd "$(dirname "$0")" && pwd -P)"
case "$1" in
  enabled)
    "$real" enabled >/dev/null 2>"$dir/enabled.err"
    result=$?
    if [[ $result == 0 ]];then
      logger -t awg-xray-auto 'PHASE=NODE_POLICY_ENABLED'
    else
      logger -t awg-xray-auto 'PHASE=NODE_POLICY_NOT_ENABLED'
    fi
    exit "$result"
    ;;
  failover)
    logger -t awg-xray-auto 'PHASE=NODE_FAILOVER_ENTER'
    if /usr/local/sbin/awg-mihomo-unified-nodes best --engine XRAY >/dev/null 2>&1;then
      logger -t awg-xray-auto 'PHASE=XRAY_CANDIDATE_FRESH'
    else
      logger -t awg-xray-auto 'PHASE=XRAY_CANDIDATE_MISSING'
    fi
    "$real" failover >"$dir/node.out" 2>"$dir/node.err"
    result=$?
    logger -t awg-xray-auto "PHASE=NODE_FAILOVER_RETURN_$result"
    if grep -Fq 'XRAY_SELECTIVE_BASELINE_UNSAFE_AWG_FALLBACK' "$dir/node.err";then
      logger -t awg-xray-auto 'PHASE=SELECTIVE_BASELINE_REJECTED'
    elif grep -Fq 'XRAY_SELECTIVE_FAILOPEN_FAILED_AWG_FALLBACK' "$dir/node.err";then
      logger -t awg-xray-auto 'PHASE=SELECTIVE_FAILOPEN_ERROR'
    elif grep -Fq 'XRAY_AUTO_TRANSACTION_ABORTED_AWG_FALLBACK' "$dir/node.err";then
      logger -t awg-xray-auto 'PHASE=XRAY_EXECUTOR_ABORTED'
    elif grep -Fq 'XRAY_AUTO_PREFLIGHT_REJECTED' "$dir/node.err";then
      logger -t awg-xray-auto 'PHASE=XRAY_DISPATCH_REJECTED'
    elif grep -Fq 'XRAY_TRANSACTION_EXECUTOR_MISSING' "$dir/node.err";then
      logger -t awg-xray-auto 'PHASE=XRAY_EXECUTOR_MISSING'
    fi
    cat "$dir/node.out"
    exit "$result"
    ;;
  *)
    exec "$real" "$@"
    ;;
esac
TRACE
chmod 0700 "$dir/trace-node-policy"
# A POSIX execute bit is insufficient: /run is often mounted noexec.
# Verify actual direct execution, not only test -x or unit Environment.
cat > "$dir/exec-preflight" <<'EXECGATE'
#!/usr/bin/env bash
exit 0
EXECGATE
chmod 0700 "$dir/exec-preflight"
"$dir/exec-preflight" || die TEMP_RUNTIME_NOEXEC
rm -f "$dir/exec-preflight"
echo 'CANARY_TMPFS_EXEC=PASS'
# Verify that the exact AUTO eligibility probe works with the injected helper.
# This runs before arming the timer or stopping Mihomo.
MIHOMO_POOL_CLI="$dir/native-exhausted" /usr/local/sbin/awg-mihomo-node-policy enabled >/dev/null ||
  die NODE_AUTO_PRECHECK_NOT_ENABLED
echo 'NODE_AUTO_PRECHECK=PASS'
systemd-run --quiet --collect --unit=awg-xray-auto-test-recover --on-active=420s /bin/bash "$dir/recover" || die WATCHDOG_NOT_ARMED
up "$timer" || die WATCHDOG_NOT_ACTIVE
echo 'WATCHDOG=ARMED_420S'
cleanup(){
  rc=$?
  trap - EXIT
  if bash "$dir/recover";then
    systemctl stop "$timer" >/dev/null 2>&1 || true
    echo 'RECOVERY_SCRIPT=PASS'
  else
    echo 'RECOVERY_SCRIPT=FAILED_TIMER_LEFT_ARMED'
    rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
install -d -m 755 "$(dirname "$drop")"
cat >"$drop" <<CONF
# AWG_XRAY_TEST_OWNED
[Service]
Environment="MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1"
Environment="MIHOMO_XRAY_SELECTIVE_CANARY=1"
Environment="MIHOMO_POOL_CLI=$dir/native-exhausted"
Environment="MIHOMO_NODE_POLICY_CLI=$dir/trace-node-policy"
CONF
systemctl daemon-reload
systemctl restart awg-selection-monitor
effective="$(systemctl show awg-selection-monitor.service -p Environment --value)"
[[ "$effective" == *"MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1"* &&
   "$effective" == *"MIHOMO_XRAY_SELECTIVE_CANARY=1"* &&
   "$effective" == *"MIHOMO_POOL_CLI=$dir/native-exhausted"* &&
   "$effective" == *"MIHOMO_NODE_POLICY_CLI=$dir/trace-node-policy"* ]] ||
   die CANARY_EFFECTIVE_ENVIRONMENT_NOT_APPLIED
unset effective
echo 'CANARY=ACTIVE_MONITOR_ONLY'
systemctl stop awg-mihomo
echo 'FAULT=MIHOMO_STOP'
first=TIMEOUT
for i in $(seq 1 60);do
  if [[ "$("$backend" get 2>/dev/null || true)" == awg ]];then first=AWG_EARLY;break;fi
  if up awg-xray-vless && up awg-mihomo && api mihomo0;then first=XRAY_TUN;break;fi
  sleep 3
done
echo "FIRST_RESULT=$first"
echo '=== NODE_AUTO_SAFE_TRACE ==='
journalctl -t awg-xray-auto --since '-8 minutes' -o cat --no-pager 2>/dev/null |
  grep -E '^PHASE=[A-Z0-9_]+$' | tail -n 25 || true
echo '=== XRAY_SELECTIVE_PREACTIVATION_DIAGNOSTIC ==='
# Fixed status strings only, no subscription URLs, node names or credentials.
if journalctl -t awg-xray-auto --since '-9 minutes' -o cat --no-pager 2>/dev/null | grep -F 'SELECTIVE_FAILOPEN=PREPARED_BEFORE_XRAY' >/dev/null; then
  echo 'XRAY_SELECTIVE_PREACTIVATION=OBSERVED'
else
  echo 'XRAY_SELECTIVE_PREACTIVATION=NOT_OBSERVED'
fi

if [[ "$first" == XRAY_TUN ]];then
  echo 'XRAY_TUN_HTTPS=PASS'
  systemctl stop awg-xray-vless
  echo 'FAULT=XRAY_STOP'
  second=TIMEOUT
  for i in $(seq 1 30);do
    if [[ "$("$backend" get 2>/dev/null || true)" == awg ]];then second=AWG;break;fi
    sleep 3
  done
  echo "SECOND_RESULT=$second"
fi
bash "$dir/recover"
[[ "$("$backend" get)" == awg ]] && api awg0 || die AWG_POSTCHECK
for u in ssh dnsmasq awg-selection-monitor awg-quick@awg0;do up "$u" || die "POST_SERVICE_$u";done
echo 'FINAL_AWG_HTTPS=PASS'
echo "REPORT_DIR=$dir"
echo 'RESTORE_ORIGINAL_MIHOMO_NODE=FOLLOWUP'
