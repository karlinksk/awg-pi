#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'sudo rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/run"
: >"$TMP/run/maintenance.lock"
chmod 666 "$TMP/run/maintenance.lock"
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
cat >"$TMP/bin/node-policy" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_NODE_POLICY_LOG:?}"
case "${1:-}" in
  enabled)
    [[ "${MOCK_NODE_POLICY_ENABLED:-0}" == 1 ]]
    ;;
  failover)
    if [[ "${MOCK_NODE_FAILOVER_OK:-0}" == 1 ]]; then
      printf 'MIHOMO_NODE_FAILOVER=Finland->Finland backup\n'
      exit 0
    fi
    exit 1
    ;;
  *)
    exit 2
    ;;
esac
MOCK

cat >"$TMP/bin/fallback-guard" <<'MOCK'
#!/usr/bin/env bash
case "${MOCK_GUARD_STATE:-LEGACY}" in
  LEGACY) echo MONITOR_FALLBACK=LEGACY ;;
  NATIVE_OK) echo MONITOR_FALLBACK=NATIVE_OK ;;
  *) echo MONITOR_FALLBACK=NATIVE_UNSAFE; exit 20 ;;
esac
MOCK
cat >"$TMP/bin/transit-routing" <<'MOCK'
#!/usr/bin/env bash
printf 'quarantine:%s\n' "$1" >>"${MOCK_TRANSPORT_LOG:?}"
[[ "$1" != disable || "${MOCK_QUARANTINE_FAIL:-0}" != 1 ]] || exit 1
[[ "$1" != apply || "${MOCK_APPLY_FAIL:-0}" != 1 ]] || exit 1
MOCK
chmod +x "$TMP/bin/"*

run_policy(){
  sudo env     AWG_COMMON_FILE="$ROOT/src/awg-common"     AWG_TRANSPORT_FILE="$TMP/transport"     AWG_SELECTION_FILE="$TMP/selection.env"     AWG_TRANSPORT_CLI="$TMP/bin/transport"     MOCK_TRANSPORT_STATE="$TMP/transport"     MOCK_TRANSPORT_LOG="$TMP/log"     MOCK_NODE_POLICY_LOG="$TMP/node-policy.log"     MOCK_NODE_POLICY_ENABLED="${MOCK_NODE_POLICY_ENABLED:-0}"     MOCK_NODE_FAILOVER_OK="${MOCK_NODE_FAILOVER_OK:-0}"     MOCK_AWG_HEALTH="${MOCK_AWG_HEALTH:-up}"     MOCK_MIHOMO_HEALTH="${MOCK_MIHOMO_HEALTH:-up}"     bash "$ROOT/src/awg-selection" "$@"
}

