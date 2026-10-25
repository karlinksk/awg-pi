#!/usr/bin/env bash
# TEST-PI ONLY: passive source sync, no service or route changes.
set -Eeuo pipefail
umask 077
die(){ echo "TRANSIT_PATCH_ABORT=$1" >&2;exit 1; }
[[ $EUID == 0 && "$(hostname)" == awg-upgrade ]] || die NOT_ROOT_TEST_PI
[[ "$(cat /etc/awg-pbr/mode)" == selective ]] || die MODE_NOT_SELECTIVE
[[ "$(/usr/local/sbin/awg-transport get)" == awg ]] || die ACTIVE_NOT_AWG
[[ "$(/usr/local/sbin/awg-transport check awg)" == healthy ]] || die AWG_UNHEALTHY
for u in ssh dnsmasq awg-selection-monitor awg-pbr-health awg-quick@awg0;do
  systemctl is-active --quiet "$u" || die "SERVICE_$u"
done
! systemctl is-active --quiet awg-mihomo || die MIHOMO_ACTIVE
! systemctl is-active --quiet awg-xray-vless || die XRAY_ACTIVE
for n in 100 101;do
  ip -4 route show table "$n" | grep -Eq '^default[[:space:]]+dev[[:space:]]+awg0([[:space:]]|$)' || die "ROUTE_$n"
done
src="$(cd "$(dirname "$0")/.." && pwd -P)/src/awg-xray-live-backend.py"
dst=/usr/local/sbin/awg-xray-live-backend
old=61f3d3143ddc5ce2ac00a292014ee752cb17ae90a9a2c9109ed89a271108165c
new=d58d55b5c60514a8ac86a1321c74b411561f08c3ab34d6415dccd52aafd925c6
[[ "$(sha256sum "$src" | cut -d' ' -f1)" == "$new" ]] || die SOURCE_SHA_MISMATCH
[[ "$(sha256sum "$dst" | cut -d' ' -f1)" == "$old" ]] || die INSTALLED_SHA_MISMATCH
python3 -m py_compile "$src" || die PYTHON_SYNTAX
dir="$(mktemp -d /var/backups/awg-gateway/transit-auto-patch-XXXXXXXX)"
cp -a -- "$dst" "$dir/old"
[[ "$(sha256sum "$dir/old" | cut -d' ' -f1)" == "$old" ]] || die BACKUP_MISMATCH
install -o root -g root -m 0755 "$src" "$dst.tmp.$$"
mv -f -- "$dst.tmp.$$" "$dst"
if [[ "$(sha256sum "$dst" | cut -d' ' -f1)" != "$new" ]];then
  install -o root -g root -m 0755 "$dir/old" "$dst"
  die VERIFY_NEW_SHA
fi
echo TRANSIT_PATCH=INSTALLED_VERIFIED
echo TRANSIT_PATCH_BACKUP=VERIFIED
echo TRANSPORT=AWG_UNCHANGED
