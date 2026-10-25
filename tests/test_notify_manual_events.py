"""Passive NODE_SWITCH hooks: committed MANUAL only; Telegram can never gate VPN."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/"src/awg-xray-manual-switch.py"
spec=importlib.util.spec_from_file_location("notify_xray_manual",source)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)


class ManualNotificationContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.config=base/"telegram.json"
        self.notifier=base/"awg-notify"
        self.config.write_text("private-placeholder")
        self.notifier.write_text("stub")
        self.finder=lambda path: (
            self.config if "telegram.json" in path else self.notifier
        )

    def test_xray_manual_enqueue_after_timer_enabled(self):
        calls=[]
        def cli(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0)
        with mock.patch.object(module,"Path",side_effect=self.finder):
            with mock.patch.object(module.subprocess,"run",side_effect=cli):
                module.notify_manual_node_change("Xray VLESS","Netherlands 1")
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][:3],
                         ["systemctl","is-enabled","--quiet"])
        self.assertEqual(calls[1][0],str(self.notifier))
        self.assertEqual(calls[1][1:5],
                         ["emit","--kind","NODE_SWITCH","--severity"])
        self.assertIn("Netherlands 1",calls[1][-1])
        self.assertNotIn("http",calls[1][-1])
        self.assertEqual(calls[1][-2],"--text")

    def test_disabled_delivery_does_not_emit(self):
        calls=[]
        def cli(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,1)
        with mock.patch.object(module,"Path",side_effect=self.finder):
            with mock.patch.object(module.subprocess,"run",side_effect=cli):
                module.notify_manual_node_change("Mihomo native","Node A")
        self.assertEqual(len(calls),1)

    def test_unreadable_config_is_not_a_switch_failure(self):
        class Unreadable:
            def is_file(self):raise PermissionError("root-owned")
        with mock.patch.object(module,"Path",return_value=Unreadable()):
            with mock.patch.object(module.subprocess,"run") as run:
                module.notify_manual_node_change("Xray VLESS","Node A")
        run.assert_not_called()

    def test_failed_event_enqueue_never_rolls_back_node(self):
        calls=[]
        def cli(args,**kwargs):
            calls.append(args)
            if len(calls)==2:raise subprocess.TimeoutExpired(args,2)
            return subprocess.CompletedProcess(args,0)
        with mock.patch.object(module,"Path",side_effect=self.finder):
            with mock.patch.object(module.subprocess,"run",side_effect=cli):
                module.notify_manual_node_change("Xray VLESS","Node B")
        self.assertEqual(len(calls),2)

    def test_node_label_control_chars_are_stripped(self):
        calls=[]
        def cli(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0)
        with mock.patch.object(module,"Path",side_effect=self.finder):
            with mock.patch.object(module.subprocess,"run",side_effect=cli):
                module.notify_manual_node_change("Xray VLESS","Finland\nTest")
        self.assertIn("Finland Test",calls[-1][-1])

    def test_mihomo_hook_skips_auto_standby_and_only_runs_after_commit(self):
        script=(ROOT/"src/awg-mihomo-configure").read_text()
        begin=script.index("node_select(){")
        end=script.index("node_select_auto(){",begin)
        selection=script[begin:end]
        self.assertIn('"${MIHOMO_NODE_FAILOVER_RECOVERY:-0}" != 1',script)
        self.assertIn('"${AWG_NOTIFY_AUTOMATIC:-0}" != 1',script)
        self.assertIn('if [[ "$current" == mihomo ]]; then\n    notify_manual_native_node',selection)
        self.assertLess(selection.index("trap - ERR\n  rm -rf"),selection.index('notify_manual_native_node "$previous_name" "$name"'))
        self.assertIn('timeout 2s /usr/local/sbin/awg-notify emit --kind NODE_SWITCH',script)

    def test_xray_native_hooks_are_postcommit_only(self):
        script=(ROOT/"src/awg-xray-manual-switch.py").read_text()
        native=script.split("def native_return(name):",1)[1].split("def ",1)[0]
        xray=script.split("def apply(index):",1)[1].split("def ",1)[0]
        for body,hook in ((native,'notify_manual_node_change("Mihomo native",name)'),
                          (xray,'notify_manual_node_change("Xray VLESS",info["candidate"])')):
            self.assertLess(body.index('stored(path,state,"committed")'),body.index(hook))
            self.assertLess(body.index('cmd("systemctl","stop",timer)'),body.index(hook))


if __name__=="__main__":
    unittest.main()
