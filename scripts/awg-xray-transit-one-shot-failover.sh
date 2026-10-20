#!/usr/bin/env bash
# TEST PI ONLY; guarded Transit dual-fault then Selective recovery.
set -Eeuo pipefail
umask 077
backend=/usr/local/sbin/awg-transport
drop=/run/systemd/system/awg-selection-monitor.service.d/95-xray-transit-canary.conf
dir="$(mktemp -d /dev/shm/awg-xray-auto-test.XXXXXXXX)"
timer=awg-xray-auto-test-recover.timer
up(){ systemctl is-active --quiet "$1"; }
die(){ echo "ABORT=$1";exit 1; }
api(){ [[ "$(curl -q -4 --noproxy '*' --interface "$1" --connect-timeout 5 --max-time 13 -sS -o /dev/null -w '%{http_code}:%{ssl_verify_result}' https://api.openai.com/v1/models 2>/dev/null)" == 401:0 ]]; }
[[ $EUID == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_TESTPI_ROOT
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die NOT_SELECTIVE_ORIGIN
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
install -o root -g root -m 0700 "$root/scripts/awg-xray-selective-test-cleanup.sh" "$dir/test-cleanup"
cat >"$dir/recover" <<'RECOVER'
#!/usr/bin/env bash
set -Eeuo pipefail
drop=/run/systemd/system/awg-selection-monitor.service.d/95-xray-transit-canary.conf
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
  echo RESTORE_AWG_UNHEALTHY=YES
fi
# Always move back to the original Selective before invoking the
# Selective-only root cleanup. Never issue fail-open while Transit.
if [[ "$(cat /etc/awg-pbr/mode)" == transit ]];then
  /usr/local/sbin/awg-route mode selective || exit 1
fi
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || exit 1
if [[ "$(/usr/local/sbin/awg-transport check awg 2>/dev/null || true)" != healthy ]];then
  /usr/local/sbin/awg-pbr-failopen
  echo RESTORE=SELECTIVE_FAILOPEN
fi
# Remove test-owned persistent bridge only AFTER healthy AWG takeover.
# The helper refuses foreign artifacts, active Mihomo and bad AWG routes.
if [[ "$(/usr/local/sbin/awg-transport get 2>/dev/null || true)" == awg ]];then
  dir="$(cd "$(dirname "$0")" && pwd -P)"
  XRAY_TEST_RECOVER_ACTIVE=1 "$dir/test-cleanup" "$dir" || exit 1
  echo XRAY_TEST_CLEANUP=PASS
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
echo WATCHDOG=ARMED_BEFORE_TRANSIT
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
/usr/local/sbin/awg-route mode transit || die TRANSIT_SWITCH_FAILED
[[ "$(cat /etc/awg-pbr/mode)" == transit ]] || die TRANSIT_MODE_NOT_SET
transit_status="$(/usr/local/sbin/awg-transit-routing status)" || die TRANSIT_STATUS_UNAVAILABLE
# Capture the exact three-line status before rejecting, not a transient or
# separately sampled state. Both SAFE and active policy/route are required.
if ! grep -Fqx 'Transit guard: SAFE' <<<"$transit_status" ||
   ! grep -Fqx 'Transit policy rule: ACTIVE' <<<"$transit_status" ||
   ! grep -Fqx 'Transit VPN table: READY' <<<"$transit_status";then
  printf '%s\n' "$transit_status"
  die TRANSIT_BASELINE_NOT_READY
fi
echo TRANSIT_BASELINE=PASS
up "$timer" || die WATCHDOG_NOT_ACTIVE
echo 'WATCHDOG=ARMED_420S'

install -d -m 755 "$(dirname "$drop")"
cat >"$drop" <<CONF
# AWG_XRAY_TEST_OWNED
[Service]
Environment="MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1"
Environment="MIHOMO_XRAY_SELECTIVE_CANARY=0"
Environment="MIHOMO_POOL_CLI=$dir/native-exhausted"
Environment="MIHOMO_NODE_POLICY_CLI=$dir/trace-node-policy"
CONF
systemctl daemon-reload
systemctl restart awg-selection-monitor
effective="$(systemctl show awg-selection-monitor.service -p Environment --value)"
[[ "$effective" == *"MIHOMO_XRAY_AUTO_FAILOVER_CANARY=1"* &&
   "$effective" == *"MIHOMO_XRAY_SELECTIVE_CANARY=0"* &&
   "$effective" == *"MIHOMO_POOL_CLI=$dir/native-exhausted"* &&
   "$effective" == *"MIHOMO_NODE_POLICY_CLI=$dir/trace-node-policy"* ]] ||
   die CANARY_EFFECTIVE_ENVIRONMENT_NOT_APPLIED
unset effective
echo 'CANARY=ACTIVE_MONITOR_ONLY'
systemctl stop awg-mihomo
echo 'FAULT=MIHOMO_STOP'
# A live SOCKS or TUN HTTP401 is NOT proof of a committed cross-core switch.
# Require the executor's committed snapshot (created after route + boot checks),
# this exact test's timestamp, and Mihomo's selected Xray bridge.
test_started="$(date +%s)"
xray_transaction_committed(){
  XRAY_TEST_STARTED="$test_started" python3 -B - <<'PY'
import json,os,time,urllib.request
from pathlib import Path
begin=int(os.environ["XRAY_TEST_STARTED"])
try:
    request=urllib.request.Request("http://127.0.0.1:9090/proxies/AWG-MIHOMO")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=3) as res:
        if json.load(res).get("now")!="AWG-XRAY-VLESS-LOCAL":
            raise SystemExit(1)
    base=Path("/var/backups/awg-gateway")
    for snap in base.glob("xray-failover-*"):
        if not snap.is_dir() or snap.is_symlink():
            continue
        pieces=snap.name.split("-")
        if len(pieces)!=4:
            continue
        timestamp=int(pieces[2])
        if timestamp<begin-3 or timestamp>int(time.time())+3:
            continue
        if json.loads((snap/"state.json").read_text()).get("state")=="committed":
            raise SystemExit(0)
except (OSError,ValueError,TypeError,KeyError,TimeoutError):
    pass
raise SystemExit(1)
PY
}
first=TIMEOUT
for i in $(seq 1 60);do
  if [[ "$("$backend" get 2>/dev/null || true)" == awg ]];then first=AWG_EARLY;break;fi
  if up awg-xray-vless && up awg-mihomo && api mihomo0 &&
     xray_transaction_committed;then first=XRAY_TUN;break;fi
  sleep 3
done
echo "FIRST_RESULT=$first"
echo '=== NODE_AUTO_SAFE_TRACE ==='
journalctl -t awg-xray-auto --since '-8 minutes' -o cat --no-pager 2>/dev/null |
  grep -E '^PHASE=[A-Z0-9_]+$' | tail -n 25 || true
echo '=== XRAY_TRANSIT_POSTFAULT_DIAGNOSTIC ==='
# Fixed status strings only, no subscription URLs, node names or credentials.
if journalctl -t awg-xray-auto --since '-9 minutes' -o cat --no-pager 2>/dev/null | grep -F 'SELECTIVE_FAILOPEN=PREPARED_BEFORE_XRAY' >/dev/null; then
  echo 'XRAY_SELECTIVE_PREACTIVATION=OBSERVED'
else
  echo 'XRAY_SELECTIVE_PREACTIVATION=NOT_OBSERVED'
fi

# This is a strict observation before recover() may explicitly select AWG.
# A name-only selected transport, failed SSH/DNS, stale routes, and no HTTPS
# cannot be reported as automatic Xray->AWG failover success.
automatic_awg_recovery_verified(){
  local policy
  [[ "$("$backend" get 2>/dev/null || true)" == awg ]] || { recovery_reason=TRANSPORT;return 1; }
  for svc in awg-quick@awg0 awg-selection-monitor ssh dnsmasq;do
    up "$svc" || { recovery_reason=SERVICE;return 1; }
  done
  ! up awg-xray-vless && ! up awg-mihomo || { recovery_reason=OLD_ENGINE_ACTIVE;return 1; }
  [[ "$(cat /etc/awg-pbr/mode)" == transit ]] || { recovery_reason=MODE;return 1; }
  policy="$(/usr/local/sbin/awg-transit-routing status 2>/dev/null)" || { recovery_reason=TRANSIT_STATUS;return 1; }
  grep -Fqx 'Transit guard: SAFE' <<<"$policy" || { recovery_reason=GUARD;return 1; }
  grep -Fqx 'Transit policy rule: ACTIVE' <<<"$policy" || { recovery_reason=POLICY;return 1; }
  grep -Fqx 'Transit VPN table: READY' <<<"$policy" || { recovery_reason=VPN_TABLE;return 1; }
  for table in 100 101;do
    ip -4 route show table "$table" |
      grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' ||
      { recovery_reason=ROUTE;return 1; }
  done
  api awg0 || { recovery_reason=HTTPS;return 1; }
  recovery_reason=PASS
}

# Bounded, non-secret snapshot; never claim AWG recovery from a log line alone.
transit_recovery_diagnostic(){
  local value t state line
  value="$("$backend" get 2>/dev/null || true)"
  case "$value" in awg|mihomo|unconfigured) ;; *) value=UNKNOWN;; esac
  echo "RECOVERY_TRANSPORT=$value"
  for t in awg-quick@awg0 awg-selection-monitor ssh dnsmasq awg-mihomo awg-xray-vless;do
    if up "$t";then state=ACTIVE;else state=INACTIVE;fi
    echo "RECOVERY_UNIT_${t//[^a-zA-Z0-9]/_}=$state"
  done
  value="$(cat /etc/awg-pbr/mode 2>/dev/null || true)"
  case "$value" in selective|transit) ;; *)value=UNKNOWN;;esac
  echo "RECOVERY_MODE=$value"
  value="$(/usr/local/sbin/awg-transit-routing status 2>/dev/null || true)"
  for line in 'Transit guard:' 'Transit policy rule:' 'Transit VPN table:';do
    state="$(grep -F "$line" <<<"$value" | head -n1 || true)"
    case "$state" in
      'Transit guard: SAFE'|'Transit guard: LOCKDOWN'|'Transit guard: UNSAFE'|      'Transit policy rule: ACTIVE'|'Transit policy rule: INACTIVE'|      'Transit VPN table: READY'|'Transit VPN table: NOT_READY') ;;
      *) state="$line UNKNOWN";;
    esac
    case "$line" in
      'Transit guard:') echo "RECOVERY_GUARD=${state#Transit guard: }";;
      'Transit policy rule:') echo "RECOVERY_POLICY=${state#Transit policy rule: }";;
      'Transit VPN table:') echo "RECOVERY_VPN_TABLE=${state#Transit VPN table: }";;
    esac
  done
  for t in 100 101;do
    value="$(ip -4 route show table "$t" 2>/dev/null || true)"
    if grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' <<<"$value";then state=AWG;
    elif grep -Eq '^default[[:space:]]+dev[[:space:]]+mihomo0([[:space:]]|$)' <<<"$value";then state=MIHOMO;
    else state=OTHER_OR_EMPTY;fi
    echo "RECOVERY_ROUTE_${t}=$state"
  done
  if api awg0;then echo RECOVERY_AWG_HTTPS=PASS;else echo RECOVERY_AWG_HTTPS=FAIL;fi
}
second=NOT_RUN
if [[ "$first" == XRAY_TUN ]];then
  echo 'XRAY_TUN_HTTPS=PASS'
  systemctl stop awg-xray-vless
  ! up awg-xray-vless || die XRAY_FAULT_DID_NOT_STOP
  echo 'FAULT=XRAY_STOP'
  second=TIMEOUT
  recovery_reason=UNSET
  for i in $(seq 1 30);do
    if automatic_awg_recovery_verified;then second=AWG;break;fi
    sleep 3
  done
  # A completed recovery can become observable immediately after the last
  # scheduled poll. One final complete predicate before declaring TIMEOUT.
  if [[ "$second" == TIMEOUT ]] && automatic_awg_recovery_verified;then
    second=AWG
    echo SECOND_RESULT_SOURCE=FINAL_POST_POLL_VERIFICATION
  fi
  echo "SECOND_RESULT=$second"
  echo "SECOND_LAST_PREDICATE=$recovery_reason"
  echo "=== SECOND_FAULT_DIAGNOSTIC ==="
  transit_recovery_diagnostic
