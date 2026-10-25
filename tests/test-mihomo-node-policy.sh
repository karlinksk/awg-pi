#!/usr/bin/env bash
# Current AUTO entry contract; no sudo, live services or provider credentials.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
python3 -B tests/test_unified_recovery_policy.py
python3 -B tests/test_unified_manual_independence.py
python3 -B - <<'PY'
import os
from pathlib import Path
import subprocess
import tempfile
s=Path('src/awg-mihomo-node-policy').read_text()
entry='failover(){'+s.split('failover(){',1)[1].split('\n}\n',1)[0]+'\n}\n'
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    node=root/'node';node.write_text('current\n')
    helper=root/'inventory';helper.write_text('#!/bin/sh\nexit 0\n');helper.chmod(0o700)
    actions=root/'actions'
    script='''set -Eeuo pipefail
mode_get(){ echo "$MODE"; }
is_enabled(){ [[ "$ENABLED" == 1 ]]; }
failover_unified(){ printf 'unified:%s\\n' "$1" >> "$ACTIONS"; }
'''+entry+'\nfailover\n'
    def run(mode='auto',enabled='1',inventory=None):
        actions.write_text('')
        return subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=3,
          env=dict(os.environ,MODE=mode,ENABLED=enabled,ACTIONS=str(actions),
                   MIHOMO_NODE_NAME_FILE=str(node),
                   MIHOMO_UNIFIED_NODE_CLI=str(inventory or helper)))
    for mode in ('manual','fixed','invalid'):
        assert run(mode).returncode != 0, mode
        assert actions.read_text() == '', mode
    assert run(enabled='0').returncode != 0
    assert actions.read_text() == ''
    assert run().returncode == 0
    assert actions.read_text() == 'unified:current\n'
    r=run(inventory=root/'missing')
    assert r.returncode != 0 and 'UNIFIED_INVENTORY_MISSING' in r.stderr
    assert actions.read_text() == ''
    helper.chmod(0o600)
    assert run().returncode != 0
    assert actions.read_text() == ''
    helper.chmod(0o700);node.write_text('')
    assert run().returncode != 0
    assert actions.read_text() == ''
print('UNIFIED_NODE_POLICY_ENTRY=PASS_OFFLINE_ONLY')
PY
