"""Only public Kraken endpoints. Never uses trading credentials."""
import concurrent.futures
import json
import math
import time
import urllib.parse
import urllib.request


def request(path,params):
    url='https://api.kraken.com/0/public/'+path+'?'+urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'paper-lab/1.0'}),timeout=20) as r:
                result=json.load(r)
            if result.get('error'): raise RuntimeError(str(result['error']))
            return result['result']
        except (OSError,ValueError,RuntimeError):
            if attempt==2: raise
            time.sleep(1+attempt)


def ohlc(k,interval):
    result=request('OHLC',{'pair':k,'interval':interval})
    raw=next(v for j,v in result.items() if j!='last')
    bars=[dict(t=int(x[0]),o=float(x[1]),h=float(x[2]),l=float(x[3]),c=float(x[4]),v=float(x[6])) for x in raw[:-1]]
    check(bars,interval*60)
    if not bars or time.time()-bars[-1]['t']-interval*60>max(180,interval*60): raise ValueError('Stale OHLC '+k)
    return bars


def check(bars,seconds):
    prev=None
    for b in bars:
        if not all(math.isfinite(b[x]) for x in ('o','h','l','c','v')) or b['l']<=0 or b['v']<0:
            raise ValueError('Invalid OHLC values')
        if not b['l']<=min(b['o'],b['c'])<=max(b['o'],b['c'])<=b['h']: raise ValueError('Invalid OHLC range')
        if prev is not None and b['t']-prev!=seconds: raise ValueError('Missing/duplicate OHLC bar')
        prev=b['t']


def one(k):
    result=request('AssetPairs',{'pair':k});p=next(iter(result.values()))
    if p.get('status','online')!='online': raise ValueError('Pair not online: '+k)
    meta=dict(ordermin=float(p['ordermin']),costmin=float(p.get('costmin',0)),lot_decimals=int(p['lot_decimals']))
    return k,ohlc(k,15),ohlc(k,1),meta


def quotes(symbols):
    pairs=request('AssetPairs',{'pair':','.join(symbols)})
    canonical={}
    for k in symbols:
        match=[j for j,p in pairs.items() if p.get('altname')==k or j==k]
        if len(match)!=1: raise ValueError('Ambiguous pair mapping: '+k)
        canonical[k]=match[0]
    result=request('Ticker',{'pair':','.join(symbols)})
    mapping={}
    for k in symbols:
        x=result.get(canonical[k])
        if x is None: raise ValueError('Missing ticker: '+k)
        bid,ask=float(x['b'][0]),float(x['a'][0])
        volume=float(x['v'][1])*float(x['p'][1])
        if not (math.isfinite(bid) and math.isfinite(ask) and 0<bid<=ask and math.isfinite(volume) and volume>=0): raise ValueError('Invalid ticker')
        mapping[k]=dict(bid=bid,ask=ask,volume_eur=volume)
    return mapping


def fetch(symbols):
    hist={};minutes={};meta={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for k,h,m,p in pool.map(one,symbols): hist[k]=h;minutes[k]=m;meta[k]=p
    # All indicators refer to the same most recent closed interval.
    end=min(rows[-1]['t'] for rows in hist.values())
    hist={k:[b for b in rows if b['t']<=end] for k,rows in hist.items()}
    return hist,minutes,meta
