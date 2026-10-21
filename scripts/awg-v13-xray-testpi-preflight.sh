#!/usr/bin/env bash
# Test Pi installation gate. --check is read-only; --snapshot ONLY creates a backup.
# No VPN/Xray service starts, no route changes and no MikroTik changes.
set -Eeuo pipefail
umask 077
usage(){ echo "Usage: $0 --check|--snapshot EXPECTED_COMMIT_SHA" >&2; exit 2; }
[[ $# -eq 2 ]] || usage
action="$1"; expected="$2"
[[ "$action" == --check || "$action" == --snapshot ]] || usage
[[ "$expected" =~ ^[a-f0-9]{40}$ ]] || usage
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(hostname -s)" == awg-upgrade ]] || { echo PREPARE_ERROR=NOT_TEST_PI >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == arm64 ]] || { echo PREPARE_ERROR=NOT_ARM64 >&2; exit 1; }
grep -Eq '^VERSION_ID="?13"?' /etc/os-release || { echo PREPARE_ERROR=NOT_DEBIAN_13 >&2; exit 1; }
current="$(git -C "$root" rev-parse HEAD)"
[[ "$current" == "$expected" ]] || { echo PREPARE_ERROR=COMMIT_MISMATCH >&2; exit 1; }
git -C "$root" diff --quiet && git -C "$root" diff --cached --quiet ||
  { echo PREPARE_ERROR=DIRTY_REPOSITORY >&2; exit 1; }
for file in install.sh src/awg-mihomo-config src/awg-menu src/awg-update src/awg-gpt;do
  bash -n "$root/$file" || { echo PREPARE_ERROR=SHELL_SYNTAX >&2; exit 1; }
done
for file in src/awg-xray-manual-switch.py src/awg-mihomo-node-picker.py src/awg-mihomo-unified-nodes.py;do
  python3 -B - "$root/$file" <<'PY' || { echo PREPARE_ERROR=PYTHON_SYNTAX >&2; exit 1; }
import ast,sys
ast.parse(open(sys.argv[1],encoding="utf-8").read())
PY
done
for component in ssh.service dnsmasq.service awg-pbr-health.service awg-mihomo.service; do
  systemctl is-active --quiet "$component" ||
    { echo PREPARE_ERROR=CRITICAL_SERVICE_UNHEALTHY >&2; exit 1; }
done
[[ "$(cat /usr/share/awg-pbr/version 2>/dev/null)" == "1.3.0" ]] ||
  { echo PREPARE_ERROR=WRONG_INSTALLED_VERSION >&2; exit 1; }
[[ -x /usr/local/sbin/awg-update && -x /usr/local/sbin/awg-transport ]] ||
  { echo PREPARE_ERROR=UPDATER_OR_TRANSPORT_ABSENT >&2; exit 1; }
for unit in units/awg-xray-subscription-scan.service \
            units/awg-xray-subscription-scan.path \
            units/awg-xray-subscription-scan.timer;do
  [[ -s "$root/$unit" ]] || { echo PREPARE_ERROR=SCANNER_UNIT_MISSING >&2; exit 1; }
done
[[ -x /usr/local/bin/mihomo && -x /usr/local/bin/awg-xray-vless-core ]] ||
  { echo PREPARE_ERROR=ENGINE_MISSING >&2; exit 1; }
[[ -x /usr/bin/ffmpeg && -x /usr/bin/ffprobe ]] ||
  { echo PREPARE_ERROR=MEDIA_RUNTIME_MISSING >&2; exit 1; }
echo "TEST_PI=VERIFIED"
echo "SOURCE_COMMIT=$current"
echo "SOURCE_SYNTAX=PASS"
echo "MANAGEMENT_SERVICES=ACTIVE"
echo "BACKUP=NOT_PERFORMED"
echo "UPGRADE=NOT_STARTED"
[[ "$action" == --check ]] && exit 0

[[ "$EUID" -eq 0 ]] || { echo PREPARE_ERROR=ROOT_REQUIRED >&2; exit 1; }
install -d -o root -g root -m 0700 /var/backups/awg-gateway
# Snapshot before upgrading. Automatic restoration of transports is NOT claimed
# because restore_gateway does restart services and requires its own live gate.
capture="$(/usr/local/sbin/awg-update backup)"
grep -Fqx 'GATEWAY_BACKUP=VERIFIED' <<<"$capture" ||
  { echo PREPARE_ERROR=BACKUP_NOT_VERIFIED >&2; exit 1; }
archive="$(sed -n 's/^GATEWAY_BACKUP_ARCHIVE=//p' <<<"$capture" | head -n1)"
[[ "$archive" == /var/backups/awg-gateway/gateway-manual-*/gateway-state.tgz ]] ||
  { echo PREPARE_ERROR=BACKUP_PATH_INVALID >&2; exit 1; }
[[ -f "$archive" && ! -L "$archive" ]] ||
  { echo PREPARE_ERROR=BACKUP_ARCHIVE_UNSAFE >&2; exit 1; }
tar -tzf "$archive" >/dev/null ||
  { echo PREPARE_ERROR=BACKUP_INTEGRITY >&2; exit 1; }
for required in etc/awg-pbr/ usr/local/sbin/awg-menu \
                usr/local/sbin/awg-update \
                etc/systemd/system/awg-mihomo.service;do
  tar -tzf "$archive" "$required" >/dev/null 2>&1 ||
    { echo PREPARE_ERROR=BACKUP_REQUIRED_MEMBER_MISSING >&2; exit 1; }
done
[[ "$(stat -c %a "$archive")" == "600" ]] ||
  { echo PREPARE_ERROR=BACKUP_PERMISSIONS >&2; exit 1; }
snapshot="$(dirname "$archive")"
{
  echo "SOURCE_COMMIT=$current"
  echo "MODE=$(cat /etc/awg-pbr/mode)"
  echo "TRANSPORT=$(cat /etc/awg-pbr/transport)"
  for unit in ssh.service dnsmasq.service awg-mihomo.service \
              awg-quick@awg0.service awg-xray-vless.service \
              awg-mihomo-hot-pool.timer;do
    echo "UNIT=$unit ACTIVE=$(systemctl is-active "$unit" 2>/dev/null || true) ENABLED=$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  done
} >"$snapshot/preinstall-state.txt"
chmod 600 "$snapshot/preinstall-state.txt"
echo "BACKUP=VERIFIED"
echo "BACKUP_ARCHIVE=$archive"
echo "BACKUP_BYTES=$(stat -c %s "$archive")"
echo "UPGRADE=NOT_STARTED"
