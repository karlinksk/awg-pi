#!/usr/bin/env python3
"""Prevent upstream AWG latest-tag drift in repeatable v1.3 clean installs."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
S=(ROOT/"install.sh").read_text()
CI=(ROOT/".github/workflows/ci.yml").read_text()
GO_TAG="v3.1.20260828"
TOOLS_TAG="v3.1.20260812"
GO_SHA="b5928efb6ca19f0153958460c3d141f04abc5c2e"
TOOLS_SHA="ee0f0a9aa34ff0a0da4b343b9512781cfe02843"

class SourcePins(unittest.TestCase):
    def test_explicit_tags_not_dynamic_latest(self):
        self.assertIn('GO_TAG="'+GO_TAG+'"',S)
        self.assertIn('TOOLS_TAG="'+TOOLS_TAG+'"',S)
        self.assertNotIn('GO_TAG="$(latest_tag',S)
        self.assertNotIn('TOOLS_TAG="$(latest_tag',S)

    def test_git_tags_match_ci_commit_pins(self):
        self.assertIn('GO_REVISION="'+GO_SHA+'"',S)
        self.assertIn('TOOLS_REVISION="'+TOOLS_SHA+'"',S)
        self.assertIn("ref: "+GO_SHA,CI)
        self.assertIn("ref: "+TOOLS_SHA,CI)

    def test_check_before_fetch_and_after_checkout(self):
        self.assertLess(S.index('verify_release_tag "$GO_REPO"'),S.index('sync_repo "$GO_REPO"'))
        self.assertLess(S.index('verify_release_tag "$TOOLS_REPO"'),S.index('sync_repo "$TOOLS_REPO"'))
        for which in ("go","tools"):
            path='$SRC_ROOT/amneziawg-'+which
            expected='$'+("GO_REVISION" if which=="go" else "TOOLS_REVISION")
            self.assertIn('"$(git -C "'+path+'" rev-parse HEAD)" == "'+expected+'"',S)

    def test_pin_verification_exact_ref_only(self):
        function=S.split('verify_release_tag(){',1)[1].split('\n}\n',1)[0]
        self.assertIn('refs/tags/$tag',function)
        self.assertIn('$2==wanted',function)
        self.assertIn('"$actual" == "$expected"',function)
        self.assertIn('die ',function)

    def test_version_validation_is_before_build(self):
        self.assertLess(S.index('[[ "$(git -C "$SRC_ROOT/amneziawg-go" rev-parse HEAD)"'),
                        S.index('make -C "$SRC_ROOT/amneziawg-go" clean'))
        self.assertLess(S.index('[[ "$(git -C "$SRC_ROOT/amneziawg-tools" rev-parse HEAD)"'),
                        S.index('make -C "$SRC_ROOT/amneziawg-tools/src" clean'))

    def test_syntax(self):
        self.assertEqual(subprocess.run(["bash","-n",str(ROOT/"install.sh")],
                                        capture_output=True).returncode,0)

if __name__=="__main__":unittest.main()
