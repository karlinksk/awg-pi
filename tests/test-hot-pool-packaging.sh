#!/usr/bin/env bash
# Offline RC1 contract: passive, reproducible Hot Pool install and rollback.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh src/awg-update extras/mihomo-hot-pool-shadow/awg-mihomo-hot-continuity-run
python3 -B - <<'PY'
import ast
from pathlib import Path
root=Path('extras/mihomo-hot-pool-shadow')
for name in ('awg-mihomo-hot-pool.py','awg-mihomo-hot-service-scan.py','awg-hot-pool-continuity.py'):
    ast.parse((root/name).read_text())
ins=Path('install.sh').read_text()
upd=Path('src/awg-update').read_text()
unit=(root/'awg-mihomo-hot-pool.service').read_text()
timer=(root/'awg-mihomo-hot-pool.timer').read_text()
files=('awg-mihomo-hot-pool','awg-mihomo-hot-service-scan','awg-hot-pool-continuity.py','awg-mihomo-hot-continuity-run')
for file in files:
    assert ins.count('/usr/local/sbin/'+file)>=1, 'not installed '+file
    assert upd.count('usr/local/sbin/'+file)==2, 'backup/rollback missing '+file
for file in ('awg-mihomo-hot-pool.service','awg-mihomo-hot-pool.timer'):
    assert ins.count('extras/mihomo-hot-pool-shadow/'+file)==1, 'unit not installed'
    assert sum(line.strip().startswith('etc/systemd/system/'+file+' ') for line in upd.splitlines())==1, 'unit backup missing'
    assert sum(line.strip().startswith('/etc/systemd/system/'+file+' ') for line in upd.splitlines())==1, 'unit rollback missing'
assert upd.count('var/lib/awg-pbr/hot-pool')>=2
assert 'hot-pool-timer-state' in upd
assert 'systemctl enable --now awg-mihomo-hot-pool.timer' in upd
assert 'systemctl disable --now awg-mihomo-hot-pool.timer' in upd
assert 'systemctl is-active --quiet awg-mihomo-hot-pool.service' in ins
assert 'systemctl is-active --quiet awg-mihomo-hot-pool.timer' in ins
assert 'systemctl is-enabled awg-mihomo-hot-pool.timer' in ins
assert '/usr/local/sbin/awg-mihomo-hot-continuity-run' in unit
assert 'ReadWritePaths=/run/awg-pbr /var/lib/awg-pbr/hot-pool/continuity /dev/shm' in unit
assert 'MemoryMax=900M' in unit and 'CPUQuota=70%' in unit
assert 'ProtectSystem=strict' in unit and 'NoNewPrivileges=true' in unit
assert 'Unit=awg-mihomo-hot-pool.service' in timer
assert 'systemctl enable awg-mihomo-hot-pool.timer' not in ins
assert 'systemctl start awg-mihomo-hot-pool.service' not in ins
assert 'systemctl enable --now awg-mihomo-hot-pool.timer' not in ins
print("HOT_POOL_PASSIVE_PACKAGING=PASS")
PY
