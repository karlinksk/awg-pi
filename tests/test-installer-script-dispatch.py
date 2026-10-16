#!/usr/bin/env python3
"""Offline regression: installer dispatcher must use the actual script language."""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = (ROOT / "install.sh").read_text(encoding="utf-8")
CALL = re.compile(
    r"^[ \t]*(install_project_(?:python_)?helper)[ \t]+"
    r"((?:src|scripts|extras)/[A-Za-z0-9._/-]+)[ \t]+",
    re.MULTILINE,
)

calls = CALL.findall(INSTALLER)
assert calls, "No installer file dispatches found"
seen = {}
for function, relative in calls:
    assert relative not in seen, f"Duplicate installer mapping: {relative}"
    seen[relative] = function
    file = ROOT / relative
    assert file.is_file(), f"Missing installer source: {relative}"
    source = file.read_text(encoding="utf-8")
    first = source.partition("\n")[0].lower()
    python = file.suffix == ".py" or first.startswith("#!") and "python" in first
    if python:
        assert function == "install_project_python_helper", (
            f"{relative} is Python, but installed through Bash validator"
        )
        ast.parse(source, filename=str(file))
    else:
        assert function == "install_project_helper", (
            f"{relative} is Bash, but installed through Python validator"
        )
        assert first.startswith("#!") and ("bash" in first or "/sh" in first), (
            f"Unrecognized installer source interpreter: {relative}"
        )
        result = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True)
        assert result.returncode == 0, f"Bash parse failed: {relative}: {result.stderr}"

assert seen.get("src/awg-health-probe") == "install_project_python_helper"
assert seen.get("src/awg-mihomo-smart") == "install_project_python_helper"
assert seen.get("src/awg-mihomo-service-check.py") == "install_project_python_helper"
print(f"INSTALLER_SCRIPT_DISPATCH=PASS ({len(calls)} source helpers)")
