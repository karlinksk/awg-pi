#!/usr/bin/env bash
# Install the reviewed cross-core candidate guard; do not change FIXED, TUN, services.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_SHA=3f89f6671c3b8806a995e30ae9ce86ce5e921b9dbc04df94cec27c4e5b291f28
LIVE=/usr/local/sbin/awg-mihomo-node-policy
SOURCE="$ROOT/src/awg-mihomo-node-policy"
RESOLVER=/usr/local/sbin/awg-mihomo-unified-nodes
LOCK=/run/awg-maintenance.lock
ACTION="${1:---check}"
reject(){ echo "XRAY_POLICY_GUARD_ERROR=$1" >&2; exit 1; }
[[ "$ACTION" == --check || "$ACTION" == --stage ]] || reject USAGE
[[ "$(id -u)" == 0 && "$(hostname)" == awg-upgrade ]] || reject ROOT_TEST_PI_REQUIRED
[[ "$(cat /etc/awg-pbr/mode)" == transit ]] || reject TRANSIT_REQUIRED
[[ -f "$LIVE" && ! -L "$LIVE" && -x "$RESOLVER" && -f "$SOURCE" ]] || reject MISSING_GUARD_OR_RESOLVER
[[ "$(git -C "$ROOT" branch --show-current)" == feature/unified-mihomo-xray-nodes-20261019 ]] || reject WRONG_BRANCH
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || reject DIRTY_SOURCE
bash -n "$SOURCE" || reject SOURCE_SYNTAX
grep -Fq 'MIHOMO_NODE_FAILOVER=XRAY_TRANSACTION_NOT_CERTIFIED' "$SOURCE" || reject NO_XRAY_GUARD
grep -Fq 'candidate_visits' "$SOURCE" || reject NO_ATTEMPT_BOUND
[[ ! -e /etc/systemd/system/awg-mihomo.service.d/61-awg-xray-bridge.conf ]] || reject ACTIVE_BRIDGE
systemctl is-active --quiet awg-mihomo.service || reject MIHOMO_INACTIVE
! systemctl is-active --quiet awg-xray-vless.service || reject XRAY_ACTIVE
exec 9>"$LOCK"
flock -x 9
OLD_ACTUAL="$(sha256sum "$LIVE" | cut -d' ' -f1)"
NEW_EXPECTED="$(sha256sum "$SOURCE" | cut -d' ' -f1)"
[[ "$OLD_ACTUAL" == "$OLD_SHA" || "$OLD_ACTUAL" == "$NEW_EXPECTED" ]] || reject UNREVIEWED_LIVE_POLICY
ROUTE100="$(ip -4 route show table 100)"
ROUTE101="$(ip -4 route show table 101)"
[[ "$ROUTE100" == 'default dev mihomo0 scope link ' || "$ROUTE100" == 'default dev mihomo0 scope link' ]] || reject ROUTE100_CHANGED
[[ "$ROUTE101" == 'default dev mihomo0 scope link ' || "$ROUTE101" == 'default dev mihomo0 scope link' ]] || reject ROUTE101_CHANGED
[[ "$(cat /etc/awg-pbr/transports/mihomo/node-policy.mode)" == fixed ]] || reject NOT_FIXED
CURRENT_BEFORE="$(sha256sum /etc/awg-pbr/transports/mihomo/node-name | cut -d' ' -f1)"
ORDER_BEFORE="$(sha256sum /etc/awg-pbr/transports/mihomo/node-policy.nodes | cut -d' ' -f1)"
if [[ "$OLD_ACTUAL" == "$NEW_EXPECTED" ]]; then
  echo XRAY_POLICY_GUARD=ALREADY_INSTALLED
  exit 0
fi
if [[ "$ACTION" == --check ]]; then
  echo XRAY_POLICY_GUARD_STAGE=READY
  echo XRAY_POLICY_GUARD_INSTALLED=NO
  exit 0
fi
SNAP="$(mktemp -d /var/backups/awg-gateway/xray-node-policy-guard-XXXXXXXX)"
chmod 700 "$SNAP"
install -m 0700 "$LIVE" "$SNAP/awg-mihomo-node-policy.old"
TMP="$(mktemp /usr/local/sbin/.awg-mihomo-node-policy.xray-XXXXXXXX)"
recover(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 )); then
    if [[ -f "$SNAP/awg-mihomo-node-policy.old" ]]; then
      install -o root -g root -m 0755 "$SNAP/awg-mihomo-node-policy.old" "$LIVE" || true
    fi
    echo XRAY_POLICY_GUARD_ROLLBACK=ATTEMPTED >&2
  fi
  rm -f -- "$TMP"
  exit "$rc"
}
trap recover EXIT
install -o root -g root -m 0755 "$SOURCE" "$TMP"
mv -f -- "$TMP" "$LIVE"
[[ "$(sha256sum "$LIVE" | cut -d' ' -f1)" == "$NEW_EXPECTED" ]] || reject INSTALL_HASH
[[ "$(sha256sum /etc/awg-pbr/transports/mihomo/node-name | cut -d' ' -f1)" == "$CURRENT_BEFORE" ]] || reject CURRENT_CHANGED
[[ "$(sha256sum /etc/awg-pbr/transports/mihomo/node-policy.nodes | cut -d' ' -f1)" == "$ORDER_BEFORE" ]] || reject ORDER_CHANGED
[[ "$(ip -4 route show table 100)" == "$ROUTE100" ]] || reject ROUTE100_POST
[[ "$(ip -4 route show table 101)" == "$ROUTE101" ]] || reject ROUTE101_POST
systemctl is-active --quiet awg-mihomo.service || reject SERVICE_CHANGED
! systemctl is-active --quiet awg-xray-vless.service || reject XRAY_CHANGED
trap - EXIT
echo XRAY_POLICY_GUARD_INSTALLED=PASSIVE
echo XRAY_POLICY_GUARD_BACKUP=VERIFIED
echo XRAY_POLICY_GUARD_FIXED_UNCHANGED=YES
echo XRAY_POLICY_GUARD_SERVICE_RESTARTED=NO
