#!/usr/bin/env bash
# Operator-reviewed, one-shot, NO-SECRETS media probe through ACTIVE loopback.
# Does not manipulate subscriptions, routes, transport selections or sudoers.
set -Eeuo pipefail
umask 077
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
[[ "$(id -u)" -eq 0 ]] || { echo "LOCAL_SUDO_REQUIRED"; exit 21; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TARGET=/usr/local/lib/awg-pbr-stage15
UNIT=/etc/systemd/system/awg-media-sidecar@.service
SERVICE=awg-media-sidecar@7890.service
RAM=/dev/shm/awg-stage15
[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" == feature/service-aware-smart-gate ]] || exit 22
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || exit 23
[[ ! -e "$UNIT" && ! -e "$TARGET" ]] || exit 24
[[ -f "$ROOT/units/awg-media-sidecar@.service" ]] || exit 25
for path in "$ROOT/src/awg-media-sidecar.py" "$ROOT/src/awg-youtube-frame-check.py"; do
  [[ -f "$path" && ! -L "$path" ]] || exit 26
done
[[ -x "$RAM/bin/node" && -f "$RAM/bin/yt-dlp" ]] || {
  echo "RAM_RUNTIME_MISSING"; exit 27;
}
[[ "$("$RAM/bin/node" --version)" == v22.16.0 ]] || exit 28
[[ ! -L "$RAM" && ! -L "$RAM/bin" && ! -L "$RAM/bin/node" && ! -L "$RAM/bin/yt-dlp" ]] || exit 28
# Pin the exact *extracted* artifacts verified against official manifests.
# Do not trust version text alone or files that can change after download.
NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
YTDLP_SHA=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6
[[ "$(sha256sum "$RAM/bin/node" | cut -d' ' -f1)" == "$NODE_SHA" ]] || exit 28
[[ "$(sha256sum "$RAM/bin/yt-dlp" | cut -d' ' -f1)" == "$YTDLP_SHA" ]] || exit 28
systemd-analyze verify "$ROOT/units/awg-media-sidecar@.service" >/dev/null
# Require the audited, loopback-only unit with its own nonroot UID.
grep -Fxq 'DynamicUser=yes' "$ROOT/units/awg-media-sidecar@.service" || exit 29
grep -Fxq 'IPAddressDeny=any' "$ROOT/units/awg-media-sidecar@.service" || exit 29
grep -Fxq 'IPAddressAllow=localhost' "$ROOT/units/awg-media-sidecar@.service" || exit 29
! grep -q '^LoadCredential=.' "$ROOT/units/awg-media-sidecar@.service" || exit 29
! grep -q '^\[Install\]' "$ROOT/units/awg-media-sidecar@.service" || exit 29
before="$(ip -4 route show table 100)"
cleanup() {
  systemctl stop "$SERVICE" >/dev/null 2>&1 || true
  rm -f -- "$UNIT"
  rm -rf -- "$TARGET" "$RAM"
  systemctl daemon-reload >/dev/null 2>&1 || true
}
trap cleanup EXIT
install -d -m 0755 "$TARGET"
install -m 0644 "$ROOT/src/awg-media-sidecar.py" "$TARGET/awg-media-sidecar.py"
install -m 0644 "$ROOT/src/awg-youtube-frame-check.py" "$TARGET/awg-youtube-frame-check.py"
install -m 0644 "$ROOT/units/awg-media-sidecar@.service" "$UNIT"
systemctl daemon-reload
echo "STAGE15_SIDE_CAR=STARTED"
echo "CREDENTIALS_EXPOSED=false"
echo "PROXY_ENDPOINT=127.0.0.1:7890"
rc=0
systemctl start "$SERVICE" || rc=$?
echo "STAGE15_SYSTEMD_RESULT:"
systemctl show "$SERVICE" -p Result -p ExecMainStatus -p ConditionResult --no-pager
echo "SANITIZED_FRAME_RESULT:"
journalctl -u "$SERVICE" -o cat -n 12 --no-pager 2>/dev/null |
  grep -E '^\{"credentials_loaded":false.*"shadow_only":true.*\}$' | tail -1 ||
  echo "NO_SANITIZED_SAMPLE"
after="$(ip -4 route show table 100)"
[[ "$before" == "$after" ]] || { echo "WARNING_ROUTE_CHANGED"; exit 30; }
echo "ROUTING_TABLE100_UNCHANGED"
echo "EPHEMERAL_RUNTIME_AND_UNIT_REMOVED_ON_EXIT"
[[ "$rc" -eq 0 ]] || exit 31
echo "STAGE15_SIDE_CAR=COMPLETE"
