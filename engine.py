"""Deterministic research engine. No order submission; rules are hypotheses."""
import copy
import datetime as dt
import math
import statistics as stats

VERSION = 'paper-lab-1.0'


def validate(c):
    if not (0 < c['initial_cash'] and 0 <= c['fee'] < .1 and 0 <= c['slippage'] < .1):
        raise ValueError('Invalid capital/costs')
    if not (0 < c['risk_fraction'] <= c['max_total_risk_fraction'] <= .1 and
            0 < c['max_position_fraction'] <= c['max_exposure_fraction'] <= 1 and
            1 <= c['max_positions'] <= 3 and 0 < c['max_drawdown'] <= .5 and
            0 < c['daily_loss_limit'] <= .3 and c['min_net_rr'] >= 1):
        raise ValueError('Invalid risk configuration')
    if len(set(c['symbols'])) != len(c['symbols']) or not c['symbols']:
        raise ValueError('Invalid symbols')


def fresh(c):
    return dict(version=VERSION, cash=c['initial_cash'], positions={}, peak=c['initial_cash'],
                halted=False, halt_reason=None, day=None, day_start=c['initial_cash'],
                last_entry={}, last_signal={}, fees=0., closed_trades=[], benchmark=None,
                equity_history=[], events=[], data_gaps=0, risk_pause_until=0)


def log(s, t, kind, **data):
    s['events'].append(dict(t=t, kind=kind, **data))
    s['events'] = s['events'][-3000:]


def ema(x, n):
    if len(x) < n: raise ValueError('Insufficient EMA history')
    value=sum(x[:n])/n
    for v in x[n:]: value += 2*(v-value)/(n+1)
    return value


def rsi(x, n=14):
    changes=[b-a for a,b in zip(x[-n-1:-1],x[-n:])]
    gain=sum(max(0,d) for d in changes)/n
    loss=sum(max(0,-d) for d in changes)/n
    return 50. if gain==loss==0 else 100. if loss==0 else 100-100/(1+gain/loss)


def atr(bars, n=14):
    pairs=list(zip(bars[-n-1:-1],bars[-n:]))
    return sum(max(b['h']-b['l'],abs(b['h']-a['c']),abs(b['l']-a['c'])) for a,b in pairs)/n


