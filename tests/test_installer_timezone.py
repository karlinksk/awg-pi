"""Isolated installer timezone regression tests (never changes the host timezone)."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "install.sh").read_text()
MENU = (ROOT / "src/awg-menu").read_text()
BEGIN = "# BEGIN_FIRST_INSTALL_TIMEZONE\n"
END = "\n# END_FIRST_INSTALL_TIMEZONE"
assert INSTALL.count(BEGIN) == 1 and INSTALL.count(END) == 1
SECTION = INSTALL.split(BEGIN, 1)[1].split(END, 1)[0]
MOCK = r"""
set -Eeuo pipefail
UPGRADE_EXISTING="$MOCK_UPGRADE"
STAGE="test"
ok(){ printf 'OK=%s\n' "$*"; }
die(){ printf 'ERROR=%s\n' "$*" >&2; exit 2; }
timedatectl(){
  case "$1" in
    show)
      [[ "$MOCK_FAIL_SHOW" == 0 ]] || return 1
      cat "$MOCK_STATE"
      ;;
    set-timezone)
      printf 'SET=%s\n' "$2" >> "$MOCK_WRITES"
      [[ "$MOCK_FAIL_SET" == 0 ]] || return 1
      printf '%s\n' "$2" > "$MOCK_STATE"
      ;;
    *) return 2 ;;
  esac
}
"""

class InstallerTimezoneTests(unittest.TestCase):
    def run_fragment(self, initial="Etc/UTC", *, upgrade=False, timezone=None, fail_set=False):
        with tempfile.TemporaryDirectory(prefix="awg-timezone-test-") as td:
            state = Path(td) / "timezone"
            writes = Path(td) / "set-calls"
            state.write_text(initial + "\n")
            env = dict(os.environ)
            env.update(MOCK_UPGRADE=str(int(upgrade)), MOCK_STATE=str(state),
                       MOCK_WRITES=str(writes), MOCK_FAIL_SET=str(int(fail_set)),
                       MOCK_FAIL_SHOW="0")
            env.pop("AWG_PI_TIMEZONE", None)
            if timezone is not None:
                env["AWG_PI_TIMEZONE"] = timezone
            p = subprocess.run(["bash", "-c", MOCK + "\n" + SECTION],
                               capture_output=True, text=True, env=env, timeout=6)
            calls = writes.read_text().splitlines() if writes.exists() else []
            return p.returncode, state.read_text().strip(), calls, p.stdout, p.stderr

    def test_fresh_install_defaults_to_novosibirsk(self):
        rc, state, calls, out, err = self.run_fragment()
        self.assertEqual(rc, 0, err)
        self.assertEqual(state, "Asia/Novosibirsk")
        self.assertEqual(calls, ["SET=Asia/Novosibirsk"])
        self.assertIn("Часовой пояс новой системы: Asia/Novosibirsk", out)

    def test_already_in_target_zone_is_idempotent(self):
        rc, state, calls, _, err = self.run_fragment(initial="Asia/Novosibirsk")
        self.assertEqual(rc, 0, err)
        self.assertEqual(state, "Asia/Novosibirsk")
        self.assertEqual(calls, [])

    def test_explicit_override(self):
        rc, state, calls, _, err = self.run_fragment(timezone="Etc/UTC")
        self.assertEqual(rc, 0, err)
        self.assertEqual(state, "Etc/UTC")
        self.assertEqual(calls, [])

    def test_upgrade_preserves_existing_zone_even_with_override(self):
        rc, state, calls, out, err = self.run_fragment(
            initial="Asia/Bangkok", upgrade=True, timezone="Asia/Novosibirsk")
        self.assertEqual(rc, 0, err)
        self.assertEqual(state, "Asia/Bangkok")
        self.assertEqual(calls, [])
        self.assertIn("Часовой пояс существующей системы сохранён", out)

    def test_rejects_traversal(self):
        rc, state, calls, _, err = self.run_fragment(timezone="Asia/../UTC")
        self.assertNotEqual(rc, 0)
        self.assertEqual(state, "Etc/UTC")
        self.assertEqual(calls, [])
        self.assertIn("Недопустимый формат", err)

    def test_rejects_nonexistent_zone(self):
        rc, state, calls, _, err = self.run_fragment(timezone="Mars/Olympus")
        self.assertNotEqual(rc, 0)
        self.assertEqual(state, "Etc/UTC")
        self.assertEqual(calls, [])
        self.assertIn("Часовой пояс отсутствует", err)

    def test_failed_set_timezone_aborts(self):
        rc, state, calls, _, err = self.run_fragment(fail_set=True)
        self.assertNotEqual(rc, 0)
        self.assertEqual(state, "Etc/UTC")
        self.assertEqual(calls, ["SET=Asia/Novosibirsk"])
        self.assertIn("Не удалось установить", err)

    def test_run_order_and_existing_menu(self):
        self.assertIn("ffmpeg xz-utils tzdata", INSTALL)
        self.assertLess(INSTALL.index("ffmpeg xz-utils tzdata"), INSTALL.index(BEGIN))
        self.assertLess(INSTALL.index(END), INSTALL.index("# 3. Go"))
        self.assertIn('timedatectl set-timezone "$zone"', MENU)

if __name__ == "__main__":
    unittest.main()
