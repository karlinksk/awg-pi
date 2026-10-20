#!/usr/bin/env bash
# TEST-PI ONLY: passive one-file Xray Selective commit recheck hotfix.
# No service stop/start, no route/DNS/SSH/MikroTik mutation.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
TARGET=/usr/local/sbin/awg-xray-live-backend
SOURCE="$ROOT/src/awg-xray-live-backend.py"
OLD=ee60c9736c162475923d580d88e7b10ae95db2020abb74b2d1887ef973c889cc
NEW=61f3d3143ddc5ce2ac00a292014ee752cb17ae90a9a2c9109ed89a271108165c
BACKUP="/var/backups/awg-gateway/xray-selective-commit-$(date -u +%Y%m%dT%H%M%S)-$$"
UNIT="awg-xray-warmup-rollback-$$"
TIMER="$UNIT.timer"
armed=0
mutated=0
committed=0
die(){ echo "XRAY_WARMUP_INSTALL_ABORT=$1" >&2;exit 1; }
hash(){ sha256sum "$1" | cut -d' ' -f1; }
up(){ systemctl is-active --quiet "$1"; }
[[ $EUID == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_ROOT_TEST_PI
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die NOT_SELECTIVE
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == auto ]] || die NOT_NODE_AUTO
[[ "$(/usr/local/sbin/awg-transport get)" == awg ]] || die AWG_NOT_SELECTED
[[ "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_UNHEALTHY
for s in awg-quick@awg0 awg-selection-monitor awg-pbr-health ssh dnsmasq;do
  up "$s" || die "REQUIRED_SERVICE_DOWN_$s"
done
! up awg-xray-vless || die XRAY_LIVE
[[ ! -e /run/systemd/system/awg-selection-monitor.service.d/95-xray-selective-canary.conf ]] || die CANARY_LIVE
[[ ! -e /var/lib/awg-pbr/xray-vless/selected.json ]] || die XRAY_SELECTED
[[ ! -e /etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf ]] || die XRAY_BOOT_BRIDGE
if systemctl list-timers --all --no-pager --no-legend | grep -Eq 'awg-xray-(auto-test-recover|failover-[0-9]+|warmup-rollback-).*\.timer';then
  die ACTIVE_OR_STALE_XRAY_WATCHDOG
fi
for tab in 100 101;do
  ip -4 route show table "$tab" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' ||
    die "AWG_ROUTE_$tab"
done
[[ -f "$TARGET" && ! -L "$TARGET" && -f "$SOURCE" && ! -L "$SOURCE" ]] || die SOURCE_OR_TARGET_MISSING
[[ "$(hash "$TARGET")" == "$OLD" ]] || die INSTALLED_BASELINE_CHANGED
[[ "$(hash "$SOURCE")" == "$NEW" ]] || die SOURCE_HASH_CHANGED
python3 -B - "$SOURCE" <<'PY'
import ast,sys
ast.parse(open(sys.argv[1],encoding="utf-8").read())
PY
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || die SOURCE_DIRTY
install -d -o root -g root -m 0700 "$BACKUP"
cp -a -- "$TARGET" "$BACKUP/original"
[[ "$(hash "$BACKUP/original")" == "$OLD" ]] || die BACKUP_INTEGRITY
cat >"$BACKUP/restore.sh" <<'RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
snap="$(cd "$(dirname "$0")" && pwd -P)"
[[ "$(cat "$snap/state" 2>/dev/null || true)" == PENDING ]] || exit 0
target=/usr/local/sbin/awg-xray-live-backend
old=ee60c9736c162475923d580d88e7b10ae95db2020abb74b2d1887ef973c889cc
new=61f3d3143ddc5ce2ac00a292014ee752cb17ae90a9a2c9109ed89a271108165c
exec 9>/run/awg-maintenance.lock
flock -x -w 30 9
current="$(sha256sum "$target" | cut -d' ' -f1)"
[[ "$current" == "$old" || "$current" == "$new" ]] || { echo XRAY_ROLLBACK=FOREIGN_FILE_REFUSED;exit 1; }
[[ "$(sha256sum "$snap/original" | cut -d' ' -f1)" == "$old" ]] || exit 1
install -o root -g root -m 0755 "$snap/original" "$target.rollback.$$"
mv -f -- "$target.rollback.$$" "$target"
printf 'ROLLED_BACK\n' >"$snap/state"
echo XRAY_ROLLBACK=PASS
RESTORE
chmod 0700 "$BACKUP/restore.sh"
printf 'PENDING\n' >"$BACKUP/state"
cleanup(){
  rc=$?
  trap - EXIT
  if (( committed == 0 ));then
    if (( mutated == 1 ));then
      "$BACKUP/restore.sh" || echo XRAY_ROLLBACK=FAILED_WATCHDOG_REMAINS >&2
    fi
    if (( armed == 1 )) && [[ "$(cat "$BACKUP/state")" != PENDING ]];then
      systemctl stop "$TIMER" >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT
systemd-run --quiet --collect --unit="$UNIT" --on-active=300s /bin/bash "$BACKUP/restore.sh" ||
  die WATCHDOG_ARM_FAILED
up "$TIMER" || die WATCHDOG_NOT_ACTIVE
armed=1
echo XRAY_WARMUP_ROLLBACK=ARMED_300S
exec 9>/run/awg-maintenance.lock
flock -x -w 15 9 || die MAINTENANCE_LOCK_BUSY
mutated=1
install -o root -g root -m 0755 "$SOURCE" "$TARGET.new.$$"
mv -f -- "$TARGET.new.$$" "$TARGET"
flock -u 9
[[ "$(hash "$TARGET")" == "$NEW" ]] || die NEW_HASH_MISMATCH
for s in awg-quick@awg0 awg-selection-monitor awg-pbr-health ssh dnsmasq;do
  up "$s" || die "POST_SERVICE_$s"
done
[[ "$(/usr/local/sbin/awg-transport get)" == awg &&
   "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_STATE_CHANGED
for tab in 100 101;do
  ip -4 route show table "$tab" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' ||
    die "AWG_POST_ROUTE_$tab"
done
systemctl stop "$TIMER" >/dev/null || die WATCHDOG_STOP_FAILED
! up "$TIMER" || die WATCHDOG_NOT_DISARMED
printf 'COMMITTED\n' >"$BACKUP/state"
committed=1
echo XRAY_WARMUP_INSTALL=PASS
echo "XRAY_WARMUP_BACKUP=$BACKUP"
echo XRAY_EXPERIMENT=NOT_ACTIVATED
echo ACTIVE_TRANSPORT=AWG_UNCHANGED
