import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import engine as e
import market


def synthetic(n=400):
    start=1700002800//3600*3600
    bars=[]
    for i in range(n):
        price=100+i*.08
        bars.append(dict(t=start+i*900,o=price-.03,h=price+.1,l=price-.1,c=price,v=10))
    return bars


class Engine(unittest.TestCase):
    def setUp(self):
        self.c=json.loads(Path(__file__).with_name('config.json').read_text())
        self.s=e.fresh(self.c)
    def position(self):
        self.s['cash']=30
        self.s['positions']['XBTEUR']=dict(qty=.2,entry=100,cost=20,stop=97,target=110,
            initial_distance=3,initial_risk=.8,atr=1,strategy='test',entry_time=0,
            checked_until=60,high_close=100)
    def test_both_hits_stop(self):
        self.position();e.process_bar(self.s,'XBTEUR',dict(t=60,o=100,l=95,h=112,c=101),self.c,60)
        self.assertEqual(self.s['closed_trades'][0]['reason'],'STOP_OHLC')
        self.assertAlmostEqual(self.s['cash'],30+.2*97*.999*.996)
    def test_gap_below_stop(self):
        self.position();e.process_bar(self.s,'XBTEUR',dict(t=60,o=90,l=89,h=95,c=92),self.c,60)
        self.assertAlmostEqual(self.s['closed_trades'][0]['exit'],89.91)
    def test_trail_not_same_bar(self):
        self.position();e.process_bar(self.s,'XBTEUR',dict(t=60,o=100,l=98,h=108,c=105),self.c,60)
        self.assertIn('XBTEUR',self.s['positions']);self.assertGreater(self.s['positions']['XBTEUR']['stop'],100)
        e.process_bar(self.s,'XBTEUR',dict(t=120,o=105,l=100,h=106,c=104),self.c,60)
        self.assertNotIn('XBTEUR',self.s['positions'])
    def test_pre_entry_bar_ignored(self):
        self.position();e.process_bar(self.s,'XBTEUR',dict(t=0,o=100,l=80,h=120,c=100),self.c,60)
        self.assertIn('XBTEUR',self.s['positions'])
    def test_gap_halts(self):
        self.position();e.replay(self.s,{'XBTEUR':[dict(t=180,o=100,l=99,h=101,c=100)]},self.c)
        self.assertTrue(self.s['halted']);self.assertGreater(self.s['data_gaps'],0)
    def test_duplicate_bar_does_not_replay(self):
        self.position();bar=dict(t=60,o=100,l=99,h=101,c=100)
        e.process_bar(self.s,'XBTEUR',bar,self.c,60)
        e.process_bar(self.s,'XBTEUR',dict(t=60,o=100,l=80,h=120,c=100),self.c,60)
        self.assertIn('XBTEUR',self.s['positions'])
    def test_hourly_excludes_incomplete(self):
        bars=synthetic(7);self.assertEqual(len(e.hourly(bars)),1)
    def test_bad_bar(self):
        with self.assertRaises(ValueError):market.check([dict(t=0,o=10,l=11,h=12,c=10,v=1)],900)
    def test_missing_bar(self):
        bars=synthetic(4);del bars[1]
        with self.assertRaises(ValueError):market.check(bars,900)
    def test_drawdown_halts_entries(self):
        self.s['cash']=39;e.guard(self.s,{},self.c,1700000000)
        self.assertTrue(self.s['halted'])
    def test_daily_pause_releases_next_day(self):
        e.guard(self.s,{},self.c,1700000000);self.s['cash']=45
        e.guard(self.s,{},self.c,1700000060)
        self.assertGreater(self.s['risk_pause_until'],1700000060)
        e.guard(self.s,{},self.c,1700086400)
        self.assertLess(self.s['risk_pause_until'],1700086400)
    def test_sizing_includes_costs(self):
        k='XBTEUR';h={k:synthetic()};q={k:dict(bid=100,ask=100.01,volume_eur=1e8)};h['_quotes']=q
        sig=dict(eligible=True,stop_fraction=.03,target_fraction=.12,atr=1,strategy='test',score=80)
        meta=dict(ordermin=.0001,costmin=1,lot_decimals=8)
        self.assertEqual(e.enter(self.s,k,sig,q[k],meta,h,self.c,1700000000),'entered')
        pos=self.s['positions'][k]
        self.assertLessEqual(pos['initial_risk'],1)
        self.assertLessEqual(pos['cost'],25)
        self.assertGreaterEqual(self.s['cash'],2)
    def test_minimum_rejects(self):
        k='XBTEUR';h={k:synthetic()};q={k:dict(bid=100,ask=100.01,volume_eur=1e8)};h['_quotes']=q
        sig=dict(eligible=True,stop_fraction=.03,target_fraction=.12,atr=1,strategy='test',score=80)
        self.assertEqual(e.enter(self.s,k,sig,q[k],dict(ordermin=1,costmin=100,lot_decimals=8),h,self.c,1700000000),'exchange_minimum')
    def test_repeated_candle_no_new_decision(self):
        c=copy.deepcopy(self.c);c['symbols']=['XBTEUR'];h={'XBTEUR':synthetic()}
        q={'XBTEUR':dict(bid=130,ask=130.01,volume_eur=1e8)};m={'XBTEUR':dict(ordermin=.0001,costmin=1,lot_decimals=8)}
        e.step(self.s,h,q,m,c,1700000000)
        r=e.step(self.s,h,q,m,c,1700000010)
        self.assertEqual(r[0]['result'],'same_candle')
    def test_correlated_assets(self):
        self.assertAlmostEqual(e.correlation(synthetic(),synthetic()),1)
    def test_backtest_next_open(self):
        import backtest
        c=copy.deepcopy(self.c);c['symbols']=['XBTEUR'];c['min_quote_volume_eur']=0;bars=synthetic(304)
        fake=dict(eligible=True,reason='test',score=80,strategy='test',regime='trend',atr=1,stop_fraction=.03,target_fraction=.12)
        with patch('engine.signal',return_value=fake):
            r,s=backtest.evaluate({'XBTEUR':bars},c,300,303)
        buy=next(x for x in s['events'] if x['kind']=='BUY')
        self.assertEqual(buy['t'],bars[301]['t'])
        self.assertAlmostEqual(buy['entry'],bars[301]['o']*1.00075*1.001)

if __name__=='__main__':unittest.main()
