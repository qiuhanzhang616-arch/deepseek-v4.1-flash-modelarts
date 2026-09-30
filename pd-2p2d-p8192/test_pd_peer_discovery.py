import unittest
import tempfile
import subprocess
import os
import sys
from pathlib import Path
from pd_peer_discovery import choose


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.contract = {'spec': 'dspark5', 'hash': 'same'}
        self.records = [dict(epoch='new', contract=self.contract, updated=100,
                             name=n, role=r, ip=ip) for n,r,ip in
                        [('p-b','prefill','172.16.0.12'), ('d-b','decode','172.16.0.22'),
                         ('p-a','prefill','172.16.0.11'), ('d-a','decode','172.16.0.21')]]

    def test_no_ranktable_or_role_in_name_required(self):
        self.assertEqual(choose(self.records,'new',self.contract,101,'p-b','prefill','172.16.0.12'),
                         ['172.16.0.12','172.16.0.11','1','172.16.0.11','172.16.0.12','172.16.0.21','172.16.0.22'])

    def test_rejects_missing_or_stale_peer(self):
        self.records[0]['updated'] = 0
        with self.assertRaises(ValueError): choose(self.records,'new',self.contract,101,'p-a','prefill','172.16.0.11')

    def test_rejects_mismatched_contract(self):
        self.records[0]['contract'] = {'spec':'off'}
        with self.assertRaises(ValueError): choose(self.records,'new',self.contract,101,'p-a','prefill','172.16.0.11')

    def test_rejects_duplicate_ip(self):
        self.records[0]['ip'] = self.records[1]['ip']
        with self.assertRaises(ValueError): choose(self.records,'new',self.contract,101,'p-a','prefill','172.16.0.11')

    def test_ignores_old_epoch(self):
        self.records.append(dict(self.records[0], epoch='old'))
        self.assertEqual(choose(self.records,'new',self.contract,101,'d-a','decode','172.16.0.21')[2],'0')

    def test_four_processes_discover_without_ranktable(self):
        with tempfile.TemporaryDirectory() as temp:
            common = Path(temp) / 'common.sh'
            common.write_text('paired dspark5')
            env = dict(os.environ, PD_RENDEZVOUS_ID='integration-new', PD_RENDEZVOUS_DIR=temp, PD_NUM_SPEC_TOKENS='5')
            procs = []
            try:
                for n,r,ip in [('p-b','prefill','172.16.0.12'),('d-b','decode','172.16.0.22'),
                               ('p-a','prefill','172.16.0.11'),('d-a','decode','172.16.0.21')]:
                    procs.append(subprocess.Popen([sys.executable, str(Path(__file__).with_name('pd_peer_discovery.py')),
                                                  '--role',r,'--local-ip',ip,'--pod-name',n,'--script',str(common),
                                                  '--wait-seconds','10'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
                outputs = []
                for p in procs:
                    out,err=p.communicate(timeout=15)
                    self.assertEqual(p.returncode,0,err)
                    outputs.append(out.splitlines())
                self.assertEqual(outputs[0][2],'1')
                self.assertEqual(outputs[2][2],'0')
                self.assertTrue(all(o[3:] == ['172.16.0.11','172.16.0.12','172.16.0.21','172.16.0.22'] for o in outputs))
            finally:
                for p in procs:
                    if p.poll() is None: p.kill(); p.wait()


if __name__ == '__main__': unittest.main()
