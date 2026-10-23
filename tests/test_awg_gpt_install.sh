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
echo 'AWG_GPT_INSTALL_REGRESSION=PASS_STATIC'
