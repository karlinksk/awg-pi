#!/usr/bin/env python3
"""Both VPN policy modes expose two independent engines, no redundant wizard."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MENU=(ROOT/"src/awg-menu").read_text()
start=MENU.index("vpn_menu(){")
end=MENU.index("\ndns_menu(){",start)
FN=MENU[start:end]

class CompactTransportMenu(unittest.TestCase):
    def test_mode_labels_and_actions(self):
        transit=FN.split('if [[ "$mode" == transit ]]',1)[1].split('continue',1)[0]
        selective=FN.split('choice="$(dialog --backtitle "$BACKTITLE" --title "VPN-маршрутизация [SELECTIVE]"',1)[1]
        for text in (transit,selective):
            self.assertNotIn('"Добавить / настроить транспорт"',text)
            self.assertNotIn('secondary_transport_setup',text)
            self.assertIn('awg_config_menu',text)
            self.assertIn('mihomo_menu',text)
            self.assertIn('active_transport_menu',text)
            self.assertIn('selection_policy_menu',text)
        for text,a,m,p,q in ((transit,3,4,5,6),(selective,4,5,6,7)):
            for option,handler in ((a,"awg_config_menu"),(m,"mihomo_menu"),
                                   (p,"active_transport_menu"),(q,"selection_policy_menu")):
                self.assertIn(str(option)+") "+handler+" ;;",text)
            self.assertIn('0 "Назад"',text)

    def test_no_orphaned_wizard_or_stale_instruction(self):
        self.assertNotIn("first_transport_setup(){",MENU)
        self.assertNotIn("secondary_transport_setup(){",MENU)
        self.assertNotIn("Сначала используйте «Добавить / настроить транспорт»",MENU)
        self.assertIn('Откройте «Конфигурация AmneziaWG» либо «Mihomo»',MENU)

    def test_dialog_dispatch_is_not_reliant_on_live_transport(self):
        # Exercise selection of both engine paths with all system actions stubbed.
        for mode,choices in (("transit",("3","4","5","6")),
                             ("selective",("4","5","6","7"))):
            for selection in choices:
                with self.subTest(mode=mode,selection=selection):
                    with tempfile.TemporaryDirectory(prefix="awg-vpn-nav-") as td:
                        log=Path(td)/"result"
                        shell=("set -Eeuo pipefail\n"
                               "BACKTITLE=test\n"
                               "cat(){ if [[ \"$1\" == /etc/awg-pbr/mode ]]; then echo \"$TEST_MODE\"; else command cat \"$@\"; fi; }\n"
                               "dialog(){ if [[ -e \"$TEST_SEEN\" ]]; then return 1; fi; touch \"$TEST_SEEN\"; echo \"$TEST_CHOICE\" >&2; }\n"
                               "awg_config_menu(){ echo awg >> \"$TEST_LOG\"; }\n"
                               "mihomo_menu(){ echo mihomo >> \"$TEST_LOG\"; }\n"
                               "active_transport_menu(){ echo active >> \"$TEST_LOG\"; }\n"
                               "selection_policy_menu(){ echo policy >> \"$TEST_LOG\"; }\n"
                               +FN+"\nvpn_menu\n")
                        env=dict(os.environ,TEST_MODE=mode,TEST_CHOICE=selection,
                                 TEST_SEEN=str(Path(td)/"seen"),TEST_LOG=str(log))
                        result=subprocess.run(["bash","-c",shell],env=env,
                                              capture_output=True,text=True,timeout=4)
                        self.assertEqual(result.returncode,0,result.stderr)
                        expected=dict(zip(choices,("awg","mihomo","active","policy")))[selection]
                        self.assertEqual(log.read_text().strip(),expected)

if __name__=="__main__":
    unittest.main()
