#!/usr/bin/env python3
"""Regression for blank Matrix editbox transparency and safe footer clicks."""
import importlib.util
from pathlib import Path
import unittest
SRC=Path(__file__).resolve().parents[1]/"extras/awg-matrix-compositor.py"
spec=importlib.util.spec_from_file_location("editor",SRC)
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
W,H=116,34
def cell(ch=" ",fg=7,bg=4,bold=False):return ch,fg,bg,bold
def editor(focus="field"):
    rows=[[cell() for _ in range(W)] for _ in range(H)]
    for y in range(4,28):
        for x in (3,5,110,112):rows[y][x]=cell("│",6,4,True)
    if focus=="field":
        for x in range(6,110):rows[4][x]=cell(" ",7,0,True)
    for x,label in ((37,"<Проверить>"),(65,"< Отмена  >")):
        for i,ch in enumerate(label):rows[30][x+i]=cell(ch,7,4,True)
    if focus in ("verify","cancel"):
        start,end=(37,48) if focus=="verify" else (65,76)
        for x in range(start,end):
            ch=rows[30][x][0]
            rows[30][x]=cell(ch,3 if ch.isalpha() else 7,0,True)
    return rows
class EditboxMouse(unittest.TestCase):
    def test_empty_focused_line_not_shadow(self):
        s=editor();self.assertEqual(ui.editbox_content_span(s[4]),(6,110))
        self.assertEqual(ui.shadow_row_columns(s[4]),set())
        self.assertTrue(ui.editbox_focus(s))
        self.assertIn('role = "panel"',SRC.read_text())
    def test_every_editor_row_is_opaque(self):
        s=editor()
        for y in range(4,28):
            self.assertEqual(ui.editbox_content_span(s[y]),(6,110))
            self.assertEqual(ui.shadow_row_columns(s[y]),set())
    def test_actual_shadow_still_hidden(self):
        s=[cell() for _ in range(W)]
        for i in range(6,110):s[i]=cell(" ",7,0,True)
        self.assertEqual(len(ui.shadow_row_columns(s)),104)
        self.assertIsNone(ui.editbox_content_span(s))
    def test_selected_menu_row_not_editbox(self):
        s=[cell() for _ in range(W)]
        s[35]=cell("2",3,0,True);s[40]=cell("N",7,0,True)
        self.assertIsNone(ui.editbox_content_span(s))
    def test_click_buttons_when_editor_has_focus(self):
        s=editor()
        self.assertEqual(ui.menu_keys_for_click(s,40,30),("Tab","Enter"))
        self.assertEqual(ui.menu_keys_for_click(s,70,30),("Tab","Tab","Enter"))
    def test_button_focus_circles_through_editor(self):
        s=editor("verify")
        self.assertEqual(ui.menu_keys_for_click(s,40,30),("Enter",))
        self.assertEqual(ui.menu_keys_for_click(s,70,30),("Tab","Enter"))
        s=editor("cancel")
        self.assertEqual(ui.menu_keys_for_click(s,70,30),("Enter",))
        self.assertEqual(ui.menu_keys_for_click(s,40,30),("Tab","Tab","Enter"))
    def test_click_on_editor_text_does_not_confirm(self):
        s=editor()
        for x,y in ((8,4),(55,7),(90,12),(4,30),(112,30)):
            with self.subTest(x=x,y=y):
                self.assertEqual(ui.menu_keys_for_click(s,x,y),())
    def test_unknown_focus_fails_closed(self):
        self.assertEqual(ui.menu_keys_for_click(editor("none"),40,30),())
        s=editor()
        for x in range(37,48):
            c=s[30][x][0]
            if c.isalpha():s[30][x]=cell(c,3,0,True)
        self.assertEqual(ui.menu_keys_for_click(s,70,30),())
    def test_unknown_button_not_clickable(self):
        s=editor()
        for x in range(37,48):s[30][x]=cell()
        self.assertEqual(ui.menu_keys_for_click(s,40,30),())
if __name__=="__main__":unittest.main()
