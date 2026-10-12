#!/usr/bin/env bash
# Stage 19: one isolated <=12MiB/60s decode on approved SS candidate.
# Does NOT read/cache provider in the media worker, switch production,
# edit routing/MikroTik/sudoers, or install a permanent service.
set -Eeuo pipefail
umask 077
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
[[ "$(id -u)" == 0 ]] || { echo LOCAL_SUDO_REQUIRED; exit 21; }

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
RAM=/dev/shm/awg-stage15
TARGET=/usr/local/lib/awg-stage16
MEDIATARGET=/usr/local/lib/awg-pbr-stage15
NODEUNIT=/etc/systemd/system/awg-stage16-node@.service
MEDIAUNIT=/etc/systemd/system/awg-stage19-media@.service
CREDS=/run/awg-pbr/stage16-media
PORTS=(17891)
NAMES=(shadowsocks-27307)
NODE_SHA=fd959ead1bf6d636f3c441b0943c4c0929db48cbf7608aa3516e66d12a727ec5
YTDLP_SHA=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6

[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" == feature/service-aware-smart-gate ]] || { echo BRANCH_MISMATCH; exit 22; }
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || { echo STAGING_SOURCE_MODIFIED; exit 23; }
for p in "$NODEUNIT" "$MEDIAUNIT" "$TARGET" "$MEDIATARGET" "$CREDS"; do
    [[ ! -e "$p" && ! -L "$p" ]] || { echo STAGE16_EXISTING_INSTALL; exit 24; }
done
[[ -d "$RAM/bin" && ! -L "$RAM" && ! -L "$RAM/bin" ]] || { echo RAM_RUNTIME_MISSING; exit 25; }
for f in node yt-dlp; do
    [[ -f "$RAM/bin/$f" && ! -L "$RAM/bin/$f" ]] || { echo RAM_RUNTIME_INVALID; exit 26; }
done
[[ "$("$RAM/bin/node" --version)" == v22.16.0 ]] || { echo NODE_VERSION_INVALID; exit 27; }
[[ "$(sha256sum "$RAM/bin/node" | cut -d' ' -f1)" == "$NODE_SHA" ]] || { echo NODE_HASH_INVALID; exit 27; }
[[ "$(sha256sum "$RAM/bin/yt-dlp" | cut -d' ' -f1)" == "$YTDLP_SHA" ]] || { echo YTDLP_HASH_INVALID; exit 27; }
[[ -x /usr/local/bin/mihomo ]] || { echo MIHOMO_BINARY_MISSING; exit 28; }

FILES=(awg-stage16-prepare.py awg-mihomo-pool.py awg-mihomo-service-trial.py awg-mihomo-smart
       awg-mihomo-limits.py awg-mihomo-service-check.py awg-endpoint-provenance.py
       awg-mihomo-standby.py awg-node-qualification.py)
for file in "${FILES[@]}"; do
  [[ -f "$ROOT/src/$file" && ! -L "$ROOT/src/$file" ]] || { echo STAGING_DEPENDENCY_MISSING; exit 29; }
done
for file in awg-youtube-frame-check.py awg-media-sidecar.py awg-video-sustained-check.py; do
  [[ -f "$ROOT/src/$file" && ! -L "$ROOT/src/$file" ]] || { echo MEDIA_SOURCE_MISSING; exit 30; }
done
for f in "$ROOT/units/awg-stage16-node@.service" "$ROOT/units/awg-stage19-media@.service"; do
  [[ -f "$f" && ! -L "$f" ]] || { echo UNIT_SOURCE_MISSING; exit 31; }
  ! grep -Eq '^\[Install\]' "$f" || { echo PERSISTENT_UNIT_NOT_ALLOWED; exit 31; }
  systemd-analyze verify "$f" >/dev/null || { echo UNIT_INVALID; exit 31; }
done
grep -Fxq 'DynamicUser=yes' "$ROOT/units/awg-stage16-node@.service" || exit 32
grep -Fxq 'LoadCredential=proxy:/run/awg-pbr/stage16-media/proxy-%i.yaml' "$ROOT/units/awg-stage16-node@.service" || exit 32
grep -Fxq 'IPAddressDeny=any' "$ROOT/units/awg-stage19-media@.service" || exit 32
grep -Fxq 'IPAddressAllow=localhost' "$ROOT/units/awg-stage19-media@.service" || exit 32
! grep -Eq '^LoadCredential=.' "$ROOT/units/awg-stage19-media@.service" || exit 32

before="$(ip -4 route show table 100)"
trap_cleanup() {
  for port in "${PORTS[@]}"; do
    systemctl stop "awg-stage19-media@${port}.service" >/dev/null 2>&1 || true
    systemctl stop "awg-stage16-node@${port}.service" >/dev/null 2>&1 || true
  done
  rm -f -- "$NODEUNIT" "$MEDIAUNIT"
  rm -rf -- "$TARGET" "$MEDIATARGET" "$CREDS" "$RAM"
  systemctl daemon-reload >/dev/null 2>&1 || true
}
trap trap_cleanup EXIT
echo STAGE19_RANGE_SHADOW_ONLY=STARTED
install -d -m 0755 "$TARGET" "$MEDIATARGET"
for f in "${FILES[@]}"; do install -m 0644 "$ROOT/src/$f" "$TARGET/$f"; done
for f in awg-youtube-frame-check.py awg-media-sidecar.py awg-video-sustained-check.py; do
    install -m 0644 "$ROOT/src/$f" "$MEDIATARGET/$f"
done
/usr/bin/python3 "$TARGET/awg-stage16-prepare.py" --target shadowsocks-27307
for port in "${PORTS[@]}"; do
  [[ -f "$CREDS/proxy-$port.yaml" ]] || { echo STAGE16_CREDENTIAL_NOT_READY; exit 33; }
  [[ "$(stat -c %a "$CREDS/proxy-$port.yaml")" == 600 ]] || { echo INSECURE_CREDENTIAL_PERMISSIONS; exit 33; }
done
install -m 0644 "$ROOT/units/awg-stage16-node@.service" "$NODEUNIT"
install -m 0644 "$ROOT/units/awg-stage19-media@.service" "$MEDIAUNIT"
systemctl daemon-reload
for round in 1; do
echo "STAGE19_INDEPENDENT_ROUND=$round"
for index in 0; do
  port="${PORTS[$index]}"
  name="${NAMES[$index]}"
  hash="$(printf '%s' "$name" | sha256sum | cut -c1-12)"
  echo "STAGE19_CANDIDATE=$hash PORT=$port"
  rc=0
  systemctl start "awg-stage16-node@$port.service" || rc=$?
  if [[ "$rc" -ne 0 ]] || ! systemctl is-active --quiet "awg-stage16-node@$port.service"; then
    echo "STAGE19_NODE_START=UNKNOWN"
    systemctl stop "awg-stage16-node@$port.service" >/dev/null 2>&1 || true
    continue
  fi
  # A reachability check on public non-sensitive Google URL through THIS
  # private side-proxy, not through the selected production Mihomo.
  ready=false
  for attempt in 1 2 3; do
    google="$(curl -q -4 -sS -o /dev/null -w '%{http_code}' \
       -x "http://127.0.0.1:$port" --connect-timeout 3 --max-time 6 \
       https://www.google.com/generate_204 2>/dev/null || :)"
    if [[ "$google" == 204 ]]; then ready=true; break; fi
    sleep 1
  done
  if [[ "$ready" != true ]]; then
    echo "STAGE19_PROXY_REACHABILITY=UNKNOWN"
    systemctl stop "awg-stage16-node@$port.service" >/dev/null 2>&1 || true
    continue
  fi
  echo "STAGE19_PROXY_REACHABILITY=PASS"
  rc=0
  systemctl start "awg-stage19-media@$port.service" || rc=$?
  echo "STAGE19_MEDIA_EXIT_RC=$rc"
  systemctl show "awg-stage19-media@$port.service" -p ExecMainStatus -p Result --no-pager
  # Sidecar output is allowlisted/sanitized. NEVER report proxy raw logs or secrets.
  echo "STAGE19_60S_RESULT:"
  journalctl -u "awg-stage19-media@$port.service" --no-pager -n 12 -o cat 2>/dev/null |
    grep -E '^\{"credentials_loaded":false.*"shadow_only":true.*\}$' | tail -1 ||
    echo "STAGE19_FRAME_SAMPLE_UNAVAILABLE"
  systemctl stop "awg-stage16-node@$port.service" >/dev/null 2>&1 || true
  systemctl reset-failed "awg-stage19-media@$port.service" >/dev/null 2>&1 || true
done

done
after="$(ip -4 route show table 100)"
[[ "$before" == "$after" ]] || { echo "WARNING_TABLE100_CHANGED_DURING_TRIAL"; exit 34; }
echo "TABLE100_UNCHANGED"
echo "SERVICE_READY=false ROUTE_VERIFIED=false"
echo "TEMPORARY_UNITS_AND_CREDENTIALS_CLEANED_ON_EXIT"
