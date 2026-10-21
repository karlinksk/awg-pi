# v1.3.0 — user-facing dialog audit (pre-release candidate)

## Coverage
- Reviewed centralized `src/awg-menu` entry points for operation results, status translations, node selection, subscription update, routing and transport management.
- Before this patch the common result dialog displayed `ОШИБКА (код N)` and raw machine codes as its first meaningful explanation.
- The common `show_operation_result` path now places an actionable, Russian-language explanation **before** retained technical diagnostics for any nonzero return code.
- Specific handled reasons: active AWG or Mihomo management not ready; transport changed during Xray rollback; selected node failed isolated HTTPS; provider changed mid-probe; incomplete rollback; generic Xray/native/unified errors. Unknown error codes also have a safe generic explanation.
- User-triggered node selection checks active Mihomo before any manual transaction, and tells the operator how to switch transports rather than exposing only a raw error.
- Ordinary technical status strings such as `FAIL-OPEN`, `FAIL-CLOSED`, engine names and exact diagnostic codes remain in details for engineering. All successful operations still preserve their underlying output. This is not a claim that every auxiliary third-party terminal/TUI dialog uses the centralized handler.

## Tests and deployment
- Added rootless behavioral tests for five common/missing/unknown error families, validating visible Russian text and unchanged diagnostic code.
- Installer-first delivery: `install.sh` already installs `src/awg-menu` and `src/awg-xray-manual-switch.py` for fresh install and upgrade. Since both patched files live in `src/`, this **candidate** includes them when `AWG_PI_REF` targets this exact commit. No manual post-install scripts needed.
- On test Pi under Debian 13 ARM64: 790 Python regression tests PASS on candidate HEAD; additional installer/upgrade tests run separately. Full clean-install hardware and LAN release gates remain pending.
- Do not tag or release v1.3.0 until the draft stack has been consolidated and clean-install + LAN + recovery gates are independently verified.

## Safety
- No modification to MikroTik or SSTP; AWG remains active until explicitly changed.
- Do not expose subscription secrets in user-visible dialogs. Error code mapping must remain conservative: it must not claim the VPN switched if no TUN/LAN check has passed.
