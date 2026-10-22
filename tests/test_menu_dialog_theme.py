#!/usr/bin/env python3
"""Terminal-safe visual-theme contracts. No sudo, routes or live VPN changes."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()
MARKER="cat > \"$AWG_DIALOG_STYLE\" <<'AWG_DIALOG_PALETTE'\n"
a=MENU.index(MARKER)+len(MARKER)
b=MENU.index("\nAWG_DIALOG_PALETTE",a)
PALETTE=MENU[a:b]+"\n"

class MenuVisualTheme(unittest.TestCase):
    def test_all_dialogs_share_process_scoped_theme(self):
        self.assertIn('awg_dialog_theme_init(){',MENU)
        self.assertIn('trap cleanup EXIT\nawg_dialog_theme_init',MENU)
        self.assertIn('export DIALOGRC="$AWG_DIALOG_STYLE"',MENU)
        self.assertIn('[[ -z "$AWG_DIALOG_STYLE" ]] || rm -f',MENU)
        self.assertIn('command dialog ',MENU)
        self.assertNotIn('~/'+'.dialogrc',MENU.split('awg_dialog_theme_init(){',1)[1].split("}",1)[0])
        self.assertNotIn('/etc/dialogrc',MENU.split('awg_dialog_theme_init(){',1)[1].split("}",1)[0])

    def test_primary_language_buttons_are_russian(self):
        for option, label in (
            ('--ok-label', 'ОК'),
            ('--cancel-label', 'Отмена'),
            ('--yes-label', 'Да'),
            ('--no-label', 'Нет'),
            ('--exit-label', 'Закрыть'),
        ):
            self.assertIn(option + ' "' + label + '"', MENU)

    def test_palette_is_dark_and_high_contrast_in_every_dialog(self):
        for field in (
            "use_colors = ON", "use_shadow = ON",
            "screen_color = (BLACK,CYAN,OFF)",
            "dialog_color = (WHITE,BLUE,OFF)",
            "item_color = dialog_color",
            "item_selected_color = (WHITE,BLACK,ON)",
            "title_color = (YELLOW,BLUE,ON)",
            "border_color = (CYAN,BLUE,ON)",
            "menubox_color = dialog_color",
            "itemhelp_color = (WHITE,BLUE,OFF)",
            "button_active_color = (WHITE,BLACK,ON)",
            "button_inactive_color = (WHITE,BLUE,ON)",
            "button_label_active_color = (YELLOW,BLACK,ON)",
            "inputbox_color = dialog_color",
            "searchbox_color = dialog_color",
            "form_text_color = dialog_color",
        ):
            self.assertIn(field, PALETTE)
        # No light cyan panel or selection that obscures Termius green words.
        # The light cyan is confined to the outside screen, never the window.
        self.assertEqual(PALETTE.count("(BLACK,CYAN,OFF)"), 1)
        self.assertNotIn("(WHITE,CYAN,ON)", PALETTE)
        self.assertEqual(MENU.count("export DIALOGRC="),1)

    def test_native_scrollbar_hidden_without_disabling_scroll(self):
        # ncurses dialog native scrollbar draws broken glyphs at right edge
        # in real SSH clients with wide UTF-8/cyan widgets. The status
        # position indicator and keyboard navigation remain native.
        self.assertIn("use_scrollbar = OFF",PALETTE)
        self.assertNotIn("use_scrollbar = ON",PALETTE)
        self.assertIn("position_indicator_color = title_color",PALETTE)
        self.assertNotIn("--scrollbar",MENU)
        self.assertIn("--item-help --menu",MENU)

    def test_dialog_help_for_every_menu(self):
        self.assertEqual(MENU.count("--item-help --menu"), len([line for line in MENU.splitlines() if "dialog " in line and "--menu" in line]))
        self.assertIn("if ((rows < 22 || cols < 70))",MENU)

    @unittest.skipUnless(shutil.which("dialog") and shutil.which("script"),
                         "native dialog / pty utility unavailable")
    def test_palette_is_accepted_by_real_ncurses_widget(self):
        with tempfile.TemporaryDirectory(prefix="awg-ui-theme-test-") as td:
            rc=Path(td)/"palette.rc"
            rc.write_text(PALETTE)
            env=dict(os.environ,TERM="xterm-256color",DIALOGRC=str(rc))
            proc=subprocess.run(
                ["script","-q","-e","-c",
                 "dialog --title 'AWG Pi Gateway' --infobox 'Style check' 7 43",
                 "/dev/null"],
                env=env,capture_output=True,timeout=8,
            )
            self.assertEqual(proc.returncode,0,proc.stderr.decode(errors="replace")[-200:])
            self.assertIn(b"Style check",proc.stdout)

    def test_no_mutation_outside_menu(self):
        install=(ROOT/"install.sh").read_text()
        self.assertIn("install_project_helper src/awg-menu /usr/local/sbin/awg-menu",install)
        self.assertNotIn("DIALOGRC=",install)
        self.assertNotIn("localectl set-locale",MENU)

if __name__=="__main__":
    unittest.main()
