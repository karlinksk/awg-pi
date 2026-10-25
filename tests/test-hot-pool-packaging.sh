#!/usr/bin/env bash
# Simplified installer contract and legacy rollback preservation, offline only.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh src/awg-update
python3 -B tests/test_installer_auto_strategy.py
python3 -B - <<'PY'
from pathlib import Path
ins=Path('install.sh').read_text()
upd=Path('src/awg-update').read_text()
assert 'install_project_unit extras/mihomo-hot-pool-shadow/' not in ins
for name in ('awg-mihomo-hot-pool.py','awg-mihomo-hot-service-scan.py',
             'awg-hot-pool-continuity.py'):
    assert 'install_project_python_helper extras/mihomo-hot-pool-shadow/'+name not in ins
assert '"$MIHOMO_NODE_POLICY_CLI" ready-auto enable' not in ins
assert '"$MIHOMO_NODE_POLICY_CLI" ready-auto disable' not in ins
assert '"$SELECTION_CLI" mode auto mihomo awg' in ins
assert 'UPGRADE_HOT_TIMER_ENABLEMENT=' in ins
assert 'UPGRADE_HOT_TIMER_RUNTIME=' in ins
assert 'if [[ "$UPGRADE_HOT_TIMER_ENABLEMENT" != absent ]]; then' in ins
# Preserve rollback of preexisting legacy state without reinstalling it.
for name in ('awg-mihomo-hot-pool','awg-mihomo-hot-service-scan',
             'awg-hot-pool-continuity.py','awg-mihomo-hot-continuity-run'):
    assert upd.count('usr/local/sbin/'+name)==2, name
assert 'hot-pool-timer-state' in upd
assert 'var/lib/awg-pbr/hot-pool' in upd
assert 'systemctl enable --now awg-mihomo-hot-pool.timer' in upd
assert 'systemctl disable --now awg-mihomo-hot-pool.timer' in upd
menu=Path('src/awg-menu').read_text()
top=menu.split('mihomo_node_policy_menu(){',1)[1].split('\n}\n',1)[0]
assert '5) mihomo_auto_strategy_menu' not in top
assert '3) mihomo_node_chain_editor' not in top
print('SIMPLIFIED_AUTO_PACKAGING=PASS_OFFLINE_ONLY')
PY
