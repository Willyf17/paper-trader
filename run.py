import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import engine as e
import market


def atomic(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        f.write(content);f.flush();os.fsync(f.fileno());name=f.name
    os.replace(name,path)


def main():
    p=argparse.ArgumentParser();p.add_argument('--demo',action='store_true');args=p.parse_args()
    c=json.loads(Path('config.json').read_text());e.validate(c)
    config_id=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()
    path=Path('state/portfolio.json')
    s=json.loads(path.read_text()) if path.exists() and not args.demo else e.fresh(c)
    if s['version']!=e.VERSION or s.get('config_hash',config_id)!=config_id:
        raise ValueError('Configuration changed: start a separate experiment/repository')
    s['config_hash']=config_id
    if args.demo:
        from test_engine import synthetic
        hist={k:synthetic() for k in c['symbols']}
        minute={k:[] for k in c['symbols']};meta={k:dict(ordermin=.00001,costmin=1,lot_decimals=8) for k in c['symbols']}
        q={k:dict(bid=hist[k][-1]['c'],ask=hist[k][-1]['c']*1.0001,volume_eur=1e8) for k in c['symbols']}
        now=hist[c['symbols'][0]][-1]['t']+900
    else:
        hist,minute,meta=market.fetch(c['symbols'])
        e.replay(s,minute,c)
        q=market.quotes(c['symbols']);now=time.time()
        for k in list(s['positions']):
            pos=s['positions'][k]
            if q[k]['bid']<=pos['stop']: e.sell(s,k,q[k]['bid'],c,now,'LIVE_STOP')
            elif q[k]['bid']>=pos['target']: e.sell(s,k,q[k]['bid'],c,now,'LIVE_TARGET')
            elif now-pos['entry_time']>=c['max_hold_seconds']: e.sell(s,k,q[k]['bid'],c,now,'TIME_EXIT')
    # In live mode, store the actual observation time; entries are never backdated.
    ranking=e.step(s,hist,q,meta,c,now)
    r=e.report(s,q,c,now)
    r['ranking']=ranking;r['experimental']=True
    text='# Paper Lab — simulation\n\n'
    text+='Capital après sortie estimée : **'+str(r['equity_after_exit_eur'])+' €**. Rendement : **'+str(r['return_pct'])+' %**.\n\n'
    text+='```json\n'+json.dumps(r,ensure_ascii=False,indent=2)+'\n```\n'
    text+='\nScores de classement, pas probabilités de succès. Aucun ordre réel. Coûts simulés.\n'
    if args.demo:
        print(text);return
    # portfolio.json is authoritative. Report regeneration is safe if interruption occurs.
    atomic(path,json.dumps(s,ensure_ascii=False,separators=(',',':')))
    atomic('state/report.json',json.dumps(r,ensure_ascii=False,indent=2))
    atomic('state/REPORT.md',text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    print(text)

if __name__=='__main__':main()
