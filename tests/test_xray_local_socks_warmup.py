"""SOCKS5 readiness must not require any external website."""
import importlib.util,sys,unittest
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location("local_ready",Path(__file__).resolve().parents[1]/"src/awg-xray-live-backend.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
class Socket:
    def __init__(self,reply=b"\x05\x00"):self.reply=reply;self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def settimeout(self,t):pass
    def sendall(self,data):self.sent.append(data)
    def recv(self,n):return self.reply
class Clock:
    def __init__(self):self.n=0
    def __call__(self):self.n+=1;return self.n
class Ready(unittest.TestCase):
    def run_probe(self,connection,active=True):
        with mock.patch.object(m.socket,"create_connection",side_effect=connection) as sock, mock.patch.object(m,"active",return_value=active), mock.patch.object(m.time,"monotonic",side_effect=Clock()), mock.patch.object(m.time,"sleep"), mock.patch.object(m.subprocess,"run",side_effect=AssertionError("external command forbidden")):
            return m.LinuxBackend("old","new").check_local_ready(),sock
    def test_protocol_ready_without_https(self):
        s=Socket();ok,c=self.run_probe(lambda *a,**k:s);self.assertTrue(ok);self.assertEqual(s.sent,[b"\x05\x01\x00"]);self.assertEqual(c.call_args.args[0],("127.0.0.1",17892))
    def test_late_listener_retries(self):
        n=[0]
        def connect(*a,**k):
            n[0]+=1
            if n[0]<3:raise ConnectionRefusedError()
            return Socket()
        ok,c=self.run_probe(connect);self.assertTrue(ok);self.assertEqual(c.call_count,3)
    def test_missing_listener_bounded(self):
        def connect(*a,**k):raise ConnectionRefusedError()
        ok,c=self.run_probe(connect);self.assertFalse(ok);self.assertLessEqual(c.call_count,12)
    def test_wrong_protocol_rejected(self):self.assertFalse(self.run_probe(lambda *a,**k:Socket(b"HTTP"))[0])
    def test_authentication_refusal_rejected(self):self.assertFalse(self.run_probe(lambda *a,**k:Socket(b"\x05\xff"))[0])
    def test_inactive_service_never_connects(self):
        ok,c=self.run_probe(lambda *a,**k:Socket(),active=False);self.assertFalse(ok);c.assert_not_called()
