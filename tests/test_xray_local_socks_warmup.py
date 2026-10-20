#!/usr/bin/env python3
"""Isolated Xray SOCKS warmup tests. No actual network or root mutations."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location(
    "xray_local_warmup",ROOT/"src/awg-xray-live-backend.py")
m=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=m
SPEC.loader.exec_module(m)

class Socket:
    def __enter__(self):return self
    def __exit__(self,*args):return False

class Clock:
    def __init__(self):self.now=-1
    def monotonic(self):
        self.now+=1
        return self.now

class XrayLocalHTTPSWarmup(unittest.TestCase):
    def setUp(self):
        self.backend=m.LinuxBackend("FAILED","CANDIDATE")

    def test_listener_late_and_exact_401_after_retry(self):
        calls=[]
        def socket(*a,**kw):
            calls.append((a,kw))
            if len(calls)<3:raise ConnectionRefusedError()
            return Socket()
        with (mock.patch.object(m.socket,"create_connection",side_effect=socket),
              mock.patch.object(m,"active",return_value=True),
              mock.patch.object(m,"http_code",side_effect=[False,True]) as tls,
              mock.patch.object(m.time,"monotonic",side_effect=Clock().monotonic),
              mock.patch.object(m.time,"sleep") as sleep):
            self.assertTrue(self.backend.check_local_https())
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[-1][0],("127.0.0.1",17892))
        self.assertEqual(tls.call_count,2)
        self.assertEqual(tls.call_args.args[0],
                         ["--socks5-hostname","127.0.0.1:17892","--noproxy",""])
        self.assertTrue(sleep.called)

    def test_immediate_success_no_unneeded_retries(self):
        with (mock.patch.object(m.socket,"create_connection",return_value=Socket()) as sock,
              mock.patch.object(m,"active",return_value=True),
              mock.patch.object(m,"http_code",return_value=True) as tls,
              mock.patch.object(m.time,"monotonic",side_effect=Clock().monotonic),
              mock.patch.object(m.time,"sleep") as sleep):
            self.assertTrue(self.backend.check_local_https())
        sock.assert_called_once()
        tls.assert_called_once()
        sleep.assert_not_called()

    def test_no_listener_never_calls_https_and_is_bounded(self):
        clock=Clock()
        with (mock.patch.object(m.socket,"create_connection",
                                side_effect=ConnectionRefusedError()) as sock,
              mock.patch.object(m,"active",return_value=True),
              mock.patch.object(m,"http_code") as tls,
              mock.patch.object(m.time,"monotonic",side_effect=clock.monotonic),
              mock.patch.object(m.time,"sleep")):
            self.assertFalse(self.backend.check_local_https())
        self.assertLessEqual(sock.call_count,12)
        tls.assert_not_called()

    def test_xray_inactive_refuses_before_socket(self):
        with (mock.patch.object(m.socket,"create_connection") as sock,
              mock.patch.object(m,"active",return_value=False),
              mock.patch.object(m,"http_code") as tls,
              mock.patch.object(m.time,"monotonic",side_effect=Clock().monotonic)):
            self.assertFalse(self.backend.check_local_https())
        sock.assert_not_called()
        tls.assert_not_called()

    def test_http_denied_three_times_cannot_claim_ready(self):
        with (mock.patch.object(m.socket,"create_connection",return_value=Socket()),
              mock.patch.object(m,"active",return_value=True),
              mock.patch.object(m,"http_code",side_effect=[False,False,False]) as tls,
              mock.patch.object(m.time,"monotonic",side_effect=Clock().monotonic),
              mock.patch.object(m.time,"sleep") as sleep):
            self.assertFalse(self.backend.check_local_https())
        self.assertEqual(tls.call_count,3)
        self.assertEqual(sleep.call_count,2)

    def test_xray_dies_during_tls_retry(self):
        with (mock.patch.object(m.socket,"create_connection",return_value=Socket()),
              mock.patch.object(m,"active",side_effect=[True,True,False]) as running,
              mock.patch.object(m,"http_code",return_value=False) as tls,
              mock.patch.object(m.time,"monotonic",side_effect=Clock().monotonic),
              mock.patch.object(m.time,"sleep")):
            self.assertFalse(self.backend.check_local_https())
        self.assertEqual(running.call_count,3)
        tls.assert_called_once()

if __name__=="__main__":unittest.main()
