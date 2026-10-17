#!/usr/bin/env python3
"""Reboot-safe Stage18 runtime bootstrap, automatically provisioned with Mihomo."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
UNIT=ROOT/"units/awg-mihomo-stage18-ram-runtime.service"
TIMER=ROOT/"units/awg-mihomo-stage18-ram-runtime.timer"
BOOT=ROOT/"scripts/awg-mihomo-stage18-ram-runtime.sh"
INSTALL=ROOT/"install.sh"

class RuntimeBootSafety(unittest.TestCase):
    def test_unit_is_conditioned_on_provider_not_balanced_gate(self):
        text=UNIT.read_text()
        self.assertIn("ConditionPathExists=/var/lib/awg-pbr/mihomo/providers/subscription.yaml",text)
        self.assertNotIn("ExecCondition=/usr/bin/grep",text)
        self.assertNotIn("awg-transport",text)

    def test_unit_must_be_ram_only(self):
        text=UNIT.read_text()
        for flag in ("Type=oneshot","NoNewPrivileges=true","ProtectSystem=strict",
                     "ReadWritePaths=/dev/shm","UMask=0077",
                     "TimeoutStartSec=180","MemoryMax=256M"):
            self.assertIn(flag,text)
        self.assertNotIn("awg-transport select",text)
        self.assertNotIn("nft ",text)

    def test_unit_executes_only_pinned_bootstrap(self):
        self.assertIn("ExecStart=/usr/local/sbin/awg-mihomo-stage18-ram-runtime",UNIT.read_text())

    def test_timer_not_persistent_or_high_frequency(self):
        text=TIMER.read_text()
        self.assertIn("OnBootSec=2min",text)
        self.assertIn("OnUnitActiveSec=1h",text)
        self.assertIn("Persistent=false",text)

    def test_install_is_complete_and_guarded(self):
        s=INSTALL.read_text()
        self.assertIn("ffmpeg xz-utils",s)
        self.assertIn('for media_bin in /usr/bin/ffmpeg /usr/bin/ffprobe /usr/bin/xz',s)
        self.assertIn("install_project_helper scripts/awg-mihomo-stage18-ram-runtime.sh",s)
        self.assertIn("install_project_unit units/awg-mihomo-stage18-ram-runtime.service",s)
        self.assertIn("install_project_unit units/awg-mihomo-stage18-ram-runtime.timer",s)
        self.assertIn("if (( UPGRADE_EXISTING == 0 )); then",s)
        self.assertIn("for unit in awg-mihomo-pool-refresh.timer awg-mihomo-stage18-ram-runtime.timer awg-mihomo-hot-pool.timer",s)
        self.assertIn('systemctl enable --now "$unit"',s)
        self.assertNotIn("Stage18 video decode unavailable: FFmpeg missing",s)

    def test_script_enforces_exact_production_pins(self):
        s=BOOT.read_text()
        self.assertIn("STAGE18_NEEDS_ROOT",s)
        self.assertIn("NODE_SHA=fd959ead1bf6d636",s)
        self.assertIn("YT_SHA=1fa6733c37ea6fb5",s)
        self.assertIn("TAR_SHA=eab80cb88f8fda1",s)
        self.assertIn('R=/dev/shm/awg-stage18-service-runtime',s)
        self.assertIn("sha256sum -c --status",s)

    def test_download_is_once_per_missing_pin(self):
        s=BOOT.read_text()
        self.assertIn('if ! verify node "$NODE_SHA"; then',s)
        self.assertIn('if ! verify yt-dlp "$YT_SHA"; then',s)
        self.assertIn("PRODUCTION_UNCHANGED=YES",s)

    def test_no_unrelated_network_changes_in_script(self):
        s=BOOT.read_text()
        for item in ("systemctl restart","awg-transport","nft add","ip route replace",
                     "/var/cache","/var/log/"):
            self.assertNotIn(item,s)

if __name__=="__main__":
    unittest.main()
