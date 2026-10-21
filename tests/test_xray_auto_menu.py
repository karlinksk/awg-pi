#!/usr/bin/env python3
"""Regression: Xray AUTO submenu must pass all options to dialog.

Bash -n cannot detect doubled backslashes on continuation lines.
The dynamic test extracts just the menu function, mocks dialog and never
calls a live policy, systemd, routing, or VPN process.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "src/awg-menu"
POLICY = ROOT / "src/awg-mihomo-node-policy"


class XrayAutoMenu(unittest.TestCase):
    def menu_section(self):
        s = MENU.read_text()
        return "mihomo_xray_auto_menu(){" + s.split(
            "mihomo_xray_auto_menu(){", 1
        )[1].split("\nmihomo_node_policy_menu(){", 1)[0]

    def test_every_dialog_continuation_has_one_backslash(self):
        section = self.menu_section()
        continuation = [line for line in section.splitlines()
                        if line.rstrip().endswith(chr(92))]
        self.assertEqual(len(continuation), 5)
        for line in continuation:
            self.assertTrue(line.endswith(chr(92)), repr(line))
            self.assertFalse(line.endswith(chr(92) * 2), repr(line))
        self.assertIn("8) mihomo_xray_auto_menu ;;", MENU.read_text())

    def test_dialog_receives_complete_menu(self):
        # The double-slash bug made --menu the last useful dialog argument.
        # Stub returns Cancel: no state-changing action can run.
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dialog-args"
            shell = (
                'BACKTITLE=TEST\nMIHOMO_NODE_POLICY=/bin/true\n'
                'dialog() { printf "%s\\n" "$@" > "$OUT"; return 1; }\n'
                + self.menu_section() + '\n'
                'mihomo_xray_auto_menu\n'
            )
            process = subprocess.run(
                ["bash", "-c", shell], env={**os.environ, "OUT": str(output)},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(output.is_file(), process.stderr)
            args = output.read_text().splitlines()
            self.assertIn("--menu", args)
            self.assertIn("Включить Xray в AUTO", args)
            self.assertIn("Выключить Xray в AUTO", args)
            self.assertIn("Показать состояние", args)
            self.assertIn("Назад", args)
            self.assertEqual(args.count("0"), 1)
            self.assertEqual(args.count("1"), 1)
            self.assertEqual(args.count("2"), 1)
            self.assertEqual(args.count("3"), 1)

    def test_status_format_and_syntax(self):
        s = POLICY.read_text()
        self.assertIn("printf 'MIHOMO_XRAY_AUTO=%s\\n'", s)
        self.assertNotIn("printf 'MIHOMO_XRAY_AUTO=%s\\\\n'", s)
        for path in [MENU, POLICY]:
            result = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
