#!/usr/bin/env python3
"""Matrix click keyboard-navigation regressions. No gateway writes or tmux."""
import collections
import curses
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "extras/awg-matrix-compositor.py"
spec = importlib.util.spec_from_file_location("matrix_clicks", SOURCE)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
W, H = 90, 28

def cell(ch=" ", fg=7, bg=4, bold=False):
    return (ch, fg, bg, bold)

def screen(selected_index=0):
    rows = [[cell() for _ in range(W)] for _ in range(H)]
    for index, (tag, label) in enumerate([
            ("1", "Первая"), ("2", "Вторая"),
            ("3", "Третья"), ("0", "Назад")]):
        y = 8 + index
        selected = index == selected_index
        rows[y][29] = cell(tag, 3 if selected else 6, 0 if selected else 4, True)
        for i, letter in enumerate(label):
            rows[y][33 + i] = cell(letter, 7, 0 if selected else 4, selected)
    for i, ch in enumerate("< ОК >       <Отмена>"):
        selected = i < 6
        rows[23][30 + i] = cell(ch, 7, 0 if selected else 4, selected)
    return rows

class Input:
    def __init__(self, keys):
        self.keys = collections.deque(keys)
    def get_wch(self):
        if not self.keys:
            raise curses.error()
        return self.keys.popleft()

