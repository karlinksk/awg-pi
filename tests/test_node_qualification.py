#!/usr/bin/env python3
"""Tests for pre-switch service qualification through an isolated node."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest

P=Path(__file__).resolve().parents[1]/"src"/"awg-node-qualification.py"
spec=importlib.util.spec_from_file_location("node_qualification_tests",P)
q=importlib.util.module_from_spec(spec);sys.modules[spec.name]=q;spec.loader.exec_module(q)
FINGERPRINT="e"*64
NOW=1000


def evidence(name="finland",sample="a1",values=("PASS","PASS","PASS")):
    checks={k:{"state":v,"reason":"verified"} for k,v in zip(q.REQUIRED,values)}
    status="PASS" if set(values)=={"PASS"} else ("FAIL" if "FAIL" in values else "UNKNOWN")
    return {"transport":"mihomo","identity":name,"sample_id":sample,
            "status":status,"checks":checks}


class QualificationTests(unittest.TestCase):
    def test_single_pass_is_not_service_ready(self):
        row=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                      boot_id="boot-A",policy_generation=1,checked_at=NOW)
        self.assertEqual(row["service_qualification"],"SERVICE_PENDING_CONFIRMATION")
        self.assertFalse(row["service_qualified"])

    def test_independent_passes_qualify(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        second=q.advance(first,evidence(sample="a2"),identity="finland",
                         fingerprint=FINGERPRINT,boot_id="boot-A",
                         policy_generation=1,checked_at=NOW+30)
        self.assertEqual(second["service_qualification"],"SERVICE_READY")
        self.assertEqual(second["service_confirmations"],2)
        self.assertTrue(q.ready_entry(second,now=NOW+31))

    def test_duplicate_sample_does_not_count_twice(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        second=q.advance(first,evidence(),identity="finland",fingerprint=FINGERPRINT,
                         boot_id="boot-A",policy_generation=1,checked_at=NOW+30)
        self.assertEqual(second["service_confirmations"],1)

    def test_other_node_does_not_inherit_success(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        second=q.advance(first,evidence(name="poland",sample="b"),
                         identity="poland",fingerprint=FINGERPRINT,
                         boot_id="boot-A",policy_generation=1,checked_at=NOW+30)
        self.assertFalse(second["service_qualified"])

    def test_failed_service_resets_confirmation(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        second=q.advance(first,evidence(sample="a2",values=("FAIL","PASS","PASS")),
                         identity="finland",fingerprint=FINGERPRINT,
                         boot_id="boot-A",policy_generation=1,checked_at=NOW+30)
        self.assertEqual(second["service_qualification"],"SERVICE_FAILED")
        self.assertEqual(second["service_confirmations"],0)

    def test_youtube_unknown_never_qualifies(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        second=q.advance(first,evidence(sample="a2",values=("PASS","PASS","UNKNOWN")),
                         identity="finland",fingerprint=FINGERPRINT,
                         boot_id="boot-A",policy_generation=1,checked_at=NOW+30)
        self.assertEqual(second["service_qualification"],"SERVICE_UNKNOWN")
        self.assertFalse(q.ready_entry(second,now=NOW+30))

    def test_web_challenge_not_pass(self):
        row=q.advance(None,evidence(values=("PASS","UNKNOWN","PASS")),
                      identity="finland",fingerprint=FINGERPRINT,boot_id="boot-A",
                      policy_generation=1,checked_at=NOW)
        self.assertFalse(row["service_qualified"])

    def test_status_forgery_rejected(self):
        fake=evidence();fake["checks"]["youtube_video"]["state"]="FAIL"
        row=q.advance(None,fake,identity="finland",fingerprint=FINGERPRINT,
                      boot_id="boot-A",policy_generation=1,checked_at=NOW)
        self.assertEqual(row["service_qualification"],"SERVICE_UNKNOWN")

    def test_changed_boot_generation_provider_or_expired(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=1,checked_at=NOW)
        changes=[{"boot_id":"boot-B"},{"policy_generation":2},
                 {"fingerprint":"f"*64},{"checked_at":NOW+181}]
        for change in changes:
            opts={"identity":"finland","fingerprint":FINGERPRINT,
                  "boot_id":"boot-A","policy_generation":1,"checked_at":NOW+30}
            opts.update(change)
            row=q.advance(first,evidence(sample="a2"),**opts)
            self.assertFalse(row["service_qualified"],change)

    def test_missing_network_event_collector_stays_pending(self):
        first=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                        boot_id="boot-A",policy_generation=None,checked_at=NOW)
        second=q.advance(first,evidence(sample="a2"),identity="finland",
                         fingerprint=FINGERPRINT,boot_id="boot-A",
                         policy_generation=None,checked_at=NOW+30)
        self.assertFalse(second["service_qualified"])

    def test_aggregation_no_cross_node_or_endpoint_duplicates(self):
        nodes=[{"name":"a","server":"1.2.3.4","port":443,"delay_ms":11,"fingerprint":FINGERPRINT},
               {"name":"b","server":"2.3.4.5","port":443,"delay_ms":22,"fingerprint":"f"*64}]
        entries={}
        for node in nodes:
            first=q.advance(None,evidence(name=node["name"]),identity=node["name"],
                            fingerprint=node["fingerprint"],boot_id="b",
                            policy_generation=1,checked_at=NOW)
            entries[node["name"]]=q.advance(first,evidence(name=node["name"],sample="b"),
                            identity=node["name"],fingerprint=node["fingerprint"],
                            boot_id="b",policy_generation=1,checked_at=NOW+20)
        self.assertEqual(q.summary(entries,nodes,now=NOW+21),["a","b"])
        nodes[1]["server"]="1.2.3.4"
        self.assertEqual(q.summary(entries,nodes,now=NOW+21),["a"])

    def test_summary_expiry(self):
        row=q.advance(None,evidence(),identity="finland",fingerprint=FINGERPRINT,
                      boot_id="b",policy_generation=1,checked_at=NOW)
        row=q.advance(row,evidence(sample="2"),identity="finland",
                      fingerprint=FINGERPRINT,boot_id="b",policy_generation=1,
                      checked_at=NOW+20)
        node={"name":"finland","server":"1.2.3.4","port":443,
              "delay_ms":10,"fingerprint":FINGERPRINT}
        self.assertEqual(q.summary({"finland":row},[node],now=NOW+300),[])


if __name__=="__main__":
    unittest.main()
