#!/usr/bin/env python3
"""Regression: menu first-click highlight and buttons, without editbox regressions."""
import importlib.util
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1]/"extras/awg-matrix-compositor.py"
spec = importlib.util.spec_from_file_location("matrix_highlight", SRC)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
W, H = 110, 30

def c(ch=" ", fg=7, bg=4, bold=False):
    return ch, fg, bg, bold

def menu(selected=0):
    s = [[c() for _ in range(W)] for _ in range(H)]
    for y in range(5, 9):
        for x in (3, 5, 104, 106):
            s[y][x] = c("│",6,4,True)
    for k, name in enumerate(("Первый", "Второй", "Третий")):
        y=6+k
        on=k==selected
        s[y][50]=c(str(k+1),3 if on else 6,0 if on else 4,on)
        for j,ch in enumerate(name):
            s[y][53+j]=c(ch,7,0 if on else 4,on)
    for start,label in ((40,"<  ОК  >"),(72,"<Отмена>")):
        for j,ch in enumerate(label):
            is_active=start==40
            s[25][start+j]=c(ch,3 if ch.isalpha() and is_active else 7,
                              0 if is_active else 4,True)
    return s

def editor():
    s=[[c() for _ in range(W)] for _ in range(H)]
    for y in range(4,26):
        for x in (3,5,104,106):
            s[y][x]=c("│",6,4,True)
    for x in range(6,104):
        s[4][x]=c(" ",7,0,True)
    for start,label in ((40,"<Проверить>"),(72,"<Отмена>")):
        for j,ch in enumerate(label):
            s[27][start+j]=c(ch,7,4,True)
    return s

class HighlightRegression(unittest.TestCase):
    def test_selected_menu_not_an_editor(self):
        for selected in (0,1,2):
            s=menu(selected)
            self.assertTrue(ui.menu_has_selected_item(s))
            self.assertFalse(ui.editbox_focus(s))
            self.assertEqual(ui.effective_editor_span(s[6+selected],True),None)
            row=s[6+selected]
            selected_chars=[x for x,v in enumerate(row)
                            if v and v[2]==0 and v[3] and v[1] in (3,7)
                            and v[0]!=" "]
            self.assertGreater(len(selected_chars),2)

    def test_click_first_selects_then_can_activate(self):
        s=menu(0)
        self.assertEqual(ui.menu_keys_for_click(s,55,7),("Down",))
        selected=menu(1)
        self.assertEqual(ui.menu_keys_for_click(selected,55,7),())
        self.assertEqual(ui.menu_keys_for_click(selected,55,7,activate_selected=True),("Enter",))

    def test_menu_buttons_not_blocked_by_false_editor_focus(self):
        for selected in range(3):
            s=menu(selected)
            self.assertEqual(ui.menu_keys_for_click(s,44,25),("Enter",))
            self.assertEqual(ui.menu_keys_for_click(s,74,25),("Tab","Enter"))

    def test_editbox_stays_opaque_and_buttons_remain_clickable(self):
        s=editor()
        self.assertFalse(ui.menu_has_selected_item(s))
        self.assertTrue(ui.editbox_focus(s))
        self.assertEqual(ui.effective_editor_span(s[4],False),(6,104))
        self.assertEqual(ui.shadow_row_columns(s[4]),set())
        self.assertEqual(ui.menu_keys_for_click(s,44,27),("Tab","Enter"))
        self.assertEqual(ui.menu_keys_for_click(s,74,27),("Tab","Tab","Enter"))

    def test_text_and_border_clicks_cannot_trigger_actions(self):
        s=editor()
        for x,y in ((4,4),(55,7),(109,25),(25,27)):
            self.assertEqual(ui.menu_keys_for_click(s,x,y),())

if __name__=="__main__":
    unittest.main()
