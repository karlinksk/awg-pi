#!/usr/bin/env python3
"""Unprivileged contract tests for safe staged Mihomo provider refresh."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = ROOT.parent / "src" / "awg-mihomo-configure"


def function_text():
    content = SOURCE.read_text()
    start = content.index("provider_auto_refresh(){")
    end = content.index("\n}\n\nprovider_import(){", start) + 2
    return content[start:end]


class PeriodicReviewTests(unittest.TestCase):
    def run_case(self, *, policy="auto", current="existing-node", candidate=True,
                 periodic="1", stage="STAGED", scan="OK", best="replacement-node"):
        with tempfile.TemporaryDirectory(prefix="awg-provider-unit-") as folder:
            working = pathlib.Path(folder)
            node = working / "node"
            policyfile = working / "policy"
            commits = working / "commits"
            node.write_text(current + "\n")
            policyfile.write_text(policy + "\n")
            pool = working / "pool-cli"
            pool.write_text("""#!/bin/bash
if [[ "${1-}" == "list" ]]; then
 if [[ "$MOCK_CANDIDATE" == "yes" ]]; then
  printf '[{"name":"existing-node"}]\\n'
 else
  printf '[{"name":"replacement-node"}]\\n'
 fi
else
 printf '%s\\n' "$MOCK_BEST"
fi
""")
            pool.chmod(0o700)
            header = r'''set -Eeuo pipefail
MIHOMO_PERIODIC_REFRESH="$MOCK_PERIODIC"
MIHOMO_NODE_NAME_FILE="$MOCK_NODE_FILE"
MIHOMO_NODE_POLICY_MODE_FILE="$MOCK_POLICY_FILE"
MIHOMO_POOL_CLI="$MOCK_POOL"
stage_provider_update() {
 case "$MOCK_STAGE" in
   STAGED) echo 'MIHOMO_PROVIDER=STAGED' ;;
   UNCHANGED) echo 'MIHOMO_PROVIDER=UNCHANGED'; return 10 ;;
   FAILED) echo 'STAGE_FAILURE'; return 3 ;;
 esac
}
scan_candidate_pool() {
 if [[ "$MOCK_SCAN" == "OK" ]]; then
   echo POOL_SCANNED
   return 0
 fi
 return 3
}
candidate_commit_auto() {
 printf '%s\n' "$1" >>"$MOCK_COMMITS"
 echo 'MOCK_COMMIT_CALLED'
}
'''
            script = header + "\n" + function_text() + "\nprovider_auto_refresh\n"
            env = {**os.environ, "MOCK_PERIODIC": periodic,
                   "MOCK_NODE_FILE": str(node),
                   "MOCK_POLICY_FILE": str(policyfile),
                   "MOCK_POOL": str(pool),
                   "MOCK_COMMITS": str(commits),
                   "MOCK_CANDIDATE": "yes" if candidate else "no",
                   "MOCK_STAGE": stage, "MOCK_SCAN": scan,
                   "MOCK_BEST": best}
            proc = subprocess.run(["bash", "-c", script], text=True,
                                  capture_output=True, env=env, timeout=6)
            return proc, commits.read_text().splitlines() if commits.exists() else []

    def test_periodic_keeps_current_existing(self):
        result, commits = self.run_case(candidate=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MIHOMO_PROVIDER_AUTO_REFRESH=STAGED_PERIODIC_REVIEW", result.stdout)
        self.assertIn("LIVE_PROVIDER=UNCHANGED", result.stdout)
        self.assertEqual(commits, [])

    def test_periodic_keeps_old_if_subscription_rotates(self):
        result, commits = self.run_case(candidate=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STAGED_PERIODIC_REVIEW", result.stdout)
        self.assertEqual(commits, [])
        self.assertNotIn("MOCK_COMMIT_CALLED", result.stdout)

    def test_periodic_never_commits_even_with_no_current_name(self):
        result, commits = self.run_case(current="", candidate=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STAGED_PERIODIC_REVIEW", result.stdout)
        self.assertEqual(commits, [])

    def test_nonperiodic_auto_best_requires_review(self):
        result, commits = self.run_case(periodic="0", candidate=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MIHOMO_PROVIDER_AUTO_TARGET=replacement-node", result.stdout)
        self.assertIn("MIHOMO_PROVIDER_AUTO_REASON=auto-best", result.stdout)
        self.assertIn("STAGED_NODE_REVIEW", result.stdout)
        self.assertIn("LIVE_PROVIDER=UNCHANGED", result.stdout)
        self.assertEqual(commits, [])

    def test_nonperiodic_matching_name_retains_explicit_keep_current(self):
        result, commits = self.run_case(periodic="0", candidate=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MIHOMO_PROVIDER_AUTO_REASON=keep-current", result.stdout)
        self.assertIn("MIHOMO_PROVIDER_AUTO_REFRESH=APPLIED", result.stdout)
        self.assertEqual(commits, ["existing-node"])

    def test_fixed_policy_always_stages(self):
        result, commits = self.run_case(policy="fixed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STAGED_FIXED_REVIEW", result.stdout)
        self.assertEqual(commits, [])

    def test_manual_no_current_stages(self):
        result, commits = self.run_case(policy="manual", periodic="0", candidate=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STAGED_CURRENT_UNAVAILABLE", result.stdout)
        self.assertEqual(commits, [])

    def test_unchanged_stops_before_scan_or_commit(self):
        result, commits = self.run_case(stage="UNCHANGED")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AUTO_REFRESH=UNCHANGED", result.stdout)
        self.assertNotIn("POOL_SCANNED", result.stdout)
        self.assertEqual(commits, [])

    def test_no_healthy_node_keeps_live(self):
        result, commits = self.run_case(scan="NO_HEALTHY")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STAGED_NO_HEALTHY_NODE", result.stdout)
        self.assertIn("LIVE_PROVIDER=UNCHANGED", result.stdout)
        self.assertEqual(commits, [])

    def test_fetch_failure_keeps_live(self):
        result, commits = self.run_case(stage="FAILED")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AUTO_REFRESH=FETCH_FAILED", result.stderr)
        self.assertEqual(commits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)