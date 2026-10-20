"""Non-invasive validation of *all* packaged systemd units in a sandbox root.

The real host's systemd units, unit links, services and routes are untouched.
Packaged executables are represented by harmless executable stubs inside the
temporary filesystem solely to let systemd-analyze verify unit syntax/ordering.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install.sh").read_text()
UNIT_SOURCES = sorted(
    p for folder in (ROOT / "units", ROOT / "extras/mihomo-hot-pool-shadow")
    for p in folder.iterdir()
    if p.is_file() and p.suffix in (".service", ".timer", ".path")
)
STEM_EXTENSIONS = {".service", ".timer", ".path"}
EXEC_RE = re.compile(r"^Exec(?:Start|StartPre|StartPost|Stop|StopPost)=\s*[-+!@:]*(/\S+)", re.M)
DEPS_RE = re.compile(r"^(After|Before|Wants|Requires|BindsTo|PartOf|Conflicts)=(.*)$", re.M)

class PackagedSystemdUnitTests(unittest.TestCase):
    def test_all_units_are_installer_assets(self):
        self.assertGreaterEqual(len(UNIT_SOURCES), 13)
        self.assertEqual(len({p.name for p in UNIT_SOURCES}), len(UNIT_SOURCES))
        for p in UNIT_SOURCES:
            with self.subTest(p=p.name):
                self.assertIn(str(p.relative_to(ROOT)), INSTALLER,
                              "Unit shipped in Git but not staged by install.sh")

    def test_custom_exec_paths_are_installed(self):
        for source in UNIT_SOURCES:
            for match in EXEC_RE.finditer(source.read_text()):
                exe = match.group(1)
                with self.subTest(unit=source.name, exe=exe):
                    if exe.startswith("/usr/local/"):
                        self.assertIn(exe, INSTALLER,
                                      "Missing installed executable referenced by unit")
                    self.assertNotIn("../", exe)
                    self.assertNotIn("//", exe)

    def test_custom_awg_dependencies_are_packaged(self):
        available = {p.name for p in UNIT_SOURCES}
        # These base units are created by install.sh rather than shipped as files.
        available.update({"awg-pbr-setup.service", "awg-pbr-health.service",
                          "awg-opencck-update.service", "awg-opencck-update.timer"})
        for source in UNIT_SOURCES:
            for _, dependencies in DEPS_RE.findall(source.read_text()):
                for dep in dependencies.split():
                    if dep.startswith("awg-"):
                        with self.subTest(unit=source.name, reference=dep):
                            self.assertIn(dep, available)
            if source.suffix in {".timer", ".path"}:
                partner = source.with_suffix(".service").name
                # Timers and paths with no Unit= use the corresponding service.
                if not re.search(r"^Unit=", source.read_text(), re.M):
                    with self.subTest(unit=source.name):
                        self.assertIn(partner, available)

    def test_remote_agent_nonroot_paired_and_boot_resilient(self):
        source = (ROOT / "units/awg-dc-remote@.service").read_text()
        self.assertIn("User=%i", source)
        self.assertIn("WantedBy=multi-user.target", source)
        self.assertIn("Restart=always", source)
        self.assertIn("ConditionPathExists=/home/%i/.desktop-commander-device/device.json", source)
        self.assertNotIn("User=root", source)
        self.assertNotIn("ExecStartPre=sudo", source)
        self.assertNotIn("After=ssh.service", source)
        self.assertNotIn("After=awg-mihomo.service", source)

    def test_hot_pool_stays_provider_guarded_and_shadow_only(self):
        source = (ROOT / "extras/mihomo-hot-pool-shadow/awg-mihomo-hot-pool.service").read_text()
        self.assertIn("ConditionPathExists=/var/lib/awg-pbr/mihomo/providers/subscription.yaml", source)
        self.assertIn("ConditionPathExists=/run/awg-pbr/mihomo-pool/live.json", source)
        self.assertIn("ExecStart=/usr/local/sbin/awg-mihomo-hot-continuity-run", source)
        self.assertNotIn("awg-transport select", source)
        self.assertNotIn("awg-mihomo-node-policy", source)

    def test_inline_generated_units_are_verified_too(self):
        # Four services/timers are written as heredocs in install.sh rather
        # than shipped in units/. Validate the *actual rendered text* in CI.
        inline = {
            "awg-pbr-setup.service": "cat >\"$SETUP_SERVICE\" <<'EOF'\n",
            "awg-pbr-health.service": "cat >\"$HEALTH_SERVICE\" <<'EOF'\n",
            "awg-opencck-update.service":
                "cat >/etc/systemd/system/awg-opencck-update.service <<'EOF'\n",
            "awg-opencck-update.timer":
                "cat >/etc/systemd/system/awg-opencck-update.timer <<'EOF'\n",
        }
        rendered = {}
        for name, marker in inline.items():
            self.assertEqual(INSTALLER.count(marker), 1)
            rendered[name] = INSTALLER.split(marker, 1)[1].split("\nEOF", 1)[0] + "\n"
            self.assertIn("[Unit]", rendered[name])
        with tempfile.TemporaryDirectory(prefix="awg-v13-generated-unit-audit-") as d:
            sandbox = Path(d)
            target = sandbox / "etc/systemd/system"
            target.mkdir(parents=True)
            system_units = Path("/usr/lib/systemd/system")
            if not system_units.is_dir():
                system_units = Path("/lib/systemd/system")
            shutil.copytree(system_units, sandbox / "usr/lib/systemd/system", symlinks=True)
            for name, body in rendered.items():
                (target / name).write_text(body)
                for m in EXEC_RE.finditer(body):
                    exe = m.group(1)
                    self.assertIn(exe, INSTALLER, "Generated service binary missing from installer")
                    stub = sandbox / exe.lstrip("/")
                    stub.parent.mkdir(parents=True, exist_ok=True)
                    stub.write_text("#!/bin/sh\nexit 0\n")
                    stub.chmod(0o755)
            # AWG's upstream package provides the awg-quick@.service template
            # on the real Pi; stub only that external dependency for CI.
            (target / "awg-quick@.service").write_text(
                "[Unit]\nDescription=AmneziaWG external template\n"
                "[Service]\nType=oneshot\nExecStart=/bin/true\n"
            )
            result = subprocess.run(
                ["systemd-analyze", "verify", f"--root={sandbox}",
                 *(str(target / name) for name in rendered)],
                capture_output=True, text=True, timeout=35,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(result.stderr.strip(), result.stderr)

    def test_systemd_verify_all_units_in_private_root(self):
        systemd_analyze = shutil.which("systemd-analyze")
        self.assertIsNotNone(systemd_analyze, "systemd-analyze missing from CI")
        system_units = Path("/usr/lib/systemd/system")
        if not system_units.is_dir():
            system_units = Path("/lib/systemd/system")
        self.assertTrue(system_units.is_dir(), "systemd base unit directory missing")
        with tempfile.TemporaryDirectory(prefix="awg-v13-unit-audit-") as d:
            sandbox = Path(d)
            target = sandbox / "etc/systemd/system"
            target.mkdir(parents=True)
            shutil.copytree(system_units, sandbox / "usr/lib/systemd/system", symlinks=True)
            for source in UNIT_SOURCES:
                shutil.copyfile(source, target / source.name)
                for m in EXEC_RE.finditer(source.read_text()):
                    executable = sandbox / m.group(1).lstrip("/")
                    if not executable.exists():
                        executable.parent.mkdir(parents=True, exist_ok=True)
                        executable.write_text("#!/bin/sh\nexit 0\n")
                        executable.chmod(0o755)
            cmd = [systemd_analyze, "verify", f"--root={sandbox}",
                   *(str(target / p.name) for p in UNIT_SOURCES)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(result.stderr.strip(), result.stderr)

if __name__ == "__main__":
    unittest.main()
