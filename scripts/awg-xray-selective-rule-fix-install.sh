#!/usr/bin/env bash
# Test-Pi-only passive one-file correction after Selective Xray AUTO early AWG.
# No reboot, unit restart, canary activation or route modifications.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
OLD_SHA=d82b88437f02481f6c908d81c692809a1f55fd56b5d4da1f314c4d510234853d
NEW_SHA=e16c005fc6df42c5a000a752484f048e384084c115a543b9cede8c56e5edf8b5
FILE=/usr/local/sbin/awg-mihomo-node-policy
SRC="$ROOT/src/awg-mihomo-node-policy"
BACKUP="/var/backups/awg-gateway/xray-selective-rule-$(date -u +%Y%m%dT%H%M%S)-$$"
UNIT=awg-xray-selective-rule-rollback-$$
TIMER="$UNIT.timer"
ARMED=0
MUTATED=0
COMMITTED=0
sum(){ sha256sum "$1" | cut -d' ' -f1; }
die(){ echo "PATCH_ABORT=$1" >&2;exit 1; }
service(){ systemctl is-active --quiet "$1"; }
[[ "$EUID" == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_TEST_PI_ROOT
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die NOT_SELECTIVE
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == auto ]] || die NOT_NODE_AUTO
[[ "$(cat /etc/awg-pbr/transports/mihomo/ready-auto.mode)" == 0 ]] || die READY_NOT_OFF
[[ "$(cat /etc/awg-pbr/vpn-enabled)" == 1 ]] || die VPN_POLICY_DISABLED
[[ "$(/usr/local/sbin/awg-transport get)" == awg ]] || die AWG_NOT_SELECTED
[[ "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_NOT_HEALTHY
for u in ssh dnsmasq awg-quick@awg0 awg-selection-monitor awg-pbr-health;do
  service "$u" || die "SERVICE_DOWN_$u"
done
! service awg-xray-vless || die XRAY_ACTIVE
for t in 100 101;do
  ip -4 route show table "$t" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "ROUTE_$t"
done
[[ -f "$FILE" && ! -L "$FILE" && -f "$SRC" && ! -L "$SRC" ]] || die BAD_FILES
[[ "$(sum "$FILE")" == "$OLD_SHA" ]] || die INSTALLED_FILE_NOT_EXPECTED
[[ "$(sum "$SRC")" == "$NEW_SHA" ]] || die SOURCE_NOT_EXPECTED
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || die DIRTY_SOURCE
bash -n "$SRC" || die SYNTAX_FAILURE
[[ ! -e /run/systemd/system/awg-selection-monitor.service.d/95-xray-selective-canary.conf ]] || die OLD_CANARY_PRESENT
install -d -m 700 -o root -g root "$BACKUP"
cp -a -- "$FILE" "$BACKUP/original"
[[ "$(sum "$BACKUP/original")" == "$OLD_SHA" ]] || die BACKUP_HASH_MISMATCH
cat > "$BACKUP/restore.sh" <<'RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
snap="$(cd "$(dirname "$0")" && pwd -P)"
[[ "$(cat "$snap/state" 2>/dev/null || true)" == PENDING ]] || exit 0
orig=d82b88437f02481f6c908d81c692809a1f55fd56b5d4da1f314c4d510234853d
new=e16c005fc6df42c5a000a752484f048e384084c115a543b9cede8c56e5edf8b5
target=/usr/local/sbin/awg-mihomo-node-policy
exec 9>/run/awg-maintenance.lock
flock -x -w 30 9
current="$(sha256sum "$target" | cut -d' ' -f1)"
[[ "$current" == "$orig" || "$current" == "$new" ]] || { echo ROLLBACK=FOREIGN_CODE_REFUSED;exit 1; }
[[ "$(sha256sum "$snap/original" | cut -d' ' -f1)" == "$orig" ]] || exit 1
install -o root -g root -m 0755 "$snap/original" "$target.restore.$$"
mv -f "$target.restore.$$" "$target"
echo ROLLED_BACK > "$snap/state"
echo ROLLBACK=PASS
RESTORE
chmod 700 "$BACKUP/restore.sh"
echo PENDING > "$BACKUP/state"
cleanup(){
  result=$?
  trap - EXIT
  if (( COMMITTED == 0 ));then
    if (( MUTATED == 1 ));then
      "$BACKUP/restore.sh" || echo 'ROLLBACK=INCOMPLETE_TIMER_STILL_ARMED' >&2
    fi
    if (( ARMED == 1 )) && [[ "$(cat "$BACKUP/state")" != PENDING ]];then
      systemctl stop "$TIMER" >/dev/null 2>&1 || true
    fi
  fi
  exit "$result"
}
trap cleanup EXIT
systemd-run --quiet --collect --unit="$UNIT" --on-active=300s /bin/bash "$BACKUP/restore.sh" || die TIMER_FAILED
service "$TIMER" || die TIMER_INACTIVE
ARMED=1
echo PATCH_ROLLBACK_TIMER=ARMED_300S
exec 9>/run/awg-maintenance.lock
flock -x -w 15 9 || die MAINTENANCE_LOCK_BUSY
MUTATED=1
TMP="$FILE.patch.$$"
install -o root -g root -m 0755 "$SRC" "$TMP"
mv -f "$TMP" "$FILE"
flock -u 9
[[ "$(sum "$FILE")" == "$NEW_SHA" ]] || die NEW_HASH_MISMATCH
bash -n "$FILE"
for u in ssh dnsmasq awg-quick@awg0 awg-selection-monitor;do
  service "$u" || die "SERVICE_FAILED_$u"
done
[[ "$(/usr/local/sbin/awg-transport get)" == awg ]] || die TRANSPORT_CHANGED
[[ "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_NOT_HEALTHY_AFTER
for t in 100 101;do
  ip -4 route show table "$t" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "ROUTE_AFTER_$t"
done
systemctl stop "$TIMER" >/dev/null || die TIMER_DISARM_FAILED
! service "$TIMER" || die TIMER_STILL_RUNNING
echo COMMITTED > "$BACKUP/state"
COMMITTED=1
echo PATCH_INSTALL=PASS
echo "PATCH_BACKUP=$BACKUP"
echo XRAY_EXPERIMENT_CANARY=OFF
echo ACTIVE_TRANSPORT=AWG_UNCHANGED
