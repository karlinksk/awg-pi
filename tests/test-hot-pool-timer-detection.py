#!/usr/bin/env python3
"""Regression for Hot Pool presence detection during first-time installation.

No root, network, unit changes, or actual installer side effects: execute only
the exact installer decision block using mocked systemctl and installer calls.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "install.sh").read_text(encoding="utf-8")
start = SOURCE.index('# Hot Pool is packaged passively and is SHADOW_ONLY.')
end = SOURCE.index('unset _hot_pool_timer_state', start) + len('unset _hot_pool_timer_state')
decision = SOURCE[start:end]

prefix = r"""set -Eeuo pipefail
systemctl() {
  case "${1-}" in
    is-enabled)
      [[ -n "${MOCK_ENABLED_TEXT:-}" ]] && printf '%s\n' "$MOCK_ENABLED_TEXT"
      return "${MOCK_ENABLED_RC:-1}"
      ;;
    is-active)
      case "${3-}" in
        awg-mihomo-hot-pool.service) [[ "${MOCK_SERVICE_ACTIVE:-0}" == 1 ]] ;;
        awg-mihomo-hot-pool.timer) [[ "${MOCK_TIMER_ACTIVE:-0}" == 1 ]] ;;
        *) return 2 ;;
      esac
      ;;
    *) return 2 ;;
  esac
}
install_project_python_helper(){ echo PYTHON >> "$MOCK_LOG"; }
install_project_helper(){ echo BASH >> "$MOCK_LOG"; }
install_project_unit(){ echo UNIT >> "$MOCK_LOG"; }
install(){ echo PRIVATE_DIRECTORY >> "$MOCK_LOG"; }
ok(){ printf 'INFO=%s\n' "$*"; }
warn(){ printf 'WARN=%s\n' "$*"; }
"""
assert '|| echo not-found' not in decision, "Double sentinel reintroduced"
assert '|| true' in decision, "Nonzero is-enabled exit is not handled"

def check(state, rc, *, service=False, timer=False, expected_install):
    with tempfile.TemporaryDirectory(prefix="awg-pi-hot-pool-probe-") as td:
        log = Path(td) / "operations"
        env = dict(os.environ, MOCK_LOG=str(log),
                   MOCK_ENABLED_TEXT=state, MOCK_ENABLED_RC=str(rc),
                   MOCK_SERVICE_ACTIVE=str(int(service)),
                   MOCK_TIMER_ACTIVE=str(int(timer)))
        p = subprocess.run(["bash", "-c", prefix + "\n" + decision],
                           text=True, capture_output=True, env=env, timeout=5)
        assert p.returncode == 0, (state, p.returncode, p.stderr)
        operations = log.read_text().splitlines() if log.exists() else []
        if expected_install:
            assert operations == ["PYTHON"]*3 + ["BASH"] + ["UNIT"]*2 + ["PRIVATE_DIRECTORY"], (state, operations)
            assert "SHADOW_ONLY установлен пассивно" in p.stdout
        else:
            assert operations == [], (state, operations)
            assert "сохраняем установленную версию" in p.stdout
        assert "not-found\nnot-found" not in p.stdout

# systemctl is-enabled on absent timer may exit nonzero with or without text.
check("not-found", 1, expected_install=True)
check("", 1, expected_install=True)
check("disabled", 1, expected_install=True)
check("enabled", 0, expected_install=False)
check("masked", 1, expected_install=False)
check("static", 0, expected_install=False)
check("not-found", 1, service=True, expected_install=False)
check("not-found", 1, timer=True, expected_install=False)
standalone = (ROOT / "extras/mihomo-hot-pool-shadow/install-shadow.sh").read_text(encoding="utf-8")
assert "awg-mihomo-hot-pool.service:not-found" in standalone
assert "awg-mihomo-hot-pool.timer:not-found" in standalone
assert 'is-active --quiet "$unit"' in standalone
assert "install -m 0644" in standalone
assert '/bin/systemctl enable --now' not in standalone
print("HOT_POOL_TIMER_PROBE=PASS (8 isolated cases)")
