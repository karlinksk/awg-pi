import pathlib,unittest
S=(pathlib.Path(__file__).resolve().parents[1]/"scripts/awg-xray-transit-one-shot-failover.sh").read_text()
class SecondFaultPostPoll(unittest.TestCase):
    def test_final_verification_before_timeout_and_rollback(self):
        p=S.index('if [[ "$second" == TIMEOUT ]] && automatic_awg_recovery_verified;then')
        self.assertLess(S.index('done\n', S.index('for i in $(seq 1 30)')),p)
        self.assertLess(p,S.index('echo "SECOND_RESULT=$second"'))
        self.assertLess(p,S.index('bash "$dir/recover"',p))
        self.assertIn('TRANSIT_XRAY_AUTO_FAILOVER=PASS_PI_TUN_AND_GUARD_ONLY',S)
        self.assertIn('TRANSIT_LAN_PACKET_FAILCLOSED=NOT_TESTED',S)
if __name__=="__main__":unittest.main()
