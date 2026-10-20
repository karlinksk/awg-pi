#!/usr/bin/env python3
"""Full Mihomo balanced -> AWG selection chain, no privileged production changes."""
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MONITOR=ROOT/"src"/"awg-selection-monitor"
POLICY=ROOT/"src"/"awg-mihomo-node-policy"
GATE=ROOT/"src"/"awg-mihomo-network-eligibility.py"

class SafeChain(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="awg-balanced-chain-",dir="/dev/shm")
        self.root=Path(self.temp.name)
        self.bin=self.root/"bin"
        self.bin.mkdir()
        self.run=self.root/"run"
        self.run.mkdir()
        self.selected=self.root/"selected"
        self.selected.write_text("mihomo\n")
        self.node=self.root/"node"
        self.node.write_text("current-node\n")
        self.nodes=self.root/"pool-names"
        self.nodes.write_text("ss-first\nvless-second\ntrojan-third\nhysteria2-fourth\nvmess-fifth\n")
        self.health=self.root/"health"
        self.health.write_text("down\n")
        self.awg=self.root/"awg-health"
        self.awg.write_text("up\n")
        self.awg_profile=self.root/"awg0.conf"
        self.awg_profile.write_text("mock AWG standby profile\n")
        self.cool=self.root/"cooldown"
        self.trace=self.root/"trace"
        self.trace.write_text("")
        self.node_trace=self.root/"node-trace"
        self.node_trace.write_text("")
        self.fixtures=self.root/"fixtures"
        self.fixtures.write_text("ss-first|FAIL|UNKNOWN|PASS|chatgpt_web_http_403\n"
             "vless-second|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n"
             "trojan-third|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n"
             "hysteria2-fourth|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n"
             "vmess-fifth|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n")
        (self.root/"selection.env").write_text("SELECTION_MODE=auto\nSELECTION_ORDER=mihomo,awg\n")
        (self.root/"node-policy.mode").write_text("auto\n")
        (self.root/"common.sh").write_text("""
awg_transport_get(){ cat "$MOCK_TRANSPORT_STATE"; }
awg_transport_backend_valid(){ [[ "$1" == mihomo || "$1" == awg ]]; }
""")
        self.put("transport", """#!/bin/bash
case "$1" in
 check)
   case "$2" in
     mihomo) [[ "$(cat "$MOCK_MI_HEALTH")" == up ]] ;;
     awg) [[ "$(cat "$MOCK_AWG_HEALTH")" == up ]] ;;
     *) exit 2 ;;
   esac
   ;;
 select)
   printf 'transport:%s\\n' "$2" >>"$MOCK_TRACE"
   if [[ "$2" == awg && "$(cat "$MOCK_AWG_HEALTH")" == up ]]; then
     echo awg >"$MOCK_TRANSPORT_STATE"; exit 0
   fi
   if [[ "$2" == mihomo && "$(cat "$MOCK_MI_HEALTH")" == up ]]; then
     echo mihomo >"$MOCK_TRANSPORT_STATE"; exit 0
   fi
   exit 1 ;;
 *) exit 2 ;;
esac
""")
        self.put("pool", """#!/bin/bash
case "$1" in
 ensure) exit 0 ;;
 cooldown)
   [[ "$2" == add ]] || exit 1
   printf '%s\\n' "$3" >>"$MOCK_COOLDOWN"
   exit 0 ;;
 best)
   shift 2
   excludes=()
   while (( $# )); do
     case "$1" in --exclude) excludes+=("$2"); shift 2 ;; *) exit 2 ;; esac
   done
   while IFS= read -r n; do
     [[ -n "$n" ]] || continue
     if [[ -s "$MOCK_COOLDOWN" ]] && grep -Fxq -- "$n" "$MOCK_COOLDOWN"; then continue; fi
     denied=0
     for ex in "${excludes[@]}"; do [[ "$ex" == "$n" ]] && denied=1; done
     if (( denied == 0 )); then echo "$n"; exit 0; fi
   done <"$MOCK_POOL_NAMES"
   exit 1 ;;
 *) exit 2 ;;
esac
""")
        self.put("scan", """#!/bin/bash
[[ "$1" == service-scan && "$2" == --node ]] || exit 2
record="$(grep -m1 "^$3|" "$MOCK_FIXTURES" || true)"
if [[ -z "$record" ]]; then exit 1; fi
IFS='|' read -r name api web video reason <<<"$record"
printf 'SERVICE_ELIGIBILITY=UNKNOWN\\n'
printf 'SERVICE_CHECK_OPENAI_API=%s\\n' "$api"
printf 'SERVICE_CHECK_CHATGPT_WEB=%s\\n' "$web"
printf 'SERVICE_CHECK_YOUTUBE_VIDEO=%s\\n' "$video"
printf 'SERVICE_REASON_CHATGPT_WEB=%s\\n' "$reason"
exit 1
""")
        self.put("configure", """#!/bin/bash
[[ "$1" == node && "$2" == select-auto ]] || exit 2
printf 'node:%s\\n' "$3" >>"$MOCK_NODE_TRACE"
if [[ -e "$MOCK_NODE_DENY" ]] && grep -Fxq -- "$3" "$MOCK_NODE_DENY"; then exit 1; fi
printf '%s\\n' "$3" >"$MOCK_NODE_NAME_FILE"
""")
        self.put("logger","#!/bin/sh\nexit 0\n")
        self.put("service-active", "#!/bin/sh\nprintf '{\"status\":\"UNKNOWN\"}\n'\nexit 1\n")
        script=POLICY.read_text()
        guard='[[ ${EUID:-$(id -u)} -eq 0 ]] || exec sudo "$0" "$@"'
        self.assertIn(guard,script)
        self.put("node-policy",script.replace(guard,": # unprivileged fixture only",1))
        self.env=dict(os.environ,
          AWG_COMMON_FILE=str(self.root/"common.sh"),
          AWG_TRANSPORT_FILE=str(self.selected),
          AWG_SELECTION_FILE=str(self.root/"selection.env"),
          AWG_TRANSPORT_CLI=str(self.bin/"transport"),
          MIHOMO_NODE_POLICY_CLI=str(self.bin/"node-policy"),
          AWG_SELECTION_STATE_DIR=str(self.run),
          AWG_SELECTION_FAILURES=str(self.run/"failures"),
          AWG_LOCK_FILE=str(self.run/"maintenance.lock"),
          AWG_SELECTION_ONCE="1",
          AWG_SELECTION_FAILURE_THRESHOLD="3",
          AWG_AUTO_AWG_CONFIG=str(self.awg_profile),
          MIHOMO_SERVICE_GATE_MODE="balanced",
          MIHOMO_SERVICE_CHECK_BIN=str(self.bin/"service-active"),
          MIHOMO_SERVICE_NODE_FILE=str(self.node),
          MIHOMO_SERVICE_CHECK_INTERVAL="0",
          LOGGER_BIN=str(self.bin/"logger"),
          MIHOMO_NODE_POLICY_MODE_FILE=str(self.root/"node-policy.mode"),
          MIHOMO_NODE_POLICY_ORDER_FILE=str(self.root/"node-policy.nodes"),
          MIHOMO_NODE_NAME_FILE=str(self.node),
          MIHOMO_POOL_CLI=str(self.bin/"pool"),
          MIHOMO_CONFIGURE_BIN=str(self.bin/"configure"),
          MIHOMO_SERVICE_QUICKCHECK_BIN=str(self.bin/"scan"),
          MIHOMO_NETWORK_GATE_BIN=str(GATE),
          MOCK_TRANSPORT_STATE=str(self.selected),
          MOCK_MI_HEALTH=str(self.health),
          MOCK_AWG_HEALTH=str(self.awg),
          MOCK_TRACE=str(self.trace),
          MOCK_NODE_TRACE=str(self.node_trace),
          MOCK_COOLDOWN=str(self.cool),
          MOCK_POOL_NAMES=str(self.nodes),
          MOCK_FIXTURES=str(self.fixtures),
          MOCK_NODE_NAME_FILE=str(self.node),
          MOCK_NODE_DENY=str(self.root/"deny"),
        )

    def tearDown(self): self.temp.cleanup()

    def put(self,name,content):
        p=self.bin/name
        p.write_text(content)
        p.chmod(0o700)

    def cycles(self,n=3):
        results=[]
        for _ in range(n):
            out=subprocess.run(["bash",str(MONITOR)],env=self.env,
                 cwd=self.root,capture_output=True,text=True,timeout=12)
            self.assertEqual(out.returncode,0,out.stderr)
            results.append(out.stdout.strip())
        return results

    def test_primary_candidate_qualified_goes_mihomo_not_awg(self):
        out=self.cycles()
        self.assertIn("MIHOMO_NODE_FAILOVER=current-node->vless-second",out[-1])
        self.assertEqual(self.selected.read_text().strip(),"mihomo")
        self.assertEqual(self.node.read_text().strip(),"vless-second")
        self.assertNotIn("transport:awg",self.trace.read_text())
        self.assertEqual((self.run/"failures").read_text().strip(),"0")

    def test_three_rejected_candidates_then_awg_fallback(self):
        self.fixtures.write_text("ss-first|FAIL|UNKNOWN|PASS|chatgpt_web_http_403\n"
            "vless-second|PASS|UNKNOWN|UNKNOWN|chatgpt_web_http_403\n"
            "trojan-third|PASS|UNKNOWN|PASS|chatgpt_web_TimeoutError\n")
        out=self.cycles()
        self.assertEqual(out[-1],"FAILOVER=mihomo->awg")
        self.assertEqual(self.selected.read_text().strip(),"awg")
        self.assertEqual(self.node.read_text().strip(),"current-node")
        self.assertIn("transport:awg",self.trace.read_text())
        self.assertEqual(self.node_trace.read_text(),"")
        self.assertEqual((self.run/"failures").read_text().strip(),"0")

    def test_unconfigured_awg_is_not_retried_after_node_exhaustion(self):
        self.fixtures.write_text("")
        self.awg_profile.unlink()
        self.cycles(5)
        self.assertEqual(self.selected.read_text().strip(),"mihomo")
        self.assertNotIn("transport:awg",self.trace.read_text())
        self.assertEqual((self.run/"failures").read_text().strip(),"3")

    def test_failed_awg_rollback_keeps_mihomo_and_saturates(self):
        self.fixtures.write_text("")
        self.awg.write_text("down\n")
        self.cycles()
        self.assertEqual(self.selected.read_text().strip(),"mihomo")
        self.assertEqual((self.run/"failures").read_text().strip(),"3")
        self.assertEqual(self.trace.read_text().count("transport:awg"),1)

    def test_awg_after_recovery_is_sticky_and_no_switch_back(self):
        self.fixtures.write_text("")
        self.cycles()
        self.assertEqual(self.selected.read_text().strip(),"awg")
        self.health.write_text("up\n")
        self.cycles(1)
        self.assertEqual(self.selected.read_text().strip(),"awg")
        self.assertNotIn("transport:mihomo",self.trace.read_text())

    def test_healthy_active_mihomo_does_not_switch_on_cloudflare_unknown(self):
        self.health.write_text("up\n")
        self.cycles(5)
        self.assertEqual(self.selected.read_text().strip(),"mihomo")
        self.assertEqual(self.node.read_text().strip(),"current-node")
        self.assertEqual(self.trace.read_text(),"")

    def test_failed_first_node_activation_tries_second_before_awg(self):
        self.fixtures.write_text("ss-first|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n"
            "vless-second|PASS|UNKNOWN|PASS|chatgpt_web_http_403\n")
        (self.root/"deny").write_text("ss-first\n")
        out=self.cycles()
        self.assertEqual(out[-1],"MIHOMO_NODE_FAILOVER=current-node->vless-second")
        self.assertEqual(self.node.read_text().strip(),"vless-second")
        self.assertIn("node:ss-first",self.node_trace.read_text())
        self.assertIn("node:vless-second",self.node_trace.read_text())
        self.assertNotIn("transport:awg",self.trace.read_text())

    def test_node_policy_disabled_allows_existing_transport_fallback(self):
        (self.root/"node-policy.mode").write_text("manual\n")
        out=self.cycles()
        self.assertEqual(out[-1],"FAILOVER=mihomo->awg")
        self.assertEqual(self.node_trace.read_text(),"")
        self.assertEqual(self.selected.read_text().strip(),"awg")

    def test_maintenance_lock_suppresses_failover(self):
        lock_path=self.run/"maintenance.lock"
        with lock_path.open("w") as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            out=self.cycles(3)
            self.assertEqual(out,["","",""])
        self.assertEqual(self.trace.read_text(),"")
        self.assertFalse((self.run/"failures").exists())

if __name__=="__main__":
    unittest.main()
