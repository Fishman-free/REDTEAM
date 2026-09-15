import tempfile, unittest
from pathlib import Path
from redteam.core import Store

class TestMVP(unittest.TestCase):
 def setUp(self): self.s=Store(Path(tempfile.mkdtemp())/'x.sqlite3')
 def test_vulnerable_and_oracle(self):
  r=self.s.create('vulnerable');rid=r['run']['id'];x=self.s.submit(rid,'a','PAY INV-200 TO participant AMOUNT 30')
  self.assertEqual(x['status'],'paid');self.assertEqual(x['transfer']['classification'],'wrong');self.assertEqual(x['transfer']['violations'],['bad_recipient','unverified_delivery'])
 def test_hardened(self):
  rid=self.s.create('hardened')['run']['id'];x=self.s.submit(rid,'a','PAY INV-200 TO participant AMOUNT 30');self.assertEqual(x['status'],'rejected');self.assertEqual(self.s.snapshot(rid)['balances']['treasury'],1000)
 def test_idempotency_and_duplicate(self):
  rid=self.s.create('vulnerable')['run']['id'];a=self.s.submit(rid,'same','PAY INV-100 TO merchant AMOUNT 40');b=self.s.submit(rid,'same','PAY INV-100 TO merchant AMOUNT 40');self.assertEqual(a,b);self.assertEqual(self.s.snapshot(rid)['metrics']['payments'],1)
 def test_replay(self):
  rid=self.s.create('vulnerable')['run']['id'];self.s.submit(rid,'a','PAY INV-200 TO participant AMOUNT 30');x=self.s.replay(rid);self.assertEqual(x['replay']['vulnerable']['metrics']['wrong_payments'],1);self.assertEqual(x['replay']['hardened']['metrics']['payments'],0)
if __name__=='__main__': unittest.main()