run_monitor(){
  sudo env     AWG_COMMON_FILE="$ROOT/src/awg-common"     AWG_TRANSPORT_FILE="$TMP/transport"     AWG_SELECTION_FILE="$TMP/selection.env"     AWG_TRANSPORT_CLI="$TMP/bin/transport"     MIHOMO_NODE_POLICY_CLI="$TMP/bin/node-policy"     AWG_SELECTION_STATE_DIR="$TMP/run"     AWG_SELECTION_FAILURES="$TMP/run/failures"     AWG_LOCK_FILE="$TMP/run/maintenance.lock"     AWG_SELECTION_FAILURE_THRESHOLD=3     AWG_SELECTION_ONCE=1     AWG_MIHOMO_NATIVE_FALLBACK="${AWG_MIHOMO_NATIVE_FALLBACK:-0}"     AWG_MODE_FILE="$TMP/mode"     MIHOMO_FALLBACK_GUARD_CLI="${MIHOMO_FALLBACK_GUARD_CLI:-$TMP/bin/fallback-guard}"     AWG_TRANSIT_ROUTING_CLI="$TMP/bin/transit-routing"     MOCK_QUARANTINE_FAIL="${MOCK_QUARANTINE_FAIL:-0}"     MOCK_APPLY_FAIL="${MOCK_APPLY_FAIL:-0}"     MOCK_GUARD_STATE="${MOCK_GUARD_STATE:-$([[ "${AWG_MIHOMO_NATIVE_FALLBACK:-0}" == 1 ]] && echo NATIVE_OK || echo LEGACY)}"     LOGGER_BIN="$TMP/bin/logger"     MOCK_TRANSPORT_STATE="$TMP/transport"     MOCK_TRANSPORT_LOG="$TMP/log"     MOCK_NODE_POLICY_LOG="$TMP/node-policy.log"     MOCK_NODE_POLICY_ENABLED="${MOCK_NODE_POLICY_ENABLED:-0}"     MOCK_NODE_FAILOVER_OK="${MOCK_NODE_FAILOVER_OK:-0}"     MOCK_AWG_HEALTH="${MOCK_AWG_HEALTH:-up}"     MOCK_MIHOMO_HEALTH="${MOCK_MIHOMO_HEALTH:-up}"     bash "$ROOT/src/awg-selection-monitor"
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

echo "=== fallback activation is attempted even when standby health check is down ==="
run_policy mode fixed awg mihomo >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=down run_monitor || true
grep -Fqx 'select:mihomo' "$TMP/log"
grep -Fqx awg "$TMP/transport"
grep -Fqx '3' "$TMP/run/failures"

echo "=== healthy fallback is sticky; no automatic return to primary ==="
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"
MOCK_AWG_HEALTH=up MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx mihomo "$TMP/transport"

echo "=== AUTO is availability-only and obeys explicit allowed order ==="
run_policy mode auto awg mihomo >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
out="$(MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=awg->mihomo' <<<"$out"
grep -Fqx mihomo "$TMP/transport"
status="$(run_policy status)"
grep -Fqx 'Selection mode: auto' <<<"$status"
grep -Fqx 'Performance optimization: disabled (conservative AUTO)' <<<"$status"
grep -Fqx 'Mihomo node failover: separate explicit policy (no country inference)' <<<"$status"

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
printf '3\n' | sudo tee "$TMP/run/failures" >/dev/null
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor
[[ ! -s "$TMP/log" ]]
grep -Fqx awg "$TMP/transport"
grep -Fqx '0' "$TMP/run/failures"

echo "=== maintenance lock suppresses false failover during candidate/node transactions ==="
run_policy mode fixed awg mihomo >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
(
  flock -x 9
  MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor
) 9>"$TMP/run/maintenance.lock"
[[ ! -s "$TMP/log" ]]
grep -Fqx awg "$TMP/transport"
grep -Fqx '2' "$TMP/run/failures"

echo "=== exact-node recovery has priority over transport failover ==="
run_policy mode fixed mihomo awg >/dev/null
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
out="$(MOCK_MIHOMO_HEALTH=down MOCK_AWG_HEALTH=up MOCK_NODE_POLICY_ENABLED=1 MOCK_NODE_FAILOVER_OK=1 run_monitor)"
grep -Fqx 'MIHOMO_NODE_FAILOVER=Finland->Finland backup' <<<"$out"
grep -Fqx 'enabled' "$TMP/node-policy.log"
grep -Fqx 'failover' "$TMP/node-policy.log"
[[ ! -s "$TMP/log" ]]
grep -Fqx mihomo "$TMP/transport"
grep -Fqx '0' "$TMP/run/failures"

echo "=== transport fallback runs only after exact-node fallback fails ==="
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
out="$(MOCK_MIHOMO_HEALTH=down MOCK_AWG_HEALTH=up MOCK_NODE_POLICY_ENABLED=1 MOCK_NODE_FAILOVER_OK=0 run_monitor)"
grep -Fqx 'FAILOVER=mihomo->awg' <<<"$out"
grep -Fqx 'failover' "$TMP/node-policy.log"
grep -Fqx 'select:awg' "$TMP/log"
grep -Fqx awg "$TMP/transport"

echo "=== transport MANUAL still permits separately explicit node failover ==="
run_policy mode manual >/dev/null
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
printf '2\n' | sudo tee "$TMP/run/failures" >/dev/null
out="$(MOCK_MIHOMO_HEALTH=down MOCK_NODE_POLICY_ENABLED=1 MOCK_NODE_FAILOVER_OK=1 run_monitor)"
grep -Fqx 'MIHOMO_NODE_FAILOVER=Finland->Finland backup' <<<"$out"
[[ ! -s "$TMP/log" ]]
grep -Fqx mihomo "$TMP/transport"

echo "transport selection policy: OK"


echo "=== native fallback owns node decisions ==="
run_policy mode auto mihomo awg >/dev/null
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"
sudo truncate -s 0 "$TMP/node-policy.log"
rm -f "$TMP/run/failures"
for i in 1 2 3; do
  AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_NODE_POLICY_ENABLED=1 MOCK_NODE_FAILOVER_OK=1 MOCK_MIHOMO_HEALTH=down MOCK_AWG_HEALTH=up run_monitor >/dev/null
done
[[ ! -s "$TMP/node-policy.log" ]] || { echo 'native fallback unexpectedly invoked legacy node policy'; exit 1; }
grep -Fqx 'select:awg' "$TMP/log"
grep -Fqx awg "$TMP/transport"
echo "STAGE25_NATIVE_FALLBACK_PASS"


echo "=== AWG healthy remains sticky (no unapproved failback) ==="
run_policy mode auto mihomo awg >/dev/null
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
rm -f "$TMP/run/failures"
AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_AWG_HEALTH=up MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
[[ ! -s "$TMP/log" ]]
grep -Fqx awg "$TMP/transport"
echo STAGE25_AWG_STICKY_PASS

echo "=== AWG down recovers to Mihomo ==="
printf '%s\n' awg >"$TMP/transport"
: >"$TMP/log"
rm -f "$TMP/run/failures"
for i in 1 2; do
  AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
done
[[ ! -s "$TMP/log" ]]
out="$(AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=awg->mihomo' <<<"$out"
grep -Fqx mihomo "$TMP/transport"
echo STAGE25_AWG_RECOVERY_PASS

echo "=== both down never selects unhealthy transport ==="
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"
rm -f "$TMP/run/failures"
for i in 1 2 3 4; do
  AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_MIHOMO_HEALTH=down MOCK_AWG_HEALTH=down run_monitor >/dev/null
done
grep -Fqx mihomo "$TMP/transport"
echo STAGE25_BOTH_DOWN_NO_LEAKY_SWITCH_PASS


echo "=== Stage29 native safe owns node switching even without legacy flag ==="
run_policy mode auto mihomo awg >/dev/null
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
rm -f "$TMP/run/failures"
MOCK_GUARD_STATE=NATIVE_OK MOCK_NODE_POLICY_ENABLED=1 MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
[[ ! -s "$TMP/log" ]]
[[ ! -s "$TMP/node-policy.log" ]]
grep -Fqx mihomo "$TMP/transport"
echo STAGE29_NATIVE_DETECTED_SAFE

echo "=== Stage29 unsafe DIRECT quarantines before immediate AWG transition ==="
printf '%s
' transit >"$TMP/mode"
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
rm -f "$TMP/run/failures"
out="$(MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_NODE_POLICY_ENABLED=1 MOCK_NODE_FAILOVER_OK=1 MOCK_MIHOMO_HEALTH=up MOCK_AWG_HEALTH=up run_monitor)"
grep -Fqx 'FAILOVER=mihomo->awg' <<<"$out"
grep -Fqx awg "$TMP/transport"
[[ ! -s "$TMP/node-policy.log" ]]
[[ "$(sed -n '1p' "$TMP/log")" == 'quarantine:disable' ]]
[[ "$(sed -n '2p' "$TMP/log")" == 'select:awg' ]]
echo STAGE29_QUARANTINE_FIRST_PASS

echo "=== Stage29 failed AWG activation preserves lockdown ==="
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"; sudo truncate -s 0 "$TMP/node-policy.log"
out="$(MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_MIHOMO_HEALTH=up MOCK_AWG_HEALTH=down run_monitor)"
grep -Fqx 'NATIVE_FALLBACK=UNSAFE_TRANSIT_LOCKDOWN' <<<"$out"
grep -Fqx mihomo "$TMP/transport"
[[ "$(sed -n '1p' "$TMP/log")" == 'quarantine:disable' ]]
[[ "$(tail -1 "$TMP/log")" == 'quarantine:disable' ]]
echo STAGE29_AWG_FAILURE_LOCKDOWN_PASS

echo "=== Stage29 manual transport remains lockdown (no unsafe selection) ==="
run_policy mode manual >/dev/null
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"
out="$(MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_AWG_HEALTH=up run_monitor)"
grep -Fqx 'NATIVE_FALLBACK=UNSAFE_TRANSIT_LOCKDOWN' <<<"$out"
! grep -Fq select: "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
echo STAGE29_MANUAL_LOCKDOWN_PASS

echo "=== Stage29 quarantine failure rejects every transport change ==="
run_policy mode auto mihomo awg >/dev/null
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"
if MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_QUARANTINE_FAIL=1 MOCK_AWG_HEALTH=up run_monitor >/dev/null; then
  echo FAIL_QUARANTINE_NOT_ENFORCED >&2
  exit 1
fi
! grep -Fq select: "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
echo STAGE29_FAILED_LOCKDOWN_BLOCKS_SWITCH_PASS

echo "=== Stage29 inconsistent opt-in and legacy group quarantined ==="
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"
MOCK_GUARD_STATE=LEGACY AWG_MIHOMO_NATIVE_FALLBACK=1 MOCK_AWG_HEALTH=down run_monitor >/dev/null
grep -Fq 'quarantine:disable' "$TMP/log"
echo STAGE29_CONFLICTING_CONFIG_QUARANTINED_PASS


echo "=== Stage29 deny AWG->Mihomo when fallback DIRECT is unsafe ==="
run_policy mode auto awg mihomo >/dev/null
printf '%s
' awg >"$TMP/transport"
: >"$TMP/log"
printf '%s
' '2' | sudo tee "$TMP/run/failures" >/dev/null
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up MOCK_GUARD_STATE=NATIVE_UNSAFE run_monitor >/dev/null
! grep -Fq 'select:mihomo' "$TMP/log"
grep -Fqx awg "$TMP/transport"
echo STAGE29_AWG_TO_UNSAFE_MIHOMO_DENIED

echo "=== Stage29 restored DIRECT allows AWG->Mihomo after normal threshold ==="
: >"$TMP/log"
printf '%s
' '2' | sudo tee "$TMP/run/failures" >/dev/null
out="$(MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up MOCK_GUARD_STATE=NATIVE_OK run_monitor)"
grep -Fqx 'FAILOVER=awg->mihomo' <<<"$out"
grep -Fqx 'select:mihomo' "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
echo STAGE29_SAFE_UNDERLAY_PERMITS_RECOVERY

echo "=== Stage29 no helper on explicitly enabled native mode quarantines ==="
run_policy mode manual >/dev/null
printf '%s
' mihomo >"$TMP/transport"
: >"$TMP/log"
MOCK_AWG_HEALTH=down MOCK_MIHOMO_HEALTH=up AWG_MIHOMO_NATIVE_FALLBACK=1 MIHOMO_FALLBACK_GUARD_CLI="$TMP/bin/missing-guard" run_monitor >/dev/null
grep -Fq 'quarantine:disable' "$TMP/log"
grep -Fqx mihomo "$TMP/transport"
echo STAGE29_MISSING_HELPER_FAIL_CLOSED


echo "=== Stage29 native quarantine restores only after verified DIRECT recovery ==="
run_policy mode manual >/dev/null
printf '%s\n' transit >"$TMP/mode"
printf '%s\n' mihomo >"$TMP/transport"
: >"$TMP/log"
MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
test -e "$TMP/run/native-fallback-quarantine"
MOCK_GUARD_STATE=NATIVE_OK MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
grep -Fqx quarantine:apply "$TMP/log"
test ! -e "$TMP/run/native-fallback-quarantine"
echo STAGE29_DIRECT_RECOVERY_APPLY_PASS

echo "=== Stage29 rejected policy restore preserves lockdown marker ==="
: >"$TMP/log"
MOCK_GUARD_STATE=NATIVE_UNSAFE MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
test -e "$TMP/run/native-fallback-quarantine"
if MOCK_GUARD_STATE=NATIVE_OK MOCK_MIHOMO_HEALTH=up MOCK_APPLY_FAIL=1 run_monitor >/dev/null; then
  echo FAIL_RESTORED_WITH_FAILED_APPLY >&2; exit 1
fi
test -e "$TMP/run/native-fallback-quarantine"
echo STAGE29_FAILED_RECOVERY_RETAINS_LOCKDOWN

echo "=== Stage29 manual lockdown is never silently restored ==="
sudo rm -f "$TMP/run/native-fallback-quarantine"
: >"$TMP/log"
MOCK_GUARD_STATE=NATIVE_OK MOCK_MIHOMO_HEALTH=up run_monitor >/dev/null
! grep -Fq quarantine:apply "$TMP/log"
echo STAGE29_MANUAL_LOCKDOWN_NOT_AUTO_RESTORED
