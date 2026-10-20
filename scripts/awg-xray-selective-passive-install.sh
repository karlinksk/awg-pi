#!/usr/bin/env bash
# PASSIVE install on test Pi only. Never enable canaries, restart units, or change routes.
set -Eeuo pipefail
umask 077
repo="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
root=/usr/local/sbin
backuproot=/var/backups/awg-gateway
snap="$backuproot/xray-passive-$(date -u +%Y%m%dT%H%M%S)-$$"
unit="awg-xray-passive-rollback-$$"
timer="$unit.timer"
mutated=0
committed=0
armed=0
die(){ echo "PASSIVE_INSTALL=ABORT_$1" >&2; exit 1; }
hash14(){ sha256sum "$1" | cut -c1-14; }
healthy(){ systemctl is-active --quiet "$1"; }
verify_routes(){
  for table in 100 101;do
    result="$(ip -4 route show table "$table")" || return 1
    [[ "$result" =~ ^default[[:space:]]+dev[[:space:]]+mihomo0([[:space:]].*)?$ ]] || return 1
  done
}
source_for(){
  case "$1" in
    awg-mihomo-node-policy) echo src/awg-mihomo-node-policy;;
    awg-xray-live-backend) echo src/awg-xray-live-backend.py;;
    awg-mihomo-unified-nodes) echo src/awg-mihomo-unified-nodes.py;;
    *) return 1;;
  esac
}
baseline_for(){
  case "$1" in
    awg-mihomo-node-policy) echo 0c0577f3941773;;
    awg-xray-live-backend) echo bdea36459bc009;;
    awg-mihomo-unified-nodes) echo 0ac8272bd2c68d;;
    *) return 1;;
  esac
}
names="awg-mihomo-node-policy awg-xray-live-backend awg-mihomo-unified-nodes"
[[ "$EUID" == 0 && "$(hostname)" == awg-upgrade ]] || die WRONG_MACHINE
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die NOT_SELECTIVE
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == auto ]] || die NODE_AUTO_CHANGED
[[ "$(cat /etc/awg-pbr/transports/mihomo/ready-auto.mode)" == 0 ]] || die READY_CHANGED
[[ "$(/usr/local/sbin/awg-transport get)" == mihomo ]] || die TRANSPORT_CHANGED
for backend in mihomo awg;do
  [[ "$(/usr/local/sbin/awg-transport check "$backend")" == healthy ]] || die "BACKEND_NOT_HEALTHY_$backend"
done
for svc in ssh dnsmasq awg-mihomo awg-quick@awg0 awg-selection-monitor awg-pbr-health;do
  healthy "$svc" || die "SERVICE_DOWN_$svc"
done
! healthy awg-xray-vless || die XRAY_ACTIVE
! healthy awg-mihomo-hot-pool.timer || die HOTPOOL_ACTIVE
verify_routes || die FOREIGN_ROUTES
[[ -d "$repo/.git" ]] || die NOT_CHECKOUT
[[ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ]] || die WORKTREE_DIRTY
for name in $names;do
  old="$root/$name"
  new="$repo/$(source_for "$name")"
  [[ -f "$old" && ! -L "$old" && -f "$new" && ! -L "$new" ]] || die "MISSING_FILE_$name"
  [[ "$(hash14 "$old")" == "$(baseline_for "$name")" ]] || die "BASELINE_CHANGED_$name"
done
bash -n "$repo/src/awg-mihomo-node-policy" || die SYNTAX_FAIL
for name in awg-xray-live-backend awg-mihomo-unified-nodes;do
  python3 -B -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' "$repo/$(source_for "$name")" || die PY_SYNTAX_FAIL
done
echo "PASSIVE_PREFLIGHT=PASS"
install -d -o root -g root -m 0700 "$backuproot" "$snap" "$snap/old"
for name in $names;do
  cp -a "$root/$name" "$snap/old/$name"
  sha256sum "$repo/$(source_for "$name")" | cut -d' ' -f1 >"$snap/new-$name.sha"
  [[ "$(hash14 "$snap/old/$name")" == "$(baseline_for "$name")" ]] || die BACKUP_FAILED
