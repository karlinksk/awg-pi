#!/usr/bin/env python3
"""Matrix rain: visible glyphs flicker as the unchanged trails fall.

Pure rendering-loop tests, no curses screen, SSH session, VPN or config writes.
"""
from pathlib import Path
import ast
import random
import textwrap
import unittest

SOURCE = (Path(__file__).resolve().parents[1] /
          "extras/awg-matrix-compositor.py").read_text()

START = "        for i,s in enumerate(streams):\n"
END = "        for y,row in enumerate(captured):\n"


def draw_once(streams, random_state, dt=0.05, height=40):
    source = SOURCE.split(START, 1)[1].split(END, 1)[0]
    statement = textwrap.dedent(START + source)

    class DummyCurses:
        error = RuntimeError

        @staticmethod
        def color_pair(number):
            return number

    class DummyScreen:
        def __init__(self):
            self.cells = []

        def addstr(self, y, x, glyph, color):
            self.cells.append((y, x, glyph, color))

    screen = DummyScreen()
    exec(compile(statement, "<Matrix stream-only draw>", "exec"),
         {"streams": streams, "stdscr": screen, "curses": DummyCurses,
          "rng": random_state, "dt": dt, "h": height,
          "GLYPHS": ast.literal_eval(SOURCE.split("GLYPHS = ", 1)[1].splitlines()[0])})
    return screen.cells


class MatrixRainFlicker(unittest.TestCase):
    def test_each_raindrop_changes_glyphs_without_changing_motion(self):
        rng = random.Random(20261025)
        initial = "A" * 9
        stream = {"y": 14.0, "speed": 4.0, "len": 9,
                  "chars": list(initial) + ["X"] * 8}
        streams = [stream]
        total_changes = 0
        frames_with_many_changes = 0
        for frame in range(25):
            before = list(stream["chars"])
            old_y = stream["y"]
            displayed = draw_once(streams, rng)
            changes = sum(a != b for a, b in zip(before, stream["chars"]))
            total_changes += changes
            if changes >= 3:
                frames_with_many_changes += 1
            self.assertAlmostEqual(stream["y"], old_y + 4.0 * 0.05)
            self.assertEqual(stream["speed"], 4.0)
            self.assertEqual(stream["len"], 9)
            self.assertEqual(len(displayed), 9)
            self.assertTrue(all(x == 0 for _, x, _, _ in displayed))
            # Unchanged gradient distribution along the nine-position trail.
            expected = [1 + min(6, k * 7 // 8) for k in range(9)]
            self.assertEqual([color for _, _, _, color in displayed], expected)
        self.assertGreater(total_changes, 40)
        self.assertLess(total_changes, 85)
        self.assertGreater(frames_with_many_changes, 7)

    def test_spacing_palette_geometry_and_global_render_rate_unchanged(self):
        self.assertIn("for _ in range(0,w,2)", SOURCE)
        self.assertIn('"speed":rng.uniform(3,7)', SOURCE)
        self.assertIn('"len":rng.randrange(9,17)', SOURCE)
        self.assertIn("time.sleep(max(0,1/20-(time.monotonic()-now)))", SOURCE)
        self.assertIn("PALETTE = [(190,255,190),(90,255,90)", SOURCE)
        self.assertIn('rng.random()<min(1.0,dt*6.0)', SOURCE)
        self.assertNotIn('rng.random()<min(1.0,dt*12.0)', SOURCE)
        self.assertNotIn('rng.random()<dt*1.5', SOURCE)


if __name__ == "__main__":
    unittest.main()
