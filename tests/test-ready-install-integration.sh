#!/usr/bin/env bash
# Offline release regression: clean installs explicitly provision Hot Pool
# READY-priority, while existing upgrades preserve their opt-in/out choice.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bash -n install.sh src/awg-update src/awg-mihomo-node-policy src/awg-mihomo-ready-postcheck-tun
# Menu selection uses the versioned installer-installed node-policy helper.
python3 -B tests/test_mihomo_auto_strategy.py
python3 -B tests/test_menu_auto_strategy.py
python3 -B -c 'import ast; from pathlib import Path; ast.parse(Path("src/awg-mihomo-ready-live-match").read_text())'
python3 -B -c 'import yaml; assert hasattr(yaml, "safe_load")'

must(){
  grep -Fq -- "$2" "$1" || { echo "READY_INSTALL_TEST=MISSING $1: $2" >&2; exit 1; }
}

# READY helpers must exist before fresh installation activates priority.
must install.sh 'install_project_python_helper src/awg-mihomo-ready-live-match "$MIHOMO_READY_GUARD"'
must install.sh 'install_project_helper src/awg-mihomo-ready-postcheck-tun "$MIHOMO_READY_POSTCHECK"'
must install.sh 'python3 -B -c'
must install.sh 'bash -n "$MIHOMO_READY_POSTCHECK"'
must install.sh 'python3-minimal python3-yaml'
# The selector must be the last of these three installed files. An existing
# opt-in canary must not run with a newly replaced selector but missing guard.
python3 -B - <<'PY'
from pathlib import Path
text=Path("install.sh").read_text()
guard=text.index('install_project_python_helper src/awg-mihomo-ready-live-match "$MIHOMO_READY_GUARD"')
post=text.index('install_project_helper src/awg-mihomo-ready-postcheck-tun "$MIHOMO_READY_POSTCHECK"')
selector=text.index('install_project_helper src/awg-mihomo-node-policy "$MIHOMO_NODE_POLICY_CLI"')
assert guard < post < selector, "READY installer dependency ordering broken"
PY
must src/awg-mihomo-node-policy 'MIHOMO_READY_AUTO_MODE_FILE="${MIHOMO_READY_AUTO_MODE_FILE:-/etc/awg-pbr/transports/mihomo/ready-auto.mode}"'
must src/awg-mihomo-node-policy 'MIHOMO_READY_AUTO_CANARY="$(cat "$MIHOMO_READY_AUTO_MODE_FILE" 2>/dev/null || echo 0)"'
must src/awg-mihomo-node-policy 'MIHOMO_READY_POSTCHECK_BIN="${MIHOMO_READY_POSTCHECK_BIN:-/usr/local/sbin/awg-mihomo-ready-postcheck-tun}"'
must src/awg-mihomo-node-policy 'ready-auto)'
must install.sh '"$MIHOMO_NODE_POLICY_CLI" ready-auto enable >/dev/null'
must src/awg-menu 'mihomo_auto_strategy_menu(){'
must src/awg-mihomo-node-policy 'select_auto_strategy(){'
must install.sh 'install_project_helper src/awg-menu /usr/local/sbin/awg-menu'

# Both files are included once in backup and once in removal before restore.
for path in awg-mihomo-ready-live-match awg-mihomo-ready-postcheck-tun; do
  n="$(grep -Fc "usr/local/sbin/$path" src/awg-update)"
  [[ "$n" == 2 ]] || { echo "READY_INSTALL_TEST=BACKUP_ROLLBACK_MISMATCH $path $n" >&2; exit 1; }
done
# The upgrade backup must fail on unreadable critical files rather than hide them.
if grep -Fq -- '--ignore-failed-read' src/awg-update; then
  echo "READY_INSTALL_TEST=BACKUP_MUST_FAIL_CLOSED" >&2
  exit 1
fi
must src/awg-update 'GATEWAY_BACKUP_ERROR=ARCHIVE_CREATE_FAILED'
must src/awg-update 'GATEWAY_BACKUP=VERIFIED'
must src/awg-update 'tar -C / -xzf "$dir/gateway-state.tgz"'

# No executable is auto-run, and a legacy upgrade never enables READY priority.
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?MIHOMO_READY_AUTO_CANARY=1' install.sh src/awg-update; then
  echo "READY_INSTALL_TEST=UNSAFE_AUTO_ENABLE" >&2
  exit 1
fi
if grep -F 'systemctl enable' install.sh | grep -Eq 'ready-(live-match|postcheck)' ; then
  echo "READY_INSTALL_TEST=UNEXPECTED_AUTO_START" >&2
  exit 1
fi
python3 -B - <<'PY'
from pathlib import Path
s=Path('install.sh').read_text()
line=s.index('"$MIHOMO_NODE_POLICY_CLI" ready-auto enable')
start=s.rfind('if (( UPGRADE_EXISTING == 0 )); then',0,line)
end=s.find('fi',line)
assert start != -1 and end != -1
assert 'ready-auto enable' not in s[:start]
PY
echo READY_INSTALL_INTEGRATION=PASS
