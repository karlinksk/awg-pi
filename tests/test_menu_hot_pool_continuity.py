#!/usr/bin/env python3
"""Read-only dashboard regression for continuity-aware Hot Pool status."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'src'/'awg-menu').read_text()
def extract(name):
    a=SOURCE.index(name+'(){')
    b=SOURCE.index('\n}\n',a)
    return SOURCE[a:b+2]

class TestHotPoolMenu(unittest.TestCase):
    def run_case(self, *,continuity=True,state_present=True,timer=True,subscription=True,cli_ok=True):
        with tempfile.TemporaryDirectory(prefix='awg-hot-menu-') as d:
            r=Path(d)
            pool=r/'hot-pool';pool.write_text('#!/bin/sh\n');pool.chmod(0o755)
            hook=r/'continuity-run'
            if continuity:hook.write_text('#!/bin/sh\n');hook.chmod(0o755)
            live=r/'subscription.yaml'
            if subscription:live.write_text('test')
            union=r/'continuity';union.mkdir()
            for f in ('provider.yaml','pool.json','state.json'):
                if state_present or f!='state.json':(union/f).write_text('test')
            fn=extract('hot_pool_summary')
            for a,b in [
                ('/usr/local/sbin/awg-mihomo-hot-pool',str(pool)),
                ('/usr/local/sbin/awg-mihomo-hot-continuity-run',str(hook)),
                ('/var/lib/awg-pbr/mihomo/providers/subscription.yaml',str(live)),
                ('/run/awg-pbr/hot-pool/continuity',str(union))]:
                fn=fn.replace(a,b)
            shell="""set -Eeuo pipefail
systemctl() {
 [[ "$1" == is-active && "$2" == --quiet && "$3" == awg-mihomo-hot-pool.timer && "$MOCK_TIMER" == 1 ]]
}
timeout() {
 printf '%s\\n' "$*" > "$MOCK_LOG"
 [[ "$MOCK_CLI_OK" == 1 ]] || return 2
 printf '%s\\n' HOT_POOL_MODE=SHADOW_ONLY HOT_POOL_READY=1 HOT_POOL_TARGET_READY=4
}
""" + fn + '\nhot_pool_summary\n'
            log=r/'calls'
            env=dict(os.environ,MOCK_TIMER='1' if timer else '0',
                     MOCK_CLI_OK='1' if cli_ok else '0',MOCK_LOG=str(log))
            done=subprocess.run(['bash','-c',shell],env=env,text=True,capture_output=True,timeout=5)
            self.assertEqual(done.returncode,0,done.stderr)
            return done.stdout,(log.read_text() if log.exists() else ''),str(union)

    def test_active_continuity_uses_exact_union_state(self):
        output,call,union=self.run_case()
        self.assertEqual(output,'READY 1/4')
        self.assertIn('--provider '+union+'/provider.yaml',call)
        self.assertIn('--pool '+union+'/pool.json',call)
        self.assertIn('--state '+union+'/state.json',call)
        self.assertTrue(call.strip().endswith(' status'))
    def test_missing_state_never_false_zero(self):
        output,call,_=self.run_case(state_present=False)
        self.assertEqual(output,'ожидает проверки')
        self.assertEqual(call,'')
    def test_legacy_does_not_need_union(self):
        output,call,_=self.run_case(continuity=False)
        self.assertEqual(output,'READY 1/4')
        self.assertNotIn('--state',call)
        self.assertTrue(call.strip().endswith('hot-pool status'))
    def test_timer_disabled(self):
        output,call,_=self.run_case(timer=False)
        self.assertEqual(output,'автопроверка выключена')
        self.assertEqual(call,'')
    def test_subscription_missing(self):
        output,call,_=self.run_case(subscription=False)
        self.assertEqual(output,'ожидает подписку')
        self.assertEqual(call,'')
    def test_status_failure_is_not_zero_ready(self):
        output,call,_=self.run_case(cli_ok=False)
        self.assertEqual(output,'не проверено')
        self.assertIn('--state',call)

if __name__=='__main__':
    unittest.main()
