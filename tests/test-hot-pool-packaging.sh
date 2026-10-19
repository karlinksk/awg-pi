#!/usr/bin/env bash
# Offline RC1 contract: passive, reproducible Hot Pool install and rollback.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh src/awg-update extras/mihomo-hot-pool-shadow/awg-mihomo-hot-continuity-run
python3 -B - <<'PY'
import ast
from pathlib import Path
root=Path('extras/mihomo-hot-pool-shadow')
for name in ('awg-mihomo-hot-pool.py','awg-mihomo-hot-service-scan.py','awg-mihomo-ip-connect-probe.py','awg-hot-pool-continuity.py'):
    ast.parse((root/name).read_text())
ins=Path('install.sh').read_text()
upd=Path('src/awg-update').read_text()
unit=(root/'awg-mihomo-hot-pool.service').read_text()
timer=(root/'awg-mihomo-hot-pool.timer').read_text()
standalone=(root/'install-shadow.sh').read_text()
files=('awg-mihomo-hot-pool','awg-mihomo-hot-service-scan','awg-mihomo-ip-connect-probe','awg-hot-pool-continuity.py','awg-mihomo-hot-continuity-run')
for file in files:
    assert ins.count('/usr/local/sbin/'+file)>=1, 'not installed '+file
    assert upd.count('usr/local/sbin/'+file)==2, 'backup/rollback missing '+file
for file in ('awg-mihomo-hot-pool.service','awg-mihomo-hot-pool.timer'):
    assert ins.count('extras/mihomo-hot-pool-shadow/'+file)==1, 'unit not installed'
    assert sum(line.strip().startswith('etc/systemd/system/'+file+' ') for line in upd.splitlines())==1, 'unit backup missing'
    assert sum(line.strip().startswith('/etc/systemd/system/'+file+' ') for line in upd.splitlines())==1, 'unit rollback missing'
assert upd.count('var/lib/awg-pbr/hot-pool')>=2
# Installer-first contract: both recent fixes ship on new installs AND
# existing-install upgrades, not only as one-off Pi changes.
assert 'install_project_helper src/awg-menu /usr/local/sbin/awg-menu' in ins
assert 'install_project_python_helper extras/mihomo-hot-pool-shadow/awg-mihomo-hot-pool.py' in ins
assert 'install_project_python_helper extras/mihomo-hot-pool-shadow/awg-mihomo-hot-service-scan.py' in ins
assert 'systemctl stop awg-mihomo-hot-pool.timer' in ins
assert 'cp -p --' in ins and 'cmp -s --' in ins
menu = Path('src/awg-menu').read_text()
assert 'status_args=(--provider' in menu and '"${status_args[@]}"' in menu
scheduler = (root/'awg-mihomo-hot-pool.py').read_text()
assert 'def protocol_discovery_penalties(' in scheduler
assert 'deprioritized = protocol_discovery_penalties(state, now)' in scheduler
assert 'install_project_helper src/awg-update' in ins  # release updater consumes install.sh
assert 'hot-pool-timer-state' in upd
assert 'systemctl enable --now awg-mihomo-hot-pool.timer' in upd
assert 'systemctl disable --now awg-mihomo-hot-pool.timer' in upd
assert 'systemctl is-active --quiet awg-mihomo-hot-pool.service' in ins
assert 'systemctl is-active --quiet awg-mihomo-hot-pool.timer' in ins
assert 'systemctl stop awg-mihomo-hot-pool.timer' in ins
assert 'systemctl start awg-mihomo-hot-pool.timer' in ins
assert 'systemctl daemon-reload' in ins
assert 'HOT_POOL_READY=' not in ins[ins.index('# Hot Pool is SHADOW_ONLY. Fetch verified components'):ins.index('install_project_helper src/awg-pbr-setup')]
assert '/usr/local/sbin/awg-mihomo-hot-continuity-run' in unit
assert 'ReadWritePaths=/run/awg-pbr /var/lib/awg-pbr/hot-pool/continuity /dev/shm' in unit
assert 'MemoryMax=900M' in unit and 'CPUQuota=70%' in unit
assert 'ProtectSystem=strict' in unit and 'NoNewPrivileges=true' in unit
assert 'Unit=awg-mihomo-hot-pool.service' in timer
assert 'systemctl enable awg-mihomo-hot-pool.timer' not in ins
assert 'systemctl start awg-mihomo-hot-pool.service' not in ins
assert 'systemctl enable --now awg-mihomo-hot-pool.timer' not in ins
for name in ('awg-mihomo-hot-pool.py','awg-mihomo-hot-service-scan.py','awg-mihomo-ip-connect-probe.py','awg-hot-pool-continuity.py','awg-mihomo-hot-continuity-run'):
    assert 'install -m 0755 "$source_dir/'+name+'"' in standalone, 'incomplete standalone shadow install '+name
assert '/var/lib/awg-pbr/hot-pool/continuity' in standalone
assert 'test_hot_pool_continuity.py' in standalone
assert '/bin/systemctl daemon-reload' in standalone
assert '/bin/systemctl enable' not in standalone

print("HOT_POOL_PASSIVE_PACKAGING=PASS")
PY
