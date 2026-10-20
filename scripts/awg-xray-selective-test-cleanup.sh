#!/usr/bin/env bash
# TEST PI ONLY. Cleanup committed test-owned Xray sidecar after AWG latch.
# NEVER alters AWG, Transit, DNS, SSH or MikroTik.
set -Eeuo pipefail
umask 077
TRANSPORT=/usr/local/sbin/awg-transport
MODE=/etc/awg-pbr/mode
CURRENT=/etc/awg-pbr/transports/mihomo/node-name
XRAY_UNIT=awg-xray-vless.service
RUNTIME=/run/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf
PERSISTENT=/etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf
SELECTED=/var/lib/awg-pbr/xray-vless/selected.json
[[ $# -eq 1 && "$1" == /dev/shm/awg-xray-auto-test.* ]] || { echo 'XRAY_TEST_CLEANUP_ABORT=BAD_TEST_DIR' >&2;exit 2; }
OLD_NODE="$1/old-node"
BACKUP="/var/backups/awg-gateway/xray-selective-test-cleanup-$(date -u +%Y%m%dT%H%M%S)-$$"
die(){ echo "XRAY_TEST_CLEANUP_ABORT=$1" >&2;exit 1; }
up(){ systemctl is-active --quiet "$1"; }
[[ "$EUID" == 0 && "$(hostname)" == awg-upgrade ]] || die TESTPI_ROOT_REQUIRED
[[ "$(cat "$MODE")" == selective ]] || die NOT_SELECTIVE
[[ "$("$TRANSPORT" get)" == awg && "$("$TRANSPORT" check awg)" == healthy ]] || die AWG_NOT_HEALTHY_SELECTED
for svc in awg-quick@awg0 awg-selection-monitor awg-pbr-health ssh dnsmasq;do
  up "$svc" || die "SERVICE_DOWN_$svc"
done
! up awg-mihomo || die ACTIVE_MIHOMO_UNEXPECTED
for tab in 100 101;do
  ip -4 route show table "$tab" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "AWG_ROUTE_$tab"
done
[[ ! -e /run/systemd/system/awg-selection-monitor.service.d/95-xray-selective-canary.conf ]] || die TEST_CANARY_STILL_ACTIVE
if systemctl list-timers --all --no-pager --no-legend | grep -Eq 'awg-xray-(auto-test-recover|failover-[0-9]+)\.timer';then
  die EXPERIMENT_WATCHDOG_STILL_ACTIVE
fi
[[ -s "$CURRENT" && -f "$CURRENT" && ! -L "$CURRENT" ]] || die CURRENT_NODE_FILE_INVALID
[[ -s "$OLD_NODE" && -f "$OLD_NODE" && ! -L "$OLD_NODE" ]] || die ORIGINAL_NODE_PROOF_MISSING
[[ "$(stat -c '%u' "$OLD_NODE")" == 0 ]] || die ORIGINAL_NODE_NOT_ROOT_OWNED
for overlay in "$PERSISTENT" "$RUNTIME";do
  if [[ -e "$overlay" || -L "$overlay" ]];then
    [[ -f "$overlay" && ! -L "$overlay" ]] || die FOREIGN_BRIDGE_FILE
    grep -Fq 'MIHOMO_XRAY_VLESS_BRIDGE=1' "$overlay" || die FOREIGN_BRIDGE_CONTENT
  fi
done
if [[ -e "$SELECTED" || -L "$SELECTED" ]];then
  [[ -f "$SELECTED" && ! -L "$SELECTED" ]] || die FOREIGN_SELECTED_FILE
fi
exec 9>/run/awg-maintenance.lock
flock -x -w 20 9 || die LOCK_BUSY
[[ "$("$TRANSPORT" get)" == awg && "$("$TRANSPORT" check awg)" == healthy ]] || die AWG_CHANGED_UNDER_LOCK
for tab in 100 101;do
  ip -4 route show table "$tab" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "AWG_CHANGED_ROUTE_$tab"
done
install -d -m 0700 -o root -g root "$BACKUP"
cp -a -- "$CURRENT" "$BACKUP/node-name.before"
cp -a -- "$OLD_NODE" "$BACKUP/node-name.saved-before-test"
for entry in "$PERSISTENT" "$RUNTIME" "$SELECTED";do
  if [[ -f "$entry" ]];then
    cp -a -- "$entry" "$BACKUP/$(basename "$entry")"
  fi
done
echo XRAY_CLEANUP_BACKUP=VERIFIED
systemctl stop "$XRAY_UNIT" || die XRAY_STOP_FAILED
systemctl disable "$XRAY_UNIT" >/dev/null || die XRAY_DISABLE_FAILED
rm -f -- "$PERSISTENT" "$RUNTIME" "$SELECTED"
systemctl daemon-reload
# Restore only saved CONFIGURATION, not a live or certified node.
install -o root -g root -m 0600 "$OLD_NODE" "$CURRENT.test-restore.$$"
mv -f -- "$CURRENT.test-restore.$$" "$CURRENT"
flock -u 9
! up "$XRAY_UNIT" || die XRAY_STILL_ACTIVE
[[ "$(systemctl is-enabled "$XRAY_UNIT" 2>/dev/null || true)" == disabled ]] || die XRAY_STILL_ENABLED
for entry in "$PERSISTENT" "$RUNTIME" "$SELECTED";do
  [[ ! -e "$entry" && ! -L "$entry" ]] || die XRAY_ARTIFACT_REMAINS
done
[[ "$("$TRANSPORT" get)" == awg && "$("$TRANSPORT" check awg)" == healthy ]] || die AWG_UNHEALTHY_AFTER
for tab in 100 101;do
  ip -4 route show table "$tab" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "AWG_ROUTE_AFTER_$tab"
done
for svc in awg-quick@awg0 awg-selection-monitor awg-pbr-health ssh dnsmasq;do
  up "$svc" || die "SERVICE_DOWN_AFTER_$svc"
done
[[ "$(sha256sum "$CURRENT" | cut -d' ' -f1)" == "$(sha256sum "$OLD_NODE" | cut -d' ' -f1)" ]] || die NODE_SELECTION_NOT_RESTORED
echo XRAY_TEST_CLEANUP=PASS
echo XRAY_SERVICE=DISABLED_INACTIVE
echo NATIVE_NODE_SELECTION=RESTORED_NOT_LIVE_TESTED
echo ACTIVE_TRANSPORT=AWG_UNCHANGED
echo "XRAY_CLEANUP_BACKUP_DIR=$BACKUP"
