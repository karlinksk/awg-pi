#!/usr/bin/env python3
"""Regression guard: classic menu uses native dialog until an actual SSH wheel fix is accepted."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeClassicDialog(unittest.TestCase):
    def test_dangerous_helper_not_connected(self):
        menu = (ROOT / "src/awg-menu").read_text()
        installer = (ROOT / "install.sh").read_text()
        self.assertNotIn("awg-classic-wheel.py", menu)
        self.assertNotIn("awg-classic-wheel.py", installer)
        self.assertIn('command dialog "${args[@]}"', menu)

    def test_appearance_screen_is_numbered(self):
        menu = (ROOT / "src/awg-menu").read_text()
        start = menu.index("appearance_menu(){")
        end = menu.index("\n}\n", start)
        body = menu[start:end]
        self.assertIn('1 "$(awg_option_label "Классическое"', body)
        self.assertIn('2 "$(awg_option_label "Matrix Gradient"', body)
        self.assertIn('0 "Назад"', body)


if __name__ == "__main__":
    unittest.main()
