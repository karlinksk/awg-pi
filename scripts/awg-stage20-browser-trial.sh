#!/usr/bin/env bash
# Stage20 opt-in manual browser session through ONE credential-isolated
# Shadowsocks proxy. Never changes the production selected transport.
set -Eeuo pipefail
umask 077
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
[[ "$(id -u)" == 0 ]] || { echo LOCAL_SUDO_REQUIRED; exit 21; }
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
TARGET=/usr/local/lib/awg-stage20
CREDS=/run/awg-pbr/stage16-media
UNIT=/etc/systemd/system/awg-stage20-browser@.service
PORT=17891
[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" == feature/service-aware-smart-gate ]] || exit 22
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || exit 23
for p in "$TARGET" "$CREDS" "$UNIT"; do
  [[ ! -e "$p" && ! -L "$p" ]] || { echo EXISTING_TEMP_INSTALL; exit 24; }
done
for item in awg-stage16-prepare.py awg-mihomo-pool.py awg-mihomo-service-trial.py awg-mihomo-smart awg-mihomo-limits.py awg-mihomo-service-check.py awg-endpoint-provenance.py awg-mihomo-standby.py awg-node-qualification.py; do
  [[ -f "$ROOT/src/$item" && ! -L "$ROOT/src/$item" ]] || exit 25
done
[[ -f "$ROOT/units/awg-stage20-browser@.service" && ! -L "$ROOT/units/awg-stage20-browser@.service" ]] || exit 26
! grep -Eq '^\[Install\]' "$ROOT/units/awg-stage20-browser@.service" || exit 27
grep -Fxq 'DynamicUser=yes' "$ROOT/units/awg-stage20-browser@.service" || exit 27
grep -Fxq 'LoadCredential=proxy:/run/awg-pbr/stage16-media/proxy-%i.yaml' "$ROOT/units/awg-stage20-browser@.service" || exit 27
systemd-analyze verify "$ROOT/units/awg-stage20-browser@.service" >/dev/null || exit 27
before="$(ip -4 route show table 100)"
cleanup() {
  systemctl stop "awg-stage20-browser@$PORT.service" >/dev/null 2>&1 || true
  rm -f -- "$UNIT"
  rm -rf -- "$CREDS" "$TARGET"
  systemctl daemon-reload >/dev/null 2>&1 || true
  [[ "$before" == "$(ip -4 route show table 100)" ]] && echo TABLE100_UNCHANGED || echo ROUTE_CHANGED_EXTERNALLY
  echo STAGE20_CREDENTIALS_AND_SERVICE_REMOVED
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
install -d -m 0755 "$TARGET"
for item in awg-stage16-prepare.py awg-mihomo-pool.py awg-mihomo-service-trial.py awg-mihomo-smart awg-mihomo-limits.py awg-mihomo-service-check.py awg-endpoint-provenance.py awg-mihomo-standby.py awg-node-qualification.py; do
  install -m 0644 "$ROOT/src/$item" "$TARGET/$item"
done
/usr/bin/python3 "$TARGET/awg-stage16-prepare.py" --target shadowsocks-27307
[[ -f "$CREDS/proxy-$PORT.yaml" && "$(stat -c %a "$CREDS/proxy-$PORT.yaml")" == 600 ]] || exit 28
python3 - "$CREDS/proxy-$PORT.yaml" <<'PY'
import sys, yaml
from pathlib import Path
cfg=yaml.safe_load(Path(sys.argv[1]).read_text())
p=cfg.get("proxies",[])
if (len(p)!=1 or p[0].get("server")!="169.150.210.233"
    or p[0].get("port")!=8080 or p[0].get("type")!="ss"
    or cfg.get("mixed-port")!=17891
    or cfg.get("bind-address")!="127.0.0.1"
    or cfg.get("allow-lan") is not False):
    raise SystemExit("ENDPOINT_CHANGED_REVIEW_REQUIRED")
print("EXACT_SPARE_ENDPOINT_VERIFIED")
PY
install -m 0644 "$ROOT/units/awg-stage20-browser@.service" "$UNIT"
systemctl daemon-reload
systemctl start "awg-stage20-browser@$PORT.service"
systemctl is-active --quiet "awg-stage20-browser@$PORT.service" || exit 29
ok=false
for attempt in 1 2 3; do
  rc="$(curl -q -4 -sS -o /dev/null -w '%{http_code}' -x "http://127.0.0.1:$PORT" --connect-timeout 3 --max-time 6 https://www.google.com/generate_204 2>/dev/null || :)"
  if [[ "$rc" == 204 ]]; then ok=true; break; fi
  sleep 1
done
[[ "$ok" == true ]] || { echo SPARE_CONNECTIVITY_UNKNOWN; exit 30; }
echo "BROWSER_PROXY_READY=127.0.0.1:$PORT"
echo "TEST_ONLY_SHADOW_NO_ROUTING_CHANGES"
echo "AUTO_STOP_AFTER_720_SECONDS"
end=$((SECONDS+720))
while ((SECONDS<end)); do
  systemctl is-active --quiet "awg-stage20-browser@$PORT.service" || exit 31
  sleep 5
done
echo BROWSER_TEST_WINDOW_EXPIRED
