#!/usr/bin/env python3
"""No-network checks for opt-in credential-isolated manual browser session."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"scripts/awg-stage20-browser-trial.sh"
UNIT=ROOT/"units/awg-stage20-browser@.service"

class BrowserTrial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run=RUN.read_text()
        cls.unit=UNIT.read_text()

    def test_manual_root_only_and_clean_checkout(self):
        self.assertIn("LOCAL_SUDO_REQUIRED",self.run)
        self.assertIn("GIT_OPTIONAL_LOCKS=0",self.run)
        self.assertIn("status --porcelain --untracked-files=no",self.run)

    def test_exact_candidate_not_current_transport(self):
        self.assertIn("--target shadowsocks-27307",self.run)
        self.assertIn('p[0].get("server")!="169.150.210.233"',self.run)
        self.assertIn('p[0].get("port")!=8080',self.run)
        self.assertIn('cfg.get("allow-lan") is not False',self.run)
        for forbidden in ("awg-transport select","awg-mihomo-configure select",
                          "ip route add","ip rule add","systemctl enable",
                          "sudoers","iptables -A","nft add"):
            self.assertNotIn(forbidden,self.run)

    def test_isolated_endpoint_and_credentials(self):
        self.assertIn("BROWSER_PROXY_READY=127.0.0.1:",self.run)
        self.assertIn('LoadCredential=proxy:/run/awg-pbr/stage16-media/proxy-%i.yaml',self.unit)
        self.assertIn("DynamicUser=yes",self.unit)
        self.assertIn("NoNewPrivileges=yes",self.unit)
        self.assertIn("CapabilityBoundingSet=\\n",self.unit)
        self.assertIn("InaccessiblePaths=/var/lib/awg-pbr /etc/awg-pbr /run/awg-pbr",self.unit)
        self.assertIn("MemoryMax=160M",self.unit)
        self.assertIn("CPUQuota=65%",self.unit)
        self.assertNotIn("\\n[Install]",self.unit)

    def test_short_bounded_lifetime_and_cleanup(self):
        self.assertIn("RuntimeMaxSec=720",self.unit)
        self.assertIn("end=$((SECONDS+720))",self.run)
        self.assertIn("trap cleanup EXIT",self.run)
        self.assertIn('systemctl stop "awg-stage20-browser@$PORT.service"',self.run)
        self.assertIn('rm -rf -- "$CREDS" "$TARGET"',self.run)
        self.assertIn("TABLE100_UNCHANGED",self.run)

    def test_no_browser_secrets_or_cross_user_exposure(self):
        self.assertIn('cfg.get("bind-address")!="127.0.0.1"',self.run)
        self.assertIn('cfg.get("allow-lan") is not False',self.run)
        self.assertIn('umask 077',self.run)
        self.assertIn('StandardOutput=null',self.unit)
        self.assertIn('StandardError=null',self.unit)
        self.assertNotIn("cookie",self.run.lower())
        self.assertNotIn("password",self.run.lower())
        self.assertNotIn("/tmp/awg-stage",self.run)

if __name__=="__main__":
    unittest.main()
