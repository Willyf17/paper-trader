"""Chronological fixed-rule evaluation; signals execute at the NEXT bar open."""
import argparse
import copy
import json
from pathlib import Path
import engine as e
import market


def evaluate(data,c,start,end):
    c=copy.deepcopy(c);c['symbols']=list(data);e.validate(c)
    s=e.fresh(c);meta={k:dict(ordermin=0,costmin=0,lot_decimals=8) for k in data}
    # Minimum-size history is unknown: this is an explicitly hypothetical assumption.
    def quotes(i):
        return {k:dict(bid=rows[i]['o']*.99925,ask=rows[i]['o']*1.00075,volume_eur=sum(b['v']*b['c'] for b in rows[max(0,i-96):i])) for k,rows in data.items()}
    for i in range(max(300,start),min(end,len(next(iter(data.values())))-1)):
        for k in list(s['positions']):e.process_bar(s,k,data[k][i],c,900)
        h={k:rows[max(0,i-719):i+1] for k,rows in data.items()}
        q=quotes(i+1);t=next(iter(data.values()))[i+1]['t']
        e.step(s,h,q,meta,c,t)
        # Historical entry is assumed at this open; the following bar can hit a stop.
        for pos in s['positions'].values():
            if pos['entry_time']==t:pos['checked_until']=t
        e.report(s,q,c,t)
    last=min(end,len(next(iter(data.values())))-1)
    if last<=max(300,start):raise ValueError('Too little data in fold')
    for k in list(s['positions']):e.process_bar(s,k,data[k][last],c,900)
    q={k:dict(bid=rows[last]['c']*.99925,ask=rows[last]['c']*1.00075,volume_eur=sum(b['v']*b['c'] for b in rows[max(0,last-96):last])) for k,rows in data.items()}
    t=next(iter(data.values()))[last]['t']+900
    for k in list(s['positions']):e.sell(s,k,q[k]['bid'],c,t,'END_OF_TEST')
    result=e.report(s,q,c,t)
    result['period_start_epoch']=next(iter(data.values()))[max(300,start)]['t']
    result['period_end_epoch']=t
    result['execution_assumptions']='15m OHLC; 0.15% total assumed spread; fixed simulated fees; historical minimum sizes/liquidity unknown'
    return result,s


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',default='data');p.add_argument('--folds',type=int,default=3)
    p.add_argument('--stress-costs',action='store_true');args=p.parse_args()
    if not 1<=args.folds<=10:raise ValueError('folds 1..10')
    folder=Path(args.data);data={f.stem:json.loads(f.read_text()) for f in folder.glob('*EUR.json')}
    if not data:raise ValueError('No data files; run history.py first')
    for rows in data.values():market.check(rows,900)
    common=sorted(set.intersection(*(set(b['t'] for b in rows) for rows in data.values())))
    indexes={k:{b['t']:b for b in rows} for k,rows in data.items()}
    data={k:[index[t] for t in common] for k,index in indexes.items()}
    for rows in data.values():market.check(rows,900)
    n=len(common);c=json.loads(Path('config.json').read_text())
    if args.stress_costs:c['fee']*=1.5;c['slippage']*=2
    if n-300<args.folds*96*7:raise ValueError('Need at least 7 days per fold plus 300 warmup bars')
    width=(n-301)//args.folds;reports=[]
    for i in range(args.folds):
        a=300+i*width;b=n-1 if i==args.folds-1 else a+width
        r,s=evaluate(data,c,a,b);r['fold']=i+1;reports.append(r)
    out=Path('research');out.mkdir(exist_ok=True)
    (out/('stress.json' if args.stress_costs else 'evaluation.json')).write_text(json.dumps(dict(
        config=c,folds=reports,method='Fixed rules on successive chronological partitions; no fitting or parameter search',
        warning='Historical evaluation, not proven performance. Selected surviving assets and another venue introduce bias.'),indent=2))
    for r in reports: print(json.dumps({k:r[k] for k in ('fold','return_pct','max_observed_drawdown_pct','closed_trades','profit_factor','btc_buy_hold_after_exit_eur')}))

if __name__=='__main__':main()
