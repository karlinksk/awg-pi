#!/usr/bin/env bash
# Root owner-run TEST-PI ONLY; one command. AWG first, independent failback.
set -Eeuo pipefail
umask 077
die(){ echo "TRANSIT_GATE_ABORT=$1" >&2; exit 1; }
[[ "$EUID" == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_TESTPI_ROOT
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die ORIGIN_NOT_SELECTIVE
[[ "$(/usr/local/sbin/awg-transport get)" == awg ]] || die ORIGIN_NOT_AWG
[[ "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_NOT_HEALTHY
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == auto ]] || die NODE_POLICY_NOT_AUTO
[[ "$(cat /etc/awg-pbr/transports/mihomo/ready-auto.mode)" == 0 ]] || die READY_ENABLED
for u in ssh dnsmasq awg-selection-monitor awg-pbr-health awg-quick@awg0;do
  systemctl is-active --quiet "$u" || die "SERVICE_$u"
done
root="$(cd "$(dirname "$0")/.." && pwd -P)"
test -f "$root/scripts/awg-xray-transit-one-shot-failover.sh" || die MISSING_TEST
# The outer timer is distinct from the inner scenario timer.
dir="$(mktemp -d /dev/shm/awg-transit-outer.XXXXXXXX)"
cat > "$dir/recover" <<'RECOVER'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(hostname)" == awg-upgrade ]] || exit 1
# Remove only the mode hazard before restoring AWG.
if [[ "$(cat /etc/awg-pbr/mode)" == transit ]];then
  /usr/local/sbin/awg-route mode selective
fi
if [[ "$(/usr/local/sbin/awg-transport check awg 2>/dev/null || true)" == healthy ]];then
  /usr/local/sbin/awg-transport select awg
fi
RECOVER
chmod 700 "$dir/recover"
systemd-run --quiet --collect --unit=awg-xray-transit-outer-recover --on-active=600s /bin/bash "$dir/recover" || die NO_INDEPENDENT_WATCHDOG
systemctl is-active --quiet awg-xray-transit-outer-recover.timer || die WATCHDOG_NOT_ARMED
echo OUTER_WATCHDOG=ARMED_600S
cleanup(){
  rc=$?
  trap - EXIT
  if bash "$dir/recover";then
    systemctl stop awg-xray-transit-outer-recover.timer >/dev/null 2>&1 || true
    echo OUTER_RECOVERY=PASS
  else
    echo OUTER_RECOVERY=FAILED_WATCHDOG_REMAINS
    rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
/usr/local/sbin/awg-transport select mihomo || die MIHOMO_SELECT_FAILED
[[ "$(/usr/local/sbin/awg-transport get)" == mihomo ]] || die MIHOMO_NOT_SELECTED
echo MIHOMO_PREPARED=PASS
bash "$root/scripts/awg-xray-transit-one-shot-failover.sh"
