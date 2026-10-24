"""Real loopback controller contract; no provider, root or live gateway use."""
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import tempfile
import threading
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'src/awg-mihomo-configure').read_text()
FUNCTION='select_live_native_node(){'+SOURCE.split('select_live_native_node(){',1)[1].split('\n}\n',1)[0]+'\n}\n'


class ControllerSelection(unittest.TestCase):
    def run_case(self,now='AWG-XRAY-VLESS-LOCAL',available=True,ignore_put=False,bad_bind=False):
        target='Тест native [2]; $(not-a-command)'
        calls=[]
        state={'now':now,'all':[target] if available else ['AWG-XRAY-VLESS-LOCAL']}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append(('GET',self.path))
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps(state).encode())
            def do_PUT(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(('PUT',body))
                if not ignore_put:state['now']=body['name']
                self.send_response(204);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config=Path(directory)/'config.yaml'
                config.write_text(yaml.safe_dump({'external-controller':
                    ('0.0.0.0' if bad_bind else '127.0.0.1')+':'+str(server.server_port),
                    'proxy-groups':[{'name':'AWG TEST','type':'select'}]}))
                r=subprocess.run(['bash','-c',FUNCTION+'\nselect_live_native_node "$1"','--',target],
                    capture_output=True,text=True,timeout=17,env=dict(os.environ,
                    PYTHON_BIN=sys.executable,MIHOMO_CONFIG_FILE=str(config),
                    http_proxy='http://127.0.0.1:1',HTTP_PROXY='http://127.0.0.1:1'))
                self.assertNotIn(target,r.stdout+r.stderr)
                return r,calls,state,target
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_stale_alias_is_replaced_and_read_back(self):
        r,calls,state,target=self.run_case()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(state['now'],target)
        self.assertEqual([c[0] for c in calls],['GET','PUT','GET'])
        self.assertIn('VERIFIED',r.stdout)
        self.assertEqual(calls[0][1],'/proxies/AWG%20TEST')

    def test_already_selected_is_idempotent(self):
        r,calls,_,_=self.run_case(now='Тест native [2]; $(not-a-command)')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual([c[0] for c in calls],['GET'])

    def test_missing_target_does_not_select_alias(self):
        r,calls,_,_=self.run_case(available=False)
        self.assertNotEqual(r.returncode,0)
        self.assertFalse(any(c[0]=='PUT' for c in calls))
        self.assertIn('SELECTION_UNVERIFIED',r.stderr)

    def test_acknowledgement_without_readback_is_not_success(self):
        r,_,_,_=self.run_case(ignore_put=True)
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('SELECTION=VERIFIED',r.stdout)

    def test_non_loopback_controller_is_refused(self):
        r,calls,_,_=self.run_case(bad_bind=True)
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(calls,[])

    def test_both_native_transactions_select_before_health(self):
        for name in ('candidate_commit','node_select'):
            body=SOURCE.split(name+'(){',1)[1].split('\n}\n',1)[0]
            self.assertLess(body.index('select_live_native_node "$name"'),body.index('  wait_mihomo_healthy'))
            self.assertIn('trap rollback_',body)


if __name__=='__main__':unittest.main()
