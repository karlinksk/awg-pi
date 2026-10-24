"""Candidate failure can retry only after quiesce and watchdog retirement."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]

def load(name, file):
    spec=importlib.util.spec_from_file_location(name,ROOT/"src"/file)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

tx=load("retry_tx","awg-xray-activation-transaction.py")
linux=load("retry_linux","awg-xray-live-backend.py")

class RetryContract(unittest.TestCase):
    def backend(self):
        backend=mock.Mock(spec=tx.Backend)
        for method in ("check_local_ready","check_provider_unchanged","check_tun_ready",
                       "check_policy_routes","check_boot_dependencies","verify_committed_node",
                       "fail_closed","finalize_retryable_abort"):
            getattr(backend,method).return_value=True
        return backend

    def test_https_failure_can_retry_after_confirmed_cleanup(self):
        for method in ("check_local_ready","check_tun_ready"):
            with self.subTest(method=method):
                backend=self.backend();getattr(backend,method).return_value=False
                with self.assertRaises(tx.ActivationFailure) as error:
                    tx.activate("dead","next",backend)
                self.assertTrue(error.exception.retryable)
                self.assertLess(backend.mock_calls.index(mock.call.fail_closed()),
                                backend.mock_calls.index(mock.call.finalize_retryable_abort()))
                backend.commit.assert_not_called()

    def test_unconfirmed_cleanup_retains_watchdog_and_blocks_retry(self):
        backend=self.backend();backend.check_tun_ready.return_value=False
        backend.fail_closed.return_value=False
        with self.assertRaisesRegex(tx.ActivationFailure,"FAIL_CLOSED_UNCONFIRMED") as error:
            tx.activate("dead","next",backend)
        self.assertFalse(error.exception.retryable)
        backend.finalize_retryable_abort.assert_not_called()
        backend.disarm_watchdog.assert_not_called()

    def test_failed_or_raised_retirement_blocks_retry(self):
        for raises in (False,True):
            backend=self.backend();backend.check_tun_ready.return_value=False
            if raises:backend.finalize_retryable_abort.side_effect=RuntimeError("TIMER_FAILED")
            else:backend.finalize_retryable_abort.return_value=False
            with self.assertRaises(tx.ActivationFailure) as error:
                tx.activate("dead","next",backend)
            self.assertFalse(error.exception.retryable)

    def test_infrastructure_and_persistence_errors_never_retry(self):
        for method in ("check_provider_unchanged","check_policy_routes",
                       "check_boot_dependencies","verify_committed_node"):
            backend=self.backend();getattr(backend,method).return_value=False
            with self.assertRaises(tx.ActivationFailure) as error:
                tx.activate("dead","next",backend)
            self.assertFalse(error.exception.retryable)
            backend.finalize_retryable_abort.assert_not_called()

    def test_backend_exception_text_cannot_forge_candidate_failure(self):
        backend=self.backend()
        backend.stage_mihomo_bridge.side_effect=RuntimeError("LIVE_TUN_NOT_READY")
        with self.assertRaises(tx.ActivationFailure) as error:
            tx.activate("dead","next",backend)
        self.assertFalse(error.exception.retryable)
        backend.finalize_retryable_abort.assert_not_called()

class LinuxRetirement(unittest.TestCase):
    def run_case(self, mode="transit", safe=True, state="armed", provider=True,
                 transport="mihomo", foreign=False, current="dead", policy="auto"):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snap=root/"snapshot";snap.mkdir()
            (snap/"state.json").write_text(json.dumps({"state":state}))
            paths={name:root/name for name in
                   ("NODE_POLICY_MODE","CURRENT","MODE","BRIDGE","BRIDGE_RUNTIME","SELECTED")}
            paths["NODE_POLICY_MODE"].write_text(policy)
            paths["CURRENT"].write_text(current)
            paths["MODE"].write_text(mode)
            if foreign:paths["BRIDGE"].write_text("foreign")
            backend=linux.LinuxBackend("dead","next")
            backend.snapshot=snap;backend.watchdog_unit="test-owned-watchdog"
            at_disarm=[]
            with mock.patch.multiple(linux,**paths), \
                 mock.patch.object(linux,"run",return_value=transport), \
                 mock.patch.object(linux,"verified_degraded_auto_transit_baseline",return_value=safe), \
                 mock.patch.object(linux,"verified_degraded_selective_baseline",return_value=safe), \
                 mock.patch.object(backend,"check_provider_unchanged",return_value=provider), \
                 mock.patch.object(backend,"disarm_watchdog",side_effect=lambda:
                     at_disarm.append(json.loads((snap/"state.json").read_text())["state"])):
                result=backend.finalize_retryable_abort()
            return result,json.loads((snap/"state.json").read_text())["state"],at_disarm

    def test_both_modes_persist_quiesced_before_disarm(self):
        for mode in ("transit","selective"):
            self.assertEqual(self.run_case(mode=mode),(True,"quiesced",["quiesced"]))

    def test_invalid_baseline_or_changed_identity_keeps_timer(self):
        for options in ({"safe":False},{"provider":False},{"transport":"awg"},
                        {"foreign":True},{"mode":"invalid"},{"current":"changed"},
                        {"policy":"fixed"}):
            self.assertEqual(self.run_case(**options),(False,"armed",[]))

    def test_old_committed_or_expired_watchdog_cannot_be_retired_as_failed(self):
        for state in ("committed","expired_before_mutation"):
            self.assertEqual(self.run_case(state=state),(False,state,[]))

    def test_already_queued_old_watchdog_cannot_quiesce_next_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshot=root/"xray-failover-123-456";snapshot.mkdir()
            (snapshot/"state.json").write_text(json.dumps({"state":"quiesced"}))
            with mock.patch.multiple(linux,BASE=root,MAINTENANCE_LOCK=root/"maintenance.lock"), \
                 mock.patch.object(linux,"failclosed") as quiesce, \
                 mock.patch.object(linux,"run") as command:
                linux.watchdog(snapshot)
            quiesce.assert_not_called()
            command.assert_not_called()

if __name__=="__main__":unittest.main()