class MouseClicks(unittest.TestCase):
    def test_click_selects_row_but_never_activates_it(self):
        s = screen()
        self.assertEqual(ui.menu_keys_for_click(s, 35, 10), ("Down", "Down"))
        self.assertEqual(ui.menu_keys_for_click(s, 29, 11), ("Down",)*3)
        self.assertEqual(ui.menu_keys_for_click(s, 35, 8), ())
        self.assertEqual(ui.menu_keys_for_click(s, 35, 8, activate_selected=True),
                         ("Enter",))

    def test_ok_cancel_close_buttons(self):
        s = screen()
        self.assertEqual(ui.menu_keys_for_click(s, 33, 23), ("Enter",))
        self.assertEqual(ui.menu_keys_for_click(s, 46, 23), ("Tab", "Enter"))
        close = [[cell() for _ in range(W)] for _ in range(H)]
        for i, ch in enumerate("<Закрыть>", 40):
            close[24][i] = cell(ch, 7, 0, True)
        self.assertEqual(ui.menu_keys_for_click(close, 44, 24), ("Enter",))
        # Prose that happens to contain <Закрыть> must not act as a button.
        for i, ch in enumerate("<Закрыть>", 40):
            close[24][i] = cell(ch, 7, 4, False)
        self.assertEqual(ui.menu_keys_for_click(close, 44, 24), ())

    def test_background_and_invalid_regions_are_ignored(self):
        s = screen()
        for x,y in ((5,10),(35,12),(31,7),(40,21),(12,23),(999,2),(-1,10)):
            with self.subTest(x=x,y=y):
                self.assertEqual(ui.menu_keys_for_click(s,x,y), ())
        # Two simultaneously selected rows are ambiguous: do nothing.
        s[9][29] = cell("2", 3, 0, True)
        for i,ch in enumerate("Вторая"):
            s[9][33+i] = cell(ch,7,0,True)
        self.assertEqual(ui.menu_keys_for_click(s,35,10), ())
        s = screen()
        for i,ch in enumerate("<Help>",70):
            s[23][i] = cell(ch,7,4,False)
        self.assertEqual(ui.menu_keys_for_click(s,46,23), ())

    def test_input_field_is_not_treated_as_menu(self):
        s = [[cell() for _ in range(W)] for _ in range(H)]
        for i,ch in enumerate("User input"):
            s[10][30+i] = cell(ch,7,0,True)
        self.assertEqual(ui.menu_keys_for_click(s,33,10), ())

    def test_press_release_then_button_and_wheel_preserve_order(self):
        s = screen()
        sent = []
        events = iter([
            (0,35,10,0,curses.BUTTON1_PRESSED),
            (0,35,10,0,curses.BUTTON1_RELEASED),
            (0,33,23,0,curses.BUTTON1_PRESSED),
            (0,33,23,0,curses.BUTTON1_RELEASED),
            (0,20,8,0,curses.BUTTON5_PRESSED),
        ])
        def tmux(*args,**kwargs):
            if args[0] == "capture-pane":
                return "\n".join("row"+str(i) for i in range(H)) + "\n"
            sent.append(args)
            return ""
        with patch.object(ui,"tmux",side_effect=tmux), \
             patch.object(ui,"parse_line",side_effect=lambda line,w:s[int(line[3:])]), \
             patch.object(ui.curses,"getmouse",side_effect=lambda:next(events)):
            ui.forward_pending_input(Input([curses.KEY_MOUSE]*5), s, {})
        self.assertEqual(sent, [
            ("send-keys","-t","menu:0.0","Down","Down"),
            ("send-keys","-t","menu:0.0","Enter"),
            ("send-keys","-t","menu:0.0","Down"),
        ])


    def test_second_separate_click_on_selected_item_activates_once(self):
        selected_first = screen()
        selected_third = screen(selected_index=2)
        state, sent = {}, []
        active = [selected_first]

        def fake_tmux(*args, **kwargs):
            if args[0] == "capture-pane":
                return "\n".join("row" + str(i) for i in range(H)) + "\n"
            sent.append(args)
            return ""

        with patch.object(ui, "tmux", side_effect=fake_tmux), \
             patch.object(ui, "parse_line",
                          side_effect=lambda line, width: active[0][int(line[3:])]):
            # First click selects Third, but must not execute any operation.
            ui.forward_verified_click(35, 10, selected_first, state)
            self.assertEqual(sent, [
                ("send-keys", "-t", "menu:0.0", "Down", "Down"),
            ])
            active[0] = selected_third
            ui.forward_verified_click(35, 10, selected_third, state)
            self.assertEqual(sent[-1],
                             ("send-keys", "-t", "menu:0.0", "Enter"))
            self.assertNotIn("armed_item", state)

    def test_preselected_item_requires_two_independent_clicks(self):
        s = screen()
        state, sent = {}, []
        def fake_tmux(*args, **kwargs):
            if args[0] == "capture-pane":
                return "\n".join("row" + str(i) for i in range(H)) + "\n"
            sent.append(args)
            return ""

        with patch.object(ui, "tmux", side_effect=fake_tmux), \
             patch.object(ui, "parse_line",
                          side_effect=lambda line, width: s[int(line[3:])]):
            ui.forward_verified_click(35, 8, s, state)
            self.assertEqual(sent, [])
            ui.forward_verified_click(35, 8, s, state)
            self.assertEqual(sent, [
                ("send-keys", "-t", "menu:0.0", "Enter")])

    def test_release_then_clicked_is_one_physical_click_not_two(self):
        initial, selected = screen(), screen(selected_index=2)
        state, sent = {}, []
        active = [initial]
        events = iter([
            (0, 35, 10, 0, curses.BUTTON1_PRESSED),
            (0, 35, 10, 0, curses.BUTTON1_RELEASED),
            (0, 35, 10, 0, curses.BUTTON1_CLICKED),
        ])
        def fake_tmux(*args, **kwargs):
            if args[0] == "capture-pane":
                return "\n".join("row" + str(i) for i in range(H)) + "\n"
            sent.append(args)
            return ""

        with patch.object(ui, "tmux", side_effect=fake_tmux), \
             patch.object(ui, "parse_line",
                          side_effect=lambda line, width: active[0][int(line[3:])]), \
             patch.object(ui.curses, "getmouse", side_effect=lambda: next(events)):
            ui.forward_pending_input(Input([curses.KEY_MOUSE] * 3), initial, state)
            self.assertEqual(sent, [
                ("send-keys", "-t", "menu:0.0", "Down", "Down")])
            active[0] = selected
            followup = iter([
                (0, 35, 10, 0, curses.BUTTON1_PRESSED),
                (0, 35, 10, 0, curses.BUTTON1_RELEASED),
            ])
            with patch.object(ui.curses, "getmouse",
                              side_effect=lambda: next(followup)):
                ui.forward_pending_input(Input([curses.KEY_MOUSE] * 2), selected, state)
            self.assertEqual(sent[-1],
                             ("send-keys", "-t", "menu:0.0", "Enter"))
            self.assertEqual(len(sent), 2)

    def test_keyboard_or_wheel_can_disarm_clicked_item(self):
        s = screen(selected_index=2)
        state = {"armed_item": (10, "".join(c[0] for c in s[10]).strip())}
        # Reaching another selection via keyboard is a separate action.
        # A later click of an already-selected item must first arm, not submit.
        state.pop("armed_item")
        sent = []
        with patch.object(ui, "tmux", side_effect=lambda *args, **kwargs:
                          "\n".join("row"+str(i) for i in range(H))+"\n"
                          if args[0] == "capture-pane" else sent.append(args)), \
             patch.object(ui, "parse_line",
                          side_effect=lambda line,width:s[int(line[3:])]):
            ui.forward_verified_click(35, 10, s, state)
        self.assertEqual(sent, [])
        self.assertIn("armed_item", state)

    def test_drag_and_unpaired_release_do_nothing(self):
        s = screen()
        sent = []
        events = iter([
            (0,35,10,0,curses.BUTTON1_PRESSED),
            (0,35,11,0,curses.BUTTON1_RELEASED),
            (0,35,10,0,curses.BUTTON1_RELEASED),
        ])
        with patch.object(ui.curses,"getmouse",side_effect=lambda:next(events)), \
             patch.object(ui,"tmux",side_effect=lambda *a,**k:sent.append(a)):
            ui.forward_pending_input(Input([curses.KEY_MOUSE]*3),s,{})
        self.assertEqual(sent, [])

    def test_stale_screen_or_missing_capture_fails_closed(self):
        sent = []
        with patch.object(ui,"tmux",side_effect=lambda *args,**kw: "" if kw.get("capture") else sent.append(args)):
            ui.forward_verified_click(35,10,screen(),{})
        self.assertEqual(sent, [])

    def test_mousemask_cleanup_and_no_raw_sgr_relay(self):
        src=SOURCE.read_text()
        self.assertIn("curses.BUTTON4_PRESSED | curses.BUTTON5_PRESSED",src)
        self.assertIn("curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED",src)
        self.assertIn("curses.mousemask(0)",src)
        self.assertNotIn('send-keys", "-M"',src)

if __name__ == "__main__":
    unittest.main()
