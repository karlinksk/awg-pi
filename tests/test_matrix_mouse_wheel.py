#!/usr/bin/env python3
"""Matrix wheel: one arrow per xterm mouse event, keyboard unchanged.

No real tmux, gateway state, SSH session, or Pi settings are involved.
"""
import collections
import curses
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "extras/awg-matrix-compositor.py"
spec = importlib.util.spec_from_file_location("matrix_wheel", SOURCE)
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class InputQueue:
    def __init__(self, keys):
        self.keys = collections.deque(keys)

    def get_wch(self):
        if not self.keys:
            raise curses.error()
        return self.keys.popleft()


class MatrixMouseWheel(unittest.TestCase):
    def forward(self, keys, buttons):
        sent = []
        events = iter(buttons)
        with patch.object(matrix, "tmux", side_effect=lambda *args: sent.append(args)):
            with patch.object(matrix.curses, "getmouse",
                              side_effect=lambda: (0, 10, 9, 0, next(events))):
                self.assertFalse(matrix.forward_pending_input(InputQueue(keys)))
        return sent

    def test_each_up_and_down_wheel_event_moves_one_row(self):
        keys = [curses.KEY_MOUSE] * 4
        states = [curses.BUTTON4_PRESSED, curses.BUTTON5_PRESSED,
                  curses.BUTTON5_PRESSED, curses.BUTTON4_PRESSED]
        self.assertEqual(
            self.forward(keys, states),
            [("send-keys", "-t", "menu:0.0", key)
             for key in ("Up", "Down", "Down", "Up")],
        )

    def test_non_wheel_mouse_events_never_select_a_menu_entry(self):
        self.assertEqual(self.forward([curses.KEY_MOUSE], [0]), [])
        self.assertEqual(self.forward([curses.KEY_MOUSE], [curses.BUTTON1_PRESSED]), [])

    def test_mouse_input_flushed_after_text_and_before_keyboard(self):
        self.assertEqual(
            self.forward(["a", "b", curses.KEY_MOUSE, curses.KEY_DOWN,
                          curses.KEY_MOUSE, "\r", "\x1b"],
                         [curses.BUTTON5_PRESSED, curses.BUTTON4_PRESSED]),
            [
                ("send-keys", "-t", "menu:0.0", "-l", "--", "ab"),
                ("send-keys", "-t", "menu:0.0", "Down"),
                ("send-keys", "-t", "menu:0.0", "Down"),
                ("send-keys", "-t", "menu:0.0", "Up"),
                ("send-keys", "-t", "menu:0.0", "Enter"),
                ("send-keys", "-t", "menu:0.0", "Escape"),
            ],
        )

    def test_missing_mouse_event_is_ignored_without_losing_keyboard(self):
        sent = []
        with patch.object(matrix, "tmux", side_effect=lambda *args: sent.append(args)):
            with patch.object(matrix.curses, "getmouse", side_effect=curses.error()):
                matrix.forward_pending_input(
                    InputQueue([curses.KEY_MOUSE, curses.KEY_UP]))
        self.assertEqual(sent, [("send-keys", "-t", "menu:0.0", "Up")])

    def test_only_matrix_requests_wheel_tracking_and_cleans_up(self):
        src = SOURCE.read_text()
        self.assertIn("curses.BUTTON4_PRESSED | curses.BUTTON5_PRESSED", src)
        self.assertIn("curses.mouseinterval(0)", src)
        self.assertIn("curses.wrapper(run_with_mouse_cleanup)", src)
        self.assertIn("curses.mousemask(0)", src)
        # No classic menu changes, no retired PTY interceptor.
        menu = (SOURCE.parents[1] / "src/awg-menu").read_text()
        self.assertNotIn("awg-classic-wheel.py", menu)

    def test_tracking_is_disabled_even_after_main_failure(self):
        calls = []
        with patch.object(matrix, "main", side_effect=RuntimeError("render stopped")):
            with patch.object(matrix.curses, "mousemask",
                              side_effect=lambda mask: calls.append(mask)):
                with self.assertRaisesRegex(RuntimeError, "render stopped"):
                    matrix.run_with_mouse_cleanup(None)
        self.assertEqual(calls, [0])


if __name__ == "__main__":
    unittest.main()
