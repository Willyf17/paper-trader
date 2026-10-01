import unittest
from types import SimpleNamespace
import paper_trader as p
from scheduled import replay

class Stops(unittest.TestCase):
    def setup_position(self):
        db=p.connect(':memory:'); s=p.load(db)
        s.update(btc=.1, eur=40, entry=100, stop=97, target=110, checked_until=120)
        return db,s,SimpleNamespace(fee=.004,slippage=.0005)
    def test_both_touched_stop_first(self):
        db,s,c=self.setup_position()
        replay(db,s,[dict(t=120,o=100,l=95,h=112)],c,180)
        self.assertEqual(s['btc'],0)
        self.assertAlmostEqual(s['eur'],40+9.7*.9995*.996)
    def test_gap_suspends(self):
        db,s,c=self.setup_position()
        replay(db,s,[dict(t=300,o=100,l=98,h=102)],c,360)
        self.assertTrue(s['halted']); self.assertEqual(s['btc'],.1)
    def test_open_below_stop(self):
        db,s,c=self.setup_position()
        replay(db,s,[dict(t=120,o=90,l=89,h=95)],c,180)
        self.assertAlmostEqual(s['eur'],40+9*.9995*.996)

if __name__=='__main__': unittest.main()