def hourly(bars):
    groups={}
    for b in bars: groups.setdefault(b['t']//3600*3600,[]).append(b)
    out=[]
    for t,rows in sorted(groups.items()):
        if [r['t'] for r in rows] != [t+i*900 for i in range(4)]: continue
        out.append(dict(t=t,o=rows[0]['o'],h=max(r['h'] for r in rows),
                        l=min(r['l'] for r in rows),c=rows[-1]['c'],v=sum(r['v'] for r in rows)))
    return out


def features(bars):
    h=hourly(bars)
    if len(bars)<260 or len(h)<60: return None
    x=[b['c'] for b in bars]; y=[b['c'] for b in h]
    a=atr(bars); price=x[-1]
    mean=stats.mean(x[-20:]); sd=stats.pstdev(x[-20:])
    return dict(price=price, atr=a, atr_pct=a/price, rsi=rsi(x), ema20=ema(x,20),
                h_fast=ema(y,20),h_slow=ema(y,50),h_price=y[-1],
                h_slope=ema(y,20)/ema(y[:-3],20)-1,
                volume_ratio=bars[-1]['v']/max(stats.mean(b['v'] for b in bars[-21:-1]),1e-12),
                momentum=x[-1]/x[-5]-1, breakout=max(b['h'] for b in bars[-21:-1]),
                support=min(b['l'] for b in bars[-21:-1]), mean=mean, z=(price-mean)/sd if sd else 0,
                prev_rsi=rsi(x[:-1]), candle=bars[-1]['t'])


def signal(bars, c):
    f=features(bars)
    if not f: return dict(eligible=False,reason='warmup',score=0)
    trend=f['h_price']>f['h_fast']>f['h_slow'] and f['h_slope']>0
    regime='trend' if trend else 'bear' if f['h_price']<f['h_slow'] and f['h_slope']<0 else 'range'
    # Rules frozen before evaluation; scores are ranks, never probabilities.
    breakout=trend and f['price']>f['breakout'] and f['volume_ratio']>=1.3 and 50<f['rsi']<78
    pullback=trend and f['price']>f['ema20'] and bars[-2]['c']<=ema([b['c'] for b in bars[:-1]],20) and 45<f['rsi']<68
    reversal=c['enable_range_strategy'] and regime=='range' and f['prev_rsi']<32<f['rsi'] and f['z']<-1
    strategy='breakout' if breakout else 'pullback' if pullback else 'range_reversal' if reversal else 'none'
    score=(35 if trend else 15) + min(20,max(0,f['volume_ratio']-1)*20) + (20 if breakout else 15 if pullback or reversal else 0) + min(15,max(0,f['momentum'])*1000) + (10 if 45<f['rsi']<70 else 0)
    stop_fraction=max(.025,min(.08,2.5*f['atr_pct']))
    # 3.5R gross, with a minimum 9% move: costly spot trades need room.
    target_fraction=max(.09,3.5*stop_fraction)
    return dict(eligible=strategy!='none' and score>=c['min_score'] and f['atr_pct']<.04,
                reason=strategy if strategy!='none' else 'No validated trigger',
                strategy=strategy,regime=regime,score=round(score,2),
                stop_fraction=stop_fraction,target_fraction=target_fraction,**f)


def correlation(a,b):
    da={v['t']:v['c'] for v in a[-100:]}; db={v['t']:v['c'] for v in b[-100:]}
    times=sorted(set(da)&set(db))
    if len(times)<40: return 1.  # missing evidence → avoid extra correlated risk
    ra=[math.log(da[y]/da[x]) for x,y in zip(times,times[1:]) if y-x==900]
    rb=[math.log(db[y]/db[x]) for x,y in zip(times,times[1:]) if y-x==900]
    if len(ra)<30: return 1.
    ma,mb=stats.mean(ra),stats.mean(rb)
    va=sum((v-ma)**2 for v in ra); vb=sum((v-mb)**2 for v in rb)
    if va*vb==0: return 1.
    return sum((x-ma)*(y-mb) for x,y in zip(ra,rb))/math.sqrt(va*vb)


def liquidation(s, quotes, c):
    return s['cash'] + sum(p['qty']*quotes[k]['bid']*(1-c['slippage'])*(1-c['fee']) for k,p in s['positions'].items())


def open_risk(s,c):
    return sum(max(0,p['cost']-p['qty']*p['stop']*(1-c['slippage'])*(1-c['fee'])) for p in s['positions'].values())


def guard(s,quotes,c,t):
    equity=liquidation(s,quotes,c); day=dt.datetime.fromtimestamp(t,dt.timezone.utc).date().isoformat()
    if s['day']!=day: s['day']=day;s['day_start']=equity
    s['peak']=max(s['peak'],equity)
    if equity<=s['peak']*(1-c['max_drawdown']):
        s['halted']=True;s['halt_reason']='max_drawdown'
    if equity<=s['day_start']*(1-c['daily_loss_limit']):
        next_day=(t//86400+1)*86400
        s['risk_pause_until']=max(s['risk_pause_until'],next_day)
    return equity


def sell(s,k,bid,c,t,reason):
    p=s['positions'].pop(k); price=bid*(1-c['slippage'])
    gross=p['qty']*price; fee=gross*c['fee']; net=gross-fee
    s['cash']+=net;s['fees']+=fee
    trade=dict(symbol=k,entry_time=p['entry_time'],exit_time=t,reason=reason,
               strategy=p['strategy'],entry=p['entry'],exit=price,cost=p['cost'],
               net_pnl=net-p['cost'],initial_risk=p['initial_risk'])
    s['closed_trades'].append(trade)
    log(s,t,'SELL',**trade)
    if len(s['closed_trades'])>=3 and all(x['net_pnl']<0 for x in s['closed_trades'][-3:]):
        s['risk_pause_until']=max(s['risk_pause_until'],t+21600)


def process_bar(s,k,b,c,seconds):
    p=s['positions'].get(k)
    if not p or b['t']<p['checked_until']: return
    stop,target=p['stop'],p['target']
    if b['l']<=stop:
        sell(s,k,min(b['o'],stop),c,b['t']+seconds,'STOP_OHLC');return
    if b['h']>=target:
        sell(s,k,target,c,b['t']+seconds,'TARGET_OHLC');return
    if b['t']+seconds-p['entry_time']>=c['max_hold_seconds']:
        sell(s,k,b['c'],c,b['t']+seconds,'TIME_EXIT');return
    # Trail only after the bar closes, never on this same bar's high.
    p['high_close']=max(p['high_close'],b['c'])
    if b['c']>=p['entry']+p['initial_distance']:
        breakeven=p['cost']/p['qty']/((1-c['slippage'])*(1-c['fee']))
        p['stop']=max(p['stop'],breakeven,p['high_close']-2.5*p['atr'])
    p['checked_until']=b['t']+seconds


def replay(s, series, c, seconds=60):
    sequence=[]
    for k,p in list(s['positions'].items()):
        rows=series[k]; start=p['checked_until']
        relevant=[b for b in rows if b['t']>=start]
        if rows and rows[0]['t']>start:
            s['halted']=True;s['halt_reason']='historical_data_gap';s['data_gaps']+=1
            log(s,rows[0]['t'],'DATA_GAP',symbol=k,expected=start,available=rows[0]['t'])
        expected=start
        for b in relevant:
            if b['t']>expected:
                s['halted']=True;s['halt_reason']='historical_data_gap';s['data_gaps']+=1
                log(s,b['t'],'DATA_GAP',symbol=k,expected=expected,available=b['t'])
            sequence.append((b['t'],k,b));expected=b['t']+seconds
    for _,k,b in sorted(sequence): process_bar(s,k,b,c,seconds)


def enter(s,k,sig,q,meta,hist,c,t):
    if k in s['positions']: return 'already_open'
    if s['halted'] or t<s['risk_pause_until']: return 'risk_paused'
    if len(s['positions'])>=c['max_positions']: return 'position_limit'
    if t-s['last_entry'].get(k,-1e12)<c['cooldown_seconds']: return 'cooldown'
    if any(correlation(hist[k],hist[j])>c['correlation_threshold'] for j in s['positions']): return 'correlated'
    if not sig['eligible']: return sig['reason']
    if q['ask']/q['bid']-1>c['max_spread']: return 'spread'
    if q['volume_eur']<c['min_quote_volume_eur']: return 'liquidity'
    equity=liquidation(s,{j:hist['_quotes'][j] for j in s['positions']},c)
    entry=q['ask']*(1+c['slippage']);stop=entry*(1-sig['stop_fraction']);target=entry*(1+sig['target_fraction'])
    cost_unit=entry*(1+c['fee'])
    loss_unit=cost_unit-stop*(1-c['slippage'])*(1-c['fee'])
    reward_unit=target*(1-c['slippage'])*(1-c['fee'])-cost_unit
    if reward_unit/loss_unit<c['min_net_rr']: return 'net_rr'
    risk_budget=min(equity*c['risk_fraction'],equity*c['max_total_risk_fraction']-open_risk(s,c))
    exposure=sum(p['qty']*hist['_quotes'][j]['bid'] for j,p in s['positions'].items())
    budget=min(s['cash']-2,equity*c['max_position_fraction'],equity*c['max_exposure_fraction']-exposure)
    qty=min(budget/cost_unit,risk_budget/loss_unit)
    if qty<=0: return 'budget'
    scale=10**meta['lot_decimals'];qty=math.floor(qty*scale)/scale
    if qty<meta['ordermin'] or qty*entry<max(c['min_notional'],meta['costmin']): return 'exchange_minimum'
    fee=qty*entry*c['fee'];cost=qty*cost_unit
    s['cash']-=cost;s['fees']+=fee;s['last_entry'][k]=t
    s['positions'][k]=dict(qty=qty,entry=entry,cost=cost,stop=stop,target=target,atr=sig['atr'],
                          initial_distance=entry-stop,initial_risk=qty*loss_unit,strategy=sig['strategy'],
                          entry_time=t,checked_until=(int(t)//60+1)*60,high_close=entry)
    log(s,t,'BUY',symbol=k,qty=qty,entry=entry,cost=cost,fee=fee,stop=stop,target=target,
        initial_risk=qty*loss_unit,score=sig['score'],strategy=sig['strategy'])
    return 'entered'


def step(s,hist,quotes,meta,c,t):
    guard(s,quotes,c,t)
    hist=dict(hist);hist['_quotes']=quotes
    ranked=[]
    for k in c['symbols']:
        sig=signal(hist[k],c);ranked.append((k,sig))
        if k in s['positions'] and sig.get('regime')=='bear': sell(s,k,quotes[k]['bid'],c,t,'REGIME_EXIT')
    ranked.sort(key=lambda item:item[1]['score'],reverse=True)
    results=[]
    for k,sig in ranked:
        candle=hist[k][-1]['t']
        if s['last_signal'].get(k)==candle:
            results.append(dict(symbol=k,result='same_candle',**sig));continue
        reason=enter(s,k,sig,quotes[k],meta[k],hist,c,t)
        s['last_signal'][k]=candle
        results.append(dict(symbol=k,result=reason,**sig))
        log(s,t,'SIGNAL',symbol=k,result=reason,signal=sig)
    guard(s,quotes,c,t)
    return results


def report(s,quotes,c,t):
    equity=liquidation(s,quotes,c)
    s['peak']=max(s['peak'],equity)
    s['equity_history'].append(dict(t=t,equity=equity))
    peak=c['initial_cash'];dd=0
    for row in s['equity_history']:
        peak=max(peak,row['equity']);dd=max(dd,1-row['equity']/peak)
    closed=s['closed_trades'];wins=sum(x['net_pnl']>0 for x in closed)
    profit=sum(max(0,x['net_pnl']) for x in closed);loss=-sum(min(0,x['net_pnl']) for x in closed)
    btc=quotes.get('XBTEUR')
    if btc and s['benchmark'] is None: s['benchmark']=c['initial_cash']/(btc['ask']*(1+c['slippage'])*(1+c['fee']))
    bench=s['benchmark']*btc['bid']*(1-c['slippage'])*(1-c['fee']) if btc else None
    return dict(version=VERSION,asof_utc=dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),
                equity_after_exit_eur=round(equity,4),return_pct=round(100*(equity/c['initial_cash']-1),3),
                cash_eur=round(s['cash'],4),positions=copy.deepcopy(s['positions']),
                closed_trades=len(closed),win_rate_pct=round(100*wins/len(closed),2) if closed else None,
                profit_factor=round(profit/loss,3) if loss else None,
                realized_pnl_eur=round(sum(x['net_pnl'] for x in closed),4),fees_eur=round(s['fees'],4),
                max_observed_drawdown_pct=round(dd*100,3),btc_buy_hold_after_exit_eur=round(bench,4) if bench else None,
                halted=s['halted'],halt_reason=s['halt_reason'],pause_until_epoch=s['risk_pause_until'],
                data_gaps=s['data_gaps'],open_risk_eur=round(open_risk(s,c),4))
