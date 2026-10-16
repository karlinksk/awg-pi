#!/usr/bin/env bash
# Offline release regression: ensure READY opt-in helpers survive install,
# upgrade backup and rollback, without automatically enabling the canary.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bash -n install.sh src/awg-update src/awg-mihomo-node-policy src/awg-mihomo-ready-postcheck-tun
python3 -B -c 'import ast; from pathlib import Path; ast.parse(Path("src/awg-mihomo-ready-live-match").read_text())'
python3 -B -c 'import yaml; assert hasattr(yaml, "safe_load")'

must(){
  grep -Fq -- "$2" "$1" || { echo "READY_INSTALL_TEST=MISSING $1: $2" >&2; exit 1; }
}

# Passive installs can never turn the feature on by default.
must install.sh 'install_project_python_helper src/awg-mihomo-ready-live-match "$MIHOMO_READY_GUARD"'
must install.sh 'install_project_helper src/awg-mihomo-ready-postcheck-tun "$MIHOMO_READY_POSTCHECK"'
must install.sh 'python3 -B -c'
must install.sh 'bash -n "$MIHOMO_READY_POSTCHECK"'
must install.sh 'python3-minimal python3-yaml'
must src/awg-mihomo-node-policy 'MIHOMO_READY_AUTO_CANARY="${MIHOMO_READY_AUTO_CANARY:-0}"'
must src/awg-mihomo-node-policy 'MIHOMO_READY_POSTCHECK_BIN="${MIHOMO_READY_POSTCHECK_BIN:-}"'

# Both files are included once in backup and once in removal before restore.
for path in awg-mihomo-ready-live-match awg-mihomo-ready-postcheck-tun; do
  n="$(grep -Fc "usr/local/sbin/$path" src/awg-update)"
  [[ "$n" == 2 ]] || { echo "READY_INSTALL_TEST=BACKUP_ROLLBACK_MISMATCH $path $n" >&2; exit 1; }
done
must src/awg-update '--ignore-failed-read'
must src/awg-update 'tar -C / -xzf "$dir/gateway-state.tgz"'

# No systemd autostart or implicit env activation is allowed.
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?MIHOMO_READY_AUTO_CANARY=1' install.sh src/awg-update; then
  echo "READY_INSTALL_TEST=UNSAFE_AUTO_ENABLE" >&2
  exit 1
fi
if grep -F 'systemctl enable' install.sh | grep -Eq 'ready-(live-match|postcheck)' ; then
  echo "READY_INSTALL_TEST=UNEXPECTED_AUTO_START" >&2
  exit 1
fi
echo READY_INSTALL_INTEGRATION=PASS
