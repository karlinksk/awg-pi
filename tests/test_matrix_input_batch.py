#!/usr/bin/env python3
"""Clipboard input throughput/order in Matrix; no tmux, sudo, or VPN is used."""
import collections
import curses
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "extras/awg-matrix-compositor.py"
spec = importlib.util.spec_from_file_location("awg_matrix_compositor_test", SOURCE)
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class QueuedKeys:
    def __init__(self, keys):
        self.keys = collections.deque(keys)
        self.reads = 0

    def get_wch(self):
        self.reads += 1
        if not self.keys:
            raise curses.error()
        return self.keys.popleft()


class MatrixInputBatch(unittest.TestCase):
    def forward(self, keys):
        screen = QueuedKeys(keys)
        sent = []
        old_tmux = matrix.tmux
        matrix.tmux = lambda *args: sent.append(args)
        try:
            quit_requested = matrix.forward_pending_input(screen)
        finally:
            matrix.tmux = old_tmux
        return sent, screen, quit_requested

    @staticmethod
    def literal_data(sent):
        return "".join(call[-1] for call in sent if "-l" in call)

    def test_large_unicode_paste_is_batched_not_limited_by_frame_rate(self):
        text = "-[Interface]\n".split("\n")[0] + "ключ=значение" * 1000
        sent, screen, quit_requested = self.forward(text)
        self.assertFalse(quit_requested)
        self.assertFalse(screen.keys)
        self.assertEqual(self.literal_data(sent), text)
        self.assertEqual(len(sent), 7)  # ceil(len(text)/2048)
        self.assertTrue(all(call[:5] ==
                            ("send-keys", "-t", "menu:0.0", "-l", "--")
                            for call in sent))

    def test_editbox_multiline_paste_and_followup_keyboard_order(self):
        # Enter is kept as an editbox newline, not swallowed or synthesized.
        config = "[Interface]\nAddress = 10.0.0.2/32\n[Peer]\nEndpoint = example.invalid:1234"
        keys = list(config) + [curses.KEY_LEFT, "X", "\x7f", "\t", "\x1b"]
        sent, screen, stopped = self.forward(keys)
        self.assertFalse(stopped)
        self.assertFalse(screen.keys)
        self.assertEqual(sent, [
            ("send-keys", "-t", "menu:0.0", "-l", "--", "[Interface]"),
            ("send-keys", "-t", "menu:0.0", "Enter"),
            ("send-keys", "-t", "menu:0.0", "-l", "--", "Address = 10.0.0.2/32"),
            ("send-keys", "-t", "menu:0.0", "Enter"),
            ("send-keys", "-t", "menu:0.0", "-l", "--", "[Peer]"),
            ("send-keys", "-t", "menu:0.0", "Enter"),
            ("send-keys", "-t", "menu:0.0", "-l", "--", "Endpoint = example.invalid:1234"),
            ("send-keys", "-t", "menu:0.0", "Left"),
            ("send-keys", "-t", "menu:0.0", "-l", "--", "X"),
            ("send-keys", "-t", "menu:0.0", "BSpace"),
            ("send-keys", "-t", "menu:0.0", "Tab"),
            ("send-keys", "-t", "menu:0.0", "Escape"),
        ])

    def test_single_line_prompt_confirm_and_cancel_remain_separate(self):
        sent, _, stopped = self.forward(list("my-value") + ["\r", "Z", "\x03"])
        self.assertTrue(stopped)
        self.assertEqual(sent, [
            ("send-keys", "-t", "menu:0.0", "-l", "--", "my-value"),
            ("send-keys", "-t", "menu:0.0", "Enter"),
            ("send-keys", "-t", "menu:0.0", "-l", "--", "Z"),
        ])

    def test_huge_paste_is_bounded_per_frame_without_loss(self):
        text = "a" * 12000
        screen = QueuedKeys(text)
        sent = []
        original = matrix.tmux
        matrix.tmux = lambda *args: sent.append(args)
        try:
            self.assertFalse(matrix.forward_pending_input(screen))
            self.assertEqual(len(screen.keys), 12000 - 8192)
            self.assertEqual(self.literal_data(sent), "a" * 8192)
            self.assertFalse(matrix.forward_pending_input(screen))
            self.assertEqual(self.literal_data(sent), text)
            self.assertFalse(screen.keys)
        finally:
            matrix.tmux = original


if __name__ == "__main__":
    unittest.main()
