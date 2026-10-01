"""A scheduled, forward-only paper simulation; no exchange orders."""
import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
import paper_trader as p


def technical(s, model):
    trend = s['close_1h'] > s['ema20_1h'] > s['ema50_1h'] and s['close_15m'] > s['ema20_15m']
    action = ('EXIT' if not trend else 'HOLD') if s['position']['btc'] else ('BUY' if trend else 'HOLD')
    return dict(action=action, reason='Filtre EMA20/50 1h et EMA20 15m', stop_pct=3, target_pct=10), {}


def replay(db, state, bars, cfg, now):
    if not state['btc']:
        return
    start = state.get('checked_until', state.get('entry_time', now))
    if not bars or bars[0]['t'] > start + 60:
        state['halted'] = True
        p.event(db, 'DATA_GAP', {'from': start, 'first_available': bars[0]['t'] if bars else None,
                                'reason': 'Stop historique impossible à reconstruire; simulation suspendue'})
        return
    for b in bars:
        # The entry minute is excluded: its OHLC contains prices before entry.
        if b['t'] < start:
            continue
        stop, target = state['stop'], state['target']
        if b['l'] <= stop:
            price, reason = min(b['o'], stop), 'SIMULATED_STOP_1M'
        elif b['h'] >= target:
            price, reason = target, 'SIMULATED_TARGET_1M'
        else:
            state['checked_until'] = b['t'] + 60
            continue
        p.sell(db, state, {'bid': price}, cfg, reason)
        p.event(db, 'FILL_ASSUMPTION', {'bar_utc_epoch': b['t'], 'both_touched': b['l'] <= stop and b['h'] >= target,
                                     'note': 'OHLC last-trade proxy, no historical bid/ask; extra slippage applied'})
        break


def main():
    folder = Path('state'); folder.mkdir(exist_ok=True)
    target = folder / 'paper.sqlite3'; working = folder / 'working.sqlite3'
    if target.exists(): shutil.copyfile(target, working)
    elif working.exists(): working.unlink()
    db = p.connect(str(working)); state = p.load(db)
    mode = os.environ.get('AGENT_MODE', 'technical')
    if mode not in ('technical', 'openai'): raise ValueError('Invalid AGENT_MODE')
    if state.get('agent_mode', mode) != mode:
        raise ValueError('Use a separate state directory/repository to compare another strategy')
    state['agent_mode'] = mode
    cfg = SimpleNamespace(fee=.004, slippage=.0005, min_order_eur=5, model=os.environ.get('OPENAI_MODEL', 'gpt-6-luna'))
    bars = p.candles(1); c15 = p.candles(15); c60 = p.candles(60); q = p.quote()
    now = q['ts']
    if not bars or now - (bars[-1]['t'] + 60) > 180: raise ValueError('Stale 1m data')
    replay(db, state, bars, cfg, now)
    had_position = bool(state['btc'])
    errors = db.execute("SELECT COUNT(*) FROM events WHERE kind='ERROR'").fetchone()[0]
    # Refresh quote after the model responds; execution uses the observed live price.
    def decision(snap, model):
        result = p.decide(snap, model) if mode == 'openai' else technical(snap, model)
        q.update(p.quote())
        return result
    p.tick(db, state, cfg, (c15, c60, q), decision)
    if db.execute("SELECT COUNT(*) FROM events WHERE kind='ERROR'").fetchone()[0] > errors:
        raise RuntimeError('Decision failed; inspect API key/model or market data')
    if state['btc'] and not had_position:
        state['entry_time'] = q['ts']; state['checked_until'] = (int(q['ts']) // 60 + 1) * 60
    p.save(db, state); p.mark(db, state, q, cfg.fee)
    report = p.status(db)
    report['agent_mode'] = mode
    report['equity_after_estimated_exit_eur'] = round(state['eur'] + state['btc'] * q['bid'] * (1-cfg.slippage) * (1-cfg.fee), 4)
    values = [r[0] for r in db.execute('SELECT equity FROM equity ORDER BY ts')]
    peak = 50; drawdown = 0
    for value in values:
        peak = max(peak, value); drawdown = max(drawdown, 100*(peak-value)/peak)
    report['max_observed_drawdown_pct'] = round(drawdown, 3)
    report['data_gap_events'] = db.execute("SELECT COUNT(*) FROM events WHERE kind='DATA_GAP'").fetchone()[0]
    db.close(); os.replace(working, target)
    (folder / 'report.json').write_text(json.dumps(report, indent=2))
    summary = '# Simulation BTC/EUR\n\n```json\n' + json.dumps(report, indent=2) + '\n```\n\nCapital virtuel. Frais API exclus. Stops estimés à partir des OHLC 1m.\n'
    (folder / 'REPORT.md').write_text(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out: out.write(summary)
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
