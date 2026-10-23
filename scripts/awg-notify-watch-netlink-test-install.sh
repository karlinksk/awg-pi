#!/usr/bin/env bash
# Test Pi only. Compare ip link show in old/new systemd sandboxes, install only
# corrected optional notifier watcher unit, but leave its timer DISABLED.
set -Eeuo pipefail
umask 077
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo ROOT_REQUIRED >&2; exit 2; }
name=awg-notify-watch.service
target=/etc/systemd/system/$name
source_unit=/home/karlinks/awg-notify-fixture/units/$name
expected=d40dde31a9d7eb382fd745d0af0451d2e42527cbce52d1221ab2c4fb767431a3
[[ -f "$target" && ! -L "$target" && -f "$source_unit" && ! -L "$source_unit" ]] || { echo REFUSE_MISSING_OR_SYMLINKED_INPUT >&2; exit 3; }
source_sha="$(sha256sum "$source_unit")"
[[ "${source_sha%% *}" == "$expected" ]] || { echo REFUSE_REVIEWED_UNIT_HASH_MISMATCH >&2; exit 4; }
if systemctl is-enabled --quiet awg-notify-watch.timer || systemctl is-active --quiet awg-notify-watch.timer; then
  echo REFUSE_WATCH_TIMER_MUST_BE_DISABLED >&2; exit 5
fi
command -v systemd-run >/dev/null
ip_bin="$(command -v ip)"
case "$ip_bin" in /usr/sbin/ip|/sbin/ip|/usr/bin/ip) ;; *) echo REFUSE_UNEXPECTED_IPROUTE2_PATH >&2; exit 5 ;; esac
# iproute2 requires AF_NETLINK. Run only a READ-ONLY ip link query, never AWG notifier.
sandbox_probe(){
  local flavor="$1" families="$2"
  systemd-run --system --quiet --wait --collect --pipe \
    "--unit=awg-notify-netlink-${flavor}-$$" \
    -p "RestrictAddressFamilies=$families" \
    -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectHome=yes \
    -p ProtectSystem=strict -p ReadWritePaths=/var/lib/awg-pbr/notify \
    "$ip_bin" link show mihomo0 >/dev/null 2>&1
}
if sandbox_probe old 'AF_UNIX AF_INET AF_INET6'; then
  echo UNEXPECTED_OLD_SANDBOX_LINK_PASS >&2; exit 6
fi
echo OLD_SANDBOX_LINK=EXPECTED_FAIL
if ! sandbox_probe new 'AF_UNIX AF_INET AF_INET6 AF_NETLINK'; then
  echo CORRECTED_SANDBOX_LINK=FAIL >&2; exit 7
fi
echo CORRECTED_SANDBOX_LINK=PASS
backup_dir="$(mktemp -d /run/awg-notify-unit-backup.XXXXXXXX)"
install -m 0600 "$target" "$backup_dir/$name"
rollback(){
  local code=$?
  trap - ERR
  install -o root -g root -m 0644 "$backup_dir/$name" "$target"
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "NOTIFY_WATCH_UNIT=ROLLED_BACK code=$code" >&2
  exit "$code"
}
trap rollback ERR
install -o root -g root -m 0644 "$source_unit" "$target"
systemctl daemon-reload
systemd-analyze verify "$target"
systemctl show "$name" -p RestrictAddressFamilies --value | grep -qw AF_NETLINK
if systemctl is-enabled --quiet awg-notify-watch.timer || systemctl is-active --quiet awg-notify-watch.timer; then
  echo WATCH_UNEXPECTEDLY_ENABLED >&2; false
fi
trap - ERR
echo NOTIFY_WATCH_UNIT=PATCHED_TEST_PI_ONLY
echo NOTIFY_WATCH_TIMER=DISABLED
echo NOTIFY_WATCH_OBSERVER_EXECUTION=NOT_YET_VALIDATED
echo "UNIT_ROLLBACK_BACKUP=$backup_dir/$name"
echo GATEWAY_SERVICE_CHANGES=NONE
