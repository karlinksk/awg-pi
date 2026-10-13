#!/usr/bin/env python3
"""Stage40 read-only host readiness and boot dependency static tests."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

AUDIT=Path(__file__).resolve().parents[1]/"src"/"awg-mihomo-stage40-boot-audit.py"
spec=importlib.util.spec_from_file_location("stage40audit",AUDIT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ReadinessTests(unittest.TestCase):
    def simulation(self,recovery=True,dependencies=True,persistent=True,sample=False,filesystem="ext4"):
        def fake(*argv):
            if argv[0]=="findmnt": return (0,filesystem)
            svc=argv[2] if argv[0]=="systemctl" else ""
            field=argv[4] if len(argv)>4 else ""
            if svc == m.RECOVERY:
                if field == "FragmentPath":
                    return (0,"/etc/systemd/system/awg-native-fallback-recovery.service") if recovery else (1,"")
                if field == "ExecStart": return (0,"/usr/bin/false" if sample else "/usr/local/sbin/awg-native-fallback-restore")
            if field=="FragmentPath": return (0,"/etc/systemd/system/"+svc)
            if field in ("Requires","After"):
                return (0,m.RECOVERY) if dependencies else (0,"network-online.target")
            raise AssertionError(argv)
        result=m.audit(command=fake,is_dir=lambda p: persistent)
        return result

    def test_uninstalled_recovery_blocks(self):
        s=self.simulation(recovery=False)
        self.assertFalse(s["ready"])
        self.assertIn("RECOVERY_UNIT_NOT_INSTALLED",s["blockers"])

    def test_every_service_must_depend_on_boot_recovery(self):
        s=self.simulation(dependencies=False)
        self.assertFalse(s["ready"])
        for name in m.PROTECTED:
            self.assertIn("UNORDERED:"+name+":Requires",s["blockers"])
            self.assertIn("UNORDERED:"+name+":After",s["blockers"])

    def test_persistent_recovery_missing(self):
        s=self.simulation(persistent=False)
        self.assertIn("NO_DURABLE_ROOT_RECOVERY",s["blockers"])

    def test_tmpfs_recovery_not_sufficient(self):
        s=self.simulation(filesystem="tmpfs")
        self.assertIn("NO_LOCAL_PERSISTENT_FILESYSTEM",s["blockers"])

    def test_placeholder_systemd_exec_rejected(self):
        s=self.simulation(sample=True)
        self.assertIn("RECOVERY_EXECUTOR_UNVERIFIED",s["blockers"])

    def test_no_static_issues_in_fully_mocked_environment(self):
        s=self.simulation()
        self.assertTrue(s["ready"],s["blockers"])

    def test_live_host_audit_runs_unprivileged(self):
        p=subprocess.run([sys.executable,"-B",str(AUDIT),"--json"],capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,2,p.stderr)
        import json
        result=json.loads(p.stdout)
        self.assertFalse(result["ready"])
        self.assertIn("RECOVERY_UNIT_NOT_INSTALLED",result["blockers"])
        self.assertIn("NO_DURABLE_ROOT_RECOVERY",result["blockers"])

    def test_external_appliances_not_contacted_by_audit_source(self):
        text=AUDIT.read_text()
        self.assertNotIn("ssh ",text)
        self.assertNotIn("curl ",text)
        self.assertNotIn("sudo ",text)
        self.assertNotIn("RouterOS API",text)
        self.assertEqual(len(m.PROTECTED),5)

if __name__=="__main__":
    unittest.main()
