#!/usr/bin/env bash
# Unified AUTO delivery and safety regressions replacing READY install contract.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh src/awg-update src/awg-mihomo-node-policy src/awg-menu
python3 -B tests/test_ready_auto_canary.py
python3 -B tests/test_unified_recovery_policy.py
python3 -B tests/test_unified_subscription_churn.py
python3 -B tests/test_unified_manual_independence.py
python3 -B - <<'PY'
from pathlib import Path
ins=Path('install.sh').read_text()
upd=Path('src/awg-update').read_text()
policy=Path('src/awg-mihomo-node-policy').read_text()
for source in ('awg-mihomo-node-policy','awg-menu','awg-selection-monitor'):
    assert 'install_project_helper src/'+source in ins
assert 'python3-minimal python3-yaml' in ins
for source in ('awg-mihomo-node-policy','awg-mihomo-unified-nodes',
               'awg-xray-manual-switch'):
    assert 'usr/local/sbin/'+source in upd
assert '--ignore-failed-read' not in upd
for contract in ('GATEWAY_BACKUP_ERROR=ARCHIVE_CREATE_FAILED',
                 'GATEWAY_BACKUP=VERIFIED', 'tar -C / -xzf "$dir/gateway-state.tgz"'):
    assert contract in upd
entry=policy.split('failover(){',1)[1].split('\n}\n',1)[0]
assert 'failover_unified "$current"' in entry
assert 'failover_auto "$current"' not in entry
assert 'MIHOMO_READY_AUTO_CANARY' not in entry
assert 'UNIFIED_INVENTORY_MISSING' in entry
print('UNIFIED_INSTALL_INTEGRATION=PASS_OFFLINE_ONLY')
PY
