"""Exercise the engine delay HTTP protocol, including ambiguous infrastructure."""
import json
import os
from pathlib import Path
import subprocess
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'src/awg-transport').read_text()
FUNCTION='network_check(){'+SOURCE.split('network_check(){',1)[1].split('\n}\n',1)[0]+'\n}\n'

class EngineNetwork(unittest.TestCase):
    def probe(self,delay=42,status=200,changed=False,malformed=False):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append(self.path)
                is_delay='/delay?' in self.path
                self.send_response(status if is_delay else 200);self.end_headers()
                if malformed and is_delay:self.wfile.write(b'not json');return
                obj=({'delay':delay} if is_delay else
                     {'now':'Changed' if changed and len(calls)>1 else 'Node / A'})
                self.wfile.write(json.dumps(obj).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            script=FUNCTION+'\ncheck_mihomo(){ return 0; }\n'+\
                'MIHOMO_API=http://127.0.0.1:'+str(server.server_port)+'\nnetwork_check\n'
            env={**os.environ,'HTTPS_PROXY':'http://127.0.0.1:1',
                 'HTTP_PROXY':'http://127.0.0.1:1','ALL_PROXY':'http://127.0.0.1:1'}
            result=subprocess.run(['bash','-c',script],env=env,capture_output=True,timeout=12)
            return result.returncode,calls
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_fresh_delay_success_encoded_exact_target(self):
        rc,calls=self.probe();self.assertEqual(rc,0)
        self.assertIn('/proxies/Node%20%2F%20A/delay?',calls[1])
        self.assertIn('generate_204',calls[1])
        self.assertEqual(calls[0],calls[-1])
    def test_engine_negative_network_result(self):
        for status in (503,504):
            with self.subTest(status=status):self.assertEqual(self.probe(status=status)[0],1)
    def test_missing_proxy_is_infrastructure(self):self.assertEqual(self.probe(status=404)[0],2)
    def test_malformed_delay_is_infrastructure(self):self.assertEqual(self.probe(malformed=True)[0],2)
    def test_invalid_delay_is_not_remote_failure(self):
        for delay in (None,0,-1,True,'5'):
            with self.subTest(delay=delay):self.assertEqual(self.probe(delay=delay)[0],2)
    def test_selection_changed_invalidates_positive_and_negative(self):
        for status in (200,503):
            with self.subTest(status=status):self.assertEqual(self.probe(status=status,changed=True)[0],2)

class MonitorNetwork(unittest.TestCase):
    def run_monitor(self,network_rc,manual=False):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);log=p/'calls';log.touch()
            common=p/'common';common.write_text('awg_transport_get(){ echo mihomo; }\nawg_transport_backend_valid(){ return 0; }\n')
            policy=p/'policy';policy.write_text('SELECTION_MODE=manual\n' if manual else 'SELECTION_MODE=auto\nSELECTION_ORDER=mihomo,awg\n')
            transport=p/'transport';transport.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\ncase "$1" in\ncheck)exit 0;;\nnetwork-check)exit '+str(network_rc)+';;\nselect)exit 1;;\nesac\n');transport.chmod(0o755)
            node=p/'node';node.write_text('#!/bin/sh\n[ "$1" = enabled ] && exit 1\nexit 1\n');node.chmod(0o755)
            env={**os.environ,'AWG_COMMON_FILE':str(common),'AWG_SELECTION_FILE':str(policy),
                 'AWG_TRANSPORT_CLI':str(transport),'MIHOMO_NODE_POLICY_CLI':str(node),
                 'AWG_SELECTION_STATE_DIR':str(p/'run'),'AWG_SELECTION_ONCE':'1',
                 'AWG_SELECTION_FAILURE_THRESHOLD':'1','AWG_LOCK_FILE':str(p/'lock'),
                 'LOGGER_BIN':'true','CALLS':str(log),'AWG_AUTO_AWG_CONFIG':str(p/'absent')}
            r=subprocess.run(['bash',str(ROOT/'src/awg-selection-monitor')],env=env,capture_output=True,timeout=6)
            counter=p/'run/selection.failures'
            return r.returncode,log.read_text(),counter.read_text().strip() if counter.exists() else None
    def test_manual_does_not_assess_remote_node(self):
        rc,calls,counter=self.run_monitor(1,manual=True)
        self.assertEqual(rc,0);self.assertEqual(calls,'');self.assertEqual(counter,'0')
    def test_network_negative_triggers_failure_counter(self):
        rc,calls,counter=self.run_monitor(1)
        self.assertEqual(rc,0);self.assertIn('network-check',calls);self.assertEqual(counter,'1')
    def test_infrastructure_unknown_does_not_count_node_failure(self):
        rc,calls,counter=self.run_monitor(2)
        self.assertEqual(rc,0);self.assertIn('network-check',calls);self.assertIsNone(counter)
    def test_network_success_resets_counter(self):
        rc,calls,counter=self.run_monitor(0)
        self.assertEqual(rc,0);self.assertEqual(counter,'0')

if __name__=='__main__':unittest.main()