fi
failclosed_checked=0
if [[ "$second" == AWG ]];then
  # With healthy standby, briefly disarm Transit policy using its native guard.
  # A missing rule alone is not proof: require SAFE/LOCKDOWN and INACTIVE.
  /usr/local/sbin/awg-transit-routing disable || die TRANSIT_DISABLE_FAILED
  status="$(/usr/local/sbin/awg-transit-routing status)"
  grep -Fqx 'Transit policy rule: INACTIVE' <<<"$status" || die FAILCLOSED_RULE_STILL_ACTIVE
  grep -Eq '^Transit guard: (SAFE|LOCKDOWN)$' <<<"$status" || die FAILCLOSED_GUARD_MISSING
  echo TRANSIT_FAIL_CLOSED_GUARD_STATE=PASS_NOT_PACKET_TEST
  failclosed_checked=1
  /usr/local/sbin/awg-transit-routing apply || die TRANSIT_REARM_FAILED
fi
bash "$dir/recover"
[[ "$("$backend" get)" == awg ]] && api awg0 || die AWG_POSTCHECK
for u in ssh dnsmasq awg-selection-monitor awg-quick@awg0;do up "$u" || die "POST_SERVICE_$u";done
! up awg-xray-vless || die XRAY_SIDECAR_LEFT_RUNNING
[[ "$(systemctl is-enabled awg-xray-vless 2>/dev/null || true)" == disabled ]] || die XRAY_SIDECAR_LEFT_ENABLED
for table in 100 101;do
  ip -4 route show table "$table" |
    grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "AWG_ROUTE_POST_$table"
done
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die SELECTIVE_NOT_RESTORED
echo 'FINAL_AWG_HTTPS=PASS'
if [[ "$first" != XRAY_TUN || "$second" != AWG || "$failclosed_checked" != 1 ]];then
  echo 'TRANSIT_XRAY_AUTO_FAILOVER=NOT_VERIFIED'
  exit 1
fi
echo 'TRANSIT_XRAY_AUTO_FAILOVER=PASS_PI_TUN_AND_GUARD_ONLY'
echo 'TRANSIT_LAN_PACKET_FAILCLOSED=NOT_TESTED'
echo "REPORT_DIR=$dir"
echo 'RESTORE_ORIGINAL_MIHOMO_NODE=FOLLOWUP'
