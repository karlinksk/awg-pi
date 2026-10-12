#!/usr/bin/env bash
# One authorized sudo invocation. Does not modify active VPN, router or sudoers.
set -Eeuo pipefail
umask 077
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
[[ "$(id -u)" -eq 0 ]] || { echo "LOCAL_SUDO_REQUIRED"; exit 21; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TARGET=/usr/local/lib/awg-pbr-stage13
UNIT=/etc/systemd/system/awg-mihomo-service-trial.service
NAME=awg-mihomo-service-trial.service
CREDS=/run/awg-pbr/stage13-selection/selection.json
[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" == feature/service-aware-smart-gate ]] || exit 22
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || exit 23
[[ ! -e "$UNIT" && ! -e "$TARGET" && ! -e "$CREDS" ]] || exit 24
FILES=(awg-mihomo-trial-prepare.py awg-mihomo-service-trial.py
       awg-mihomo-standby.py awg-mihomo-smart awg-mihomo-pool.py
       awg-mihomo-service-check.py awg-mihomo-limits.py
       awg-endpoint-provenance.py awg-node-qualification.py)
for f in "${FILES[@]}"; do
    [[ -f "$ROOT/src/$f" && ! -L "$ROOT/src/$f" ]] || exit 25
done
[[ -f "$ROOT/units/$NAME" ]] || exit 26
! grep -q '^\[Install\]' "$ROOT/units/$NAME" || exit 27
systemd-analyze verify "$ROOT/units/$NAME" >/dev/null
before="$(ip -4 route show table 100)"
cleanup() {
    systemctl stop "$NAME" >/dev/null 2>&1 || true
    rm -f -- "$UNIT" "$CREDS"
    rm -rf -- "$TARGET"
    rmdir /run/awg-pbr/stage13-selection >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true
}
trap cleanup EXIT
echo "STAGE13_V2=STARTED"
echo "PROTECTED_INPUT_SIZES_ONLY:"
for p in /var/lib/awg-pbr/mihomo/providers/subscription.yaml /run/awg-pbr/mihomo-pool/live.json; do
    if test -f "$p"; then stat -c 'SOURCE_PRESENT_BYTES=%s' "$p"; else echo SOURCE_MISSING; fi
done
install -d -m 0755 "$TARGET"
for f in "${FILES[@]}"; do install -m 0644 "$ROOT/src/$f" "$TARGET/$f"; done
/usr/bin/python3 "$TARGET/awg-mihomo-trial-prepare.py"
[[ -f "$CREDS" && "$(stat -c %s "$CREDS")" -le 480000 ]] || exit 28
install -m 0644 "$ROOT/units/$NAME" "$UNIT"
systemctl daemon-reload
rc=0
systemctl start "$NAME" || rc=$?
echo "TRIAL_SERVICE_STATUS:"
systemctl show "$NAME" -p LoadState -p Result -p ExecMainStatus -p ConditionResult --no-pager
echo "SANITIZED_SAMPLE:"
journalctl -u "$NAME" -o cat -n 20 --no-pager 2>/dev/null |
    grep -E '^\{.*"mode":"SHADOW_ONLY".*\}$' | tail -1 || echo "NO_SANITIZED_SAMPLE"
after="$(ip -4 route show table 100)"
[[ "$before" == "$after" ]] || { echo "WARNING_ROUTE_CHANGED"; exit 30; }
echo "WORKING_ROUTE_UNCHANGED"
echo "TEMPORARY_SERVICE_REMOVED_AT_EXIT"
[[ "$rc" -eq 0 ]] || exit 31
echo "STAGE13_V2=COMPLETE"
