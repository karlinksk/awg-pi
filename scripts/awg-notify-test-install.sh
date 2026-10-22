#!/usr/bin/env bash
# Passive, minimal test-Pi deployment. DOES NOT run full installer.
# Does not touch transports, selection monitors, routes, DNS, SSH or MikroTik.
set -Eeuo pipefail
umask 077

[[ ${EUID:-$(id -u)} -eq 0 ]] || {
  echo 'ERROR: run with sudo on the TEST Pi only.' >&2
  exit 2
}
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
files=(
  src/awg-notify.py
  units/awg-notify-flush.service
  units/awg-notify-flush.timer
  units/awg-notify-daily.service
  units/awg-notify-daily.timer
)
for file in "${files[@]}"; do
  [[ -f "$root/$file" && ! -L "$root/$file" ]] || {
    echo "Missing or symbolic-link input: $file" >&2
    exit 3
  }
done

# Never overwrite live notification state/units during this first isolated test.
targets=(
  /usr/local/sbin/awg-notify
  /etc/systemd/system/awg-notify-flush.service
  /etc/systemd/system/awg-notify-flush.timer
  /etc/systemd/system/awg-notify-daily.service
  /etc/systemd/system/awg-notify-daily.timer
)
for target in "${targets[@]}"; do
  [[ ! -e "$target" && ! -L "$target" ]] || {
    echo "REFUSE: $target already exists; do not overwrite." >&2
    exit 4
  }
done

# Do not bring up any unit; preflight only.
bash -n "$root/install.sh" "$root/src/awg-transport" \
  "$root/src/awg-selection-monitor" "$root/src/awg-menu"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "$root/tests" -p 'test_notify*.py' -q
# Existing units should remain unaffected.
echo 'PRECHECK=PASS'

installed=()
cleanup_on_error(){
  local rc=$?
  trap - ERR
  for target in "${installed[@]}"; do rm -f -- "$target"; done
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "NOTIFY_PASSIVE_INSTALL=ROLLED_BACK rc=$rc" >&2
  exit "$rc"
}
trap cleanup_on_error ERR

install -d -o root -g root -m 0700 \
  /etc/awg-pbr/notify /var/lib/awg-pbr/notify
install -o root -g root -m 0755 "$root/src/awg-notify.py" "${targets[0]}"
installed+=("${targets[0]}")
for i in 1 2 3 4; do
  install -o root -g root -m 0644 "$root/${files[i]}" "${targets[i]}"
  installed+=("${targets[i]}")
done

systemctl daemon-reload
systemd-analyze verify "${targets[1]}" "${targets[2]}" "${targets[3]}" "${targets[4]}"
for timer in awg-notify-flush.timer awg-notify-daily.timer; do
  if systemctl is-enabled --quiet "$timer" ||
     systemctl is-active --quiet "$timer"; then
    echo "ERROR: timer unexpectedly active/enabled: $timer" >&2
    false
  fi
done
/usr/local/sbin/awg-notify status
trap - ERR
echo 'NOTIFY_PASSIVE_INSTALL=PASS'
echo 'NOTIFY_TIMERS=DISABLED'
echo 'GATEWAY_SERVICE_CHANGES=NONE'
