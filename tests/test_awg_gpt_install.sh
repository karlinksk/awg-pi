#!/usr/bin/env bash
# Static installer regression: narrow GPT helper must ship on clean and upgrade.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh
bash -n src/awg-gpt
grep -Fq 'GPT_CLI="/usr/local/sbin/awg-gpt"' install.sh
grep -Fq 'install_project_helper src/awg-gpt "$GPT_CLI"' install.sh
grep -Fq 'bash -n "$GPT_CLI"' install.sh
grep -Fq '[[ "${EUID}" == 0 ]]' src/awg-gpt
grep -Fq '[[ "$#" == 1 ]]' src/awg-gpt
if grep -Eq 'NOPASSWD: *ALL|chmod +s|setcap .*awg-gpt' install.sh src/awg-gpt; then
  echo 'AWG_GPT_INSTALL_REGRESSION=FAIL_PRIVILEGE_EXPANSION' >&2
  exit 1
fi
grep -Fq 'notify-update)' src/awg-gpt
grep -Fq 'sha256sum -c -' src/awg-gpt
python3 -B -c 'import ast; ast.parse(open("src/awg-notify",encoding="utf-8").read())'
python3 -B - <<'PY'
import ast
p = ast.parse(open('src/awg-notify', encoding='utf-8').read())
fn = next(n for n in p.body if isinstance(n, ast.FunctionDef) and n.name == 'format_event')
ns = {'EVENT_LABELS': {}}
exec(compile(ast.Module(body=[fn], type_ignores=[]), '<format_event>', 'exec'), ns)
assert ns['format_event']('VPN_LOST', 'critical', 'test').startswith('🟥')
assert ns['format_event']('VPN_RESTORED', 'info', 'test').startswith('🟩')
PY
echo 'AWG_GPT_INSTALL_REGRESSION=PASS_STATIC'