done
cat >"$snap/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
snap="$(cd -- "$(dirname -- "$0")" && pwd -P)"
[[ "$(cat "$snap/state" 2>/dev/null || true)" == PENDING ]] || exit 0
exec 9>/run/awg-maintenance.lock
flock -x -w 30 9
names="awg-mihomo-node-policy awg-xray-live-backend awg-mihomo-unified-nodes"
for name in $names;do
  target="/usr/local/sbin/$name"
  original="$(sha256sum "$snap/old/$name" | cut -d' ' -f1)"
  intended="$(cat "$snap/new-$name.sha")"
  current="$(sha256sum "$target" | cut -d' ' -f1)"
  [[ "$current" == "$original" || "$current" == "$intended" ]] || {
    echo "ROLLBACK=REFUSED_FOREIGN_FILE:$name" >&2
    exit 1
  }
done
for name in $names;do
  tmp="/usr/local/sbin/.$name.rollback.$$"
  install -o root -g root -m 0755 "$snap/old/$name" "$tmp"
  mv -f "$tmp" "/usr/local/sbin/$name"
done
echo ROLLED_BACK >"$snap/state"
echo ROLLBACK=PASS
ROLLBACK
chmod 0700 "$snap/rollback.sh"
echo PENDING >"$snap/state"
cleanup(){
  rc=$?
  trap - EXIT
  if (( committed == 0 ));then
    flock -u 9 2>/dev/null || true
    if (( mutated == 1 ));then
      /bin/bash "$snap/rollback.sh" || echo 'ROLLBACK=INCOMPLETE_TIMER_PRESERVED' >&2
    fi
    if (( armed == 1 ));then
      [[ "$(cat "$snap/state")" != PENDING ]] && systemctl stop "$timer" >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT
systemd-run --quiet --collect --unit="$unit" --on-active=300s \
  /bin/bash "$snap/rollback.sh" || die TIMER_FAILED
healthy "$timer" || die TIMER_NOT_ACTIVE
armed=1
echo PASSIVE_WATCHDOG=ARMED_300S
exec 9>/run/awg-maintenance.lock
flock -x -w 15 9 || die MAINTENANCE_BUSY
mutated=1
for name in $names;do
  tmp="$root/.$name.stage.$$"
  install -o root -g root -m 0755 "$repo/$(source_for "$name")" "$tmp"
  mv -f "$tmp" "$root/$name"
done
flock -u 9
for name in $names;do
  cmp -s "$repo/$(source_for "$name")" "$root/$name" || die INSTALL_VERIFICATION_FAILED
done
[[ "$(/usr/local/sbin/awg-transport get)" == mihomo ]] || die TRANSPORT_CHANGED_AFTER
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die MODE_CHANGED_AFTER
verify_routes || die ROUTE_CHANGED_AFTER
for svc in ssh dnsmasq awg-mihomo awg-quick@awg0 awg-selection-monitor awg-pbr-health;do
  healthy "$svc" || die "SERVICE_FAILED_$svc"
done
! healthy awg-xray-vless || die XRAY_STARTED
[[ "$(/usr/local/sbin/awg-mihomo-node-policy status)" == *"Mihomo node policy: auto"* ]] || die NODE_AUTO_CHANGED
systemctl stop "$timer" >/dev/null || die WATCHDOG_DISARM_FAILED
! healthy "$timer" || die WATCHDOG_STILL_ACTIVE
echo COMMITTED >"$snap/state"
committed=1
echo PASSIVE_INSTALL=PASS
echo "PASSIVE_BACKUP=$snap"
echo XRAY_CANARY=OFF
echo RUNTIME_SERVICES_RESTARTED=NO
echo OPERATING_MODE=SELECTIVE
