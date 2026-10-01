#!/usr/bin/env python3
"""BTC/EUR live-forward paper trading. Public market data; no exchange credentials."""
import argparse
import csv
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc
PAIR = "XBTEUR"
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["BUY", "HOLD", "EXIT"]},
        "reason": {"type": "string"},
        "stop_pct": {"type": ["number", "null"]},
        "target_pct": {"type": ["number", "null"]},
    },
    "required": ["action", "reason", "stop_pct", "target_pct"],
}
SYSTEM = """Tu es un agent expérimental de paper trading BTC/EUR au comptant.
Les seules données actuelles sont le JSON fourni. Les bougies 15m et 1h sont clôturées.
Décide BUY, HOLD ou EXIT. Une seule position est possible. HOLD si aucune
opportunité solide. BUY uniquement si tendance 1h et signal 15m concordent,
avec stop_pct entre 1 et 8 et target_pct entre 2 et 20, et objectif/risque >= 2
avant frais. EXIT seulement si la thèse est invalidée avec une position ouverte.
Ne prétends pas avoir des nouvelles ou données absentes. Les raisons doivent
mentionner les signaux observés et le scénario d'invalidation. Tu ne passes
aucun ordre; un programme indépendant contrôle et simule l'exécution."""


def utc_now():
    return dt.datetime.now(UTC).isoformat(timespec="seconds")


def get_json(url, headers=None, body=None, timeout=20):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def kraken(path, params):
    url = "https://api.kraken.com/0/public/" + path + "?" + urllib.parse.urlencode(params)
    obj = get_json(url)
    if obj.get("error"):
        raise RuntimeError(f"Kraken {path}: {obj['error']}")
    return next(v for k, v in obj["result"].items() if k != "last")


def candles(interval):
    raw = kraken("OHLC", {"pair": PAIR, "interval": interval})
    # Kraken's final candle is always the current, uncommitted interval.
    return [{"t": int(x[0]), "o": float(x[1]), "h": float(x[2]),
             "l": float(x[3]), "c": float(x[4]), "v": float(x[6])}
            for x in raw[:-1]]


def quote():
    x = kraken("Ticker", {"pair": PAIR})
    bid, ask = float(x["b"][0]), float(x["a"][0])
    if not (0 < bid <= ask):
        raise ValueError("invalid bid/ask")
    return {"bid": bid, "ask": ask, "ts": time.time()}


def ema(values, period):
    value = sum(values[:period]) / period
    for price in values[period:]:
        value += (price - value) * 2 / (period + 1)
    return value


def snapshot(c15, c60, q, state):
    if len(c15) < 52 or len(c60) < 52:
        raise ValueError("insufficient history")
    if time.time() - (c15[-1]["t"] + 900) > 900 or time.time() - q["ts"] > 20:
        raise ValueError("stale market data")
    p15 = [x["c"] for x in c15]
    p60 = [x["c"] for x in c60]
    return {
        "asof_utc": utc_now(), "last_closed_15m": c15[-1]["t"],
        "bid": q["bid"], "ask": q["ask"],
        "spread_pct": 100 * (q["ask"] - q["bid"]) / q["ask"],
        "close_15m": p15[-1], "ema20_15m": ema(p15, 20),
        "ema50_15m": ema(p15, 50), "close_1h": p60[-1],
        "ema20_1h": ema(p60, 20), "ema50_1h": ema(p60, 50),
        "last_15m_candles": c15[-8:],
        "position": {"btc": state["btc"], "entry": state["entry"],
                     "stop": state["stop"], "target": state["target"]},
        "equity_eur": state["eur"] + state["btc"] * q["bid"],
    }


def decide(s, model):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing; use --demo only for a smoke test")
    payload = {
        "model": model, "instructions": SYSTEM,
        "input": json.dumps(s, separators=(",", ":")),
        "max_output_tokens": 500,
        "text": {"format": {"type": "json_schema", "name": "paper_decision",
                            "strict": True, "schema": SCHEMA}},
    }
    response = get_json("https://api.openai.com/v1/responses",
                        {"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"},
                        json.dumps(payload).encode(), timeout=45)
    if response.get("status") != "completed":
        raise RuntimeError("OpenAI response incomplete")
    parts = [c["text"] for item in response.get("output", [])
             if item.get("type") == "message" for c in item.get("content", [])
             if c.get("type") == "output_text"]
    if len(parts) != 1:
        raise RuntimeError("OpenAI gave no unique decision")
    decision = json.loads(parts[0])
    if set(decision) != set(SCHEMA["required"]) or decision["action"] not in ("BUY", "HOLD", "EXIT"):
        raise ValueError("invalid model decision")
    return decision, response.get("usage", {})


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS equity (ts TEXT PRIMARY KEY, equity REAL, eur REAL, btc REAL, bid REAL)")
    db.commit()
    return db


def event(db, kind, payload):
    db.execute("INSERT INTO events(ts, kind, payload) VALUES(?,?,?)",
               (utc_now(), kind, json.dumps(payload, ensure_ascii=False)))
    db.commit()


def save(db, state):
    db.execute("INSERT INTO state(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
               (json.dumps(state),))
    db.commit()


def load(db):
    row = db.execute("SELECT data FROM state WHERE id=1").fetchone()
    if row:
        return json.loads(row["data"])
    s = {"eur": 50.0, "btc": 0.0, "entry": None, "stop": None,
         "target": None, "last_candle": None, "start_day": None,
         "day_equity": 50.0, "halted": False, "fees_eur": 0.0,
         "api_input_tokens": 0, "api_output_tokens": 0,
         "benchmark_btc": None, "benchmark_fee": None}
    save(db, s)
    return s


def mark(db, state, q, fee):
    if state.get("benchmark_btc") is None:
        state["benchmark_btc"] = 50.0 / (q["ask"] * (1 + fee))
        state["benchmark_fee"] = fee
        save(db, state)
    db.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?)",
               (utc_now(), state["eur"] + state["btc"] * q["bid"],
                state["eur"], state["btc"], q["bid"]))
    db.commit()


def sell(db, s, q, cfg, reason):
    if s["btc"] <= 0:
        return
    price = q["bid"] * (1 - cfg.slippage)
    proceeds = s["btc"] * price
    fee = proceeds * cfg.fee
    event(db, "SELL", {"reason": reason, "btc": s["btc"], "price": price,
                       "gross_eur": proceeds, "fee_eur": fee, "bid": q["bid"]})
    s["eur"] += proceeds - fee
    s["fees_eur"] += fee
    s.update(btc=0.0, entry=None, stop=None, target=None)
    save(db, s)


def buy(db, s, q, cfg, d):
    try:
        stop_pct, target_pct = float(d["stop_pct"]), float(d["target_pct"])
    except (ValueError, TypeError):
        return "invalid stop or target"
    price = q["ask"] * (1 + cfg.slippage)
    spread_pct = 100 * (q["ask"] - q["bid"]) / q["ask"]
    estimated_cost_pct = 100 * (2 * cfg.fee + 2 * cfg.slippage) + spread_pct
    if not (1 <= stop_pct <= 8 and 2 <= target_pct <= 20):
        return "stop/target bounds"
    if (target_pct - estimated_cost_pct) / (stop_pct + estimated_cost_pct) < 2:
        return "net reward/risk under 2"
    if spread_pct > 0.20 or estimated_cost_pct >= stop_pct / 2:
        return "spread/cost too high"
    gross = min(20.0, (s["eur"] - 2.0) / (1 + cfg.fee),
                1.0 * 100 / stop_pct)
    if gross < cfg.min_order_eur:
        return "minimum order or insufficient balance"
    btc = gross / price
    fee = gross * cfg.fee
    s["eur"] -= gross + fee
    s["btc"] = btc
    s["entry"] = price
    s["stop"] = price * (1 - stop_pct / 100)
    s["target"] = price * (1 + target_pct / 100)
    s["fees_eur"] += fee
    event(db, "BUY", {"btc": btc, "price": price, "gross_eur": gross,
                      "fee_eur": fee, "ask": q["ask"], "stop": s["stop"],
                      "target": s["target"]})
    save(db, s)
    return None


def tick(db, s, cfg, market=None, decision_fn=decide):
    c15, c60, q = market if market else (candles(15), candles(60), quote())
    if s["btc"] and q["bid"] <= s["stop"]:
        sell(db, s, q, cfg, "STOP")
    elif s["btc"] and q["bid"] >= s["target"]:
        sell(db, s, q, cfg, "TARGET")
    today = dt.datetime.now(UTC).date().isoformat()
    if s["start_day"] != today:
        s["start_day"] = today
        s["day_equity"] = s["eur"] + s["btc"] * q["bid"]
    equity = s["eur"] + s["btc"] * q["bid"]
    if not s["halted"] and (equity <= 40 or equity <= s["day_equity"] - 3):
        s["halted"] = True
        event(db, "HALT", {"equity": equity, "reason": "loss limit"})
    mark(db, s, q, cfg.fee)
    current = c15[-1]["t"]
    if s["last_candle"] == current or s["halted"]:
        save(db, s)
        return
    try:
        snap = snapshot(c15, c60, q, s)
        d, usage = decision_fn(snap, cfg.model)
    except Exception as exc:
        event(db, "ERROR", {"stage": "decision", "error": str(exc)})
        return  # retry on next poll; no candle marked processed
    s["api_input_tokens"] += usage.get("input_tokens", 0)
    s["api_output_tokens"] += usage.get("output_tokens", 0)
    reason = None
    if d["action"] == "BUY":
        if s["btc"]:
            reason = "already in position"
        elif not (snap["close_1h"] > snap["ema20_1h"] > snap["ema50_1h"]
                  and snap["close_15m"] > snap["ema20_15m"]):
            reason = "trend filter rejected"
        else:
            reason = buy(db, s, q, cfg, d)
    elif d["action"] == "EXIT":
        if s["btc"]:
            sell(db, s, q, cfg, "AGENT_EXIT")
        else:
            reason = "no position"
    event(db, "DECISION", {"candle": current, "decision": d,
                           "rejected": reason, "snapshot": snap, "usage": usage})
    s["last_candle"] = current
    save(db, s)


def status(db):
    s = load(db)
    row = db.execute("SELECT * FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
    equity = row["equity"] if row else 50.0
    benchmark = ((s.get("benchmark_btc") or 0) * row["bid"] *
                 (1 - (s.get("benchmark_fee") or 0))) if row else 50.0
    trades = db.execute("SELECT COUNT(*) FROM events WHERE kind='BUY'").fetchone()[0]
    return {"equity_eur": round(equity, 4), "return_pct": round((equity / 50 - 1) * 100, 3),
            "eur": round(s["eur"], 4), "btc": s["btc"], "trades": trades,
            "fees_eur": round(s["fees_eur"], 4),
            "btc_buy_hold_eur": round(benchmark, 4),
            "btc_buy_hold_return_pct": round((benchmark / 50 - 1) * 100, 3),
            "halted": s["halted"],
            "model_tokens": {"input": s["api_input_tokens"],
                             "output": s["api_output_tokens"]},
            "last_mark_utc": row["ts"] if row else None,
            "last_decision_candle": s["last_candle"]}


def demo_market():
    now = int(time.time()) // 900 * 900
    c15 = [{"t": now - 900 * (100 - i), "o": 100000 + i * 10,
            "h": 100020 + i * 10, "l": 99980 + i * 10,
            "c": 100000 + i * 10, "v": 1} for i in range(100)]
    c60 = [{"t": now - 3600 * (100 - i), "o": 100000 + i * 10,
            "h": 100020 + i * 10, "l": 99980 + i * 10,
            "c": 100000 + i * 10, "v": 1} for i in range(100)]
    return c15, c60, {"bid": 101000.0, "ask": 101010.0, "ts": time.time()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["run", "once", "status", "export", "demo"])
    p.add_argument("--db", default="paper_trading.sqlite3")
    p.add_argument("--model", default="gpt-6-luna")
    p.add_argument("--fee", type=float, default=0.004,
                   help="fee fraction per side, default 0.004 (0.40%%)")
    p.add_argument("--slippage", type=float, default=0.0005,
                   help="extra slippage fraction per side")
    p.add_argument("--min-order-eur", type=float, default=5.0)
    p.add_argument("--poll-seconds", type=int, default=60)
    cfg = p.parse_args()
    if not (0 <= cfg.fee < .1 and 0 <= cfg.slippage < .1 and
            1 <= cfg.min_order_eur <= 50 and cfg.poll_seconds >= 10):
        p.error("invalid costs/minimum/poll interval")
    db = connect(cfg.db)
    if cfg.command == "status":
        print(json.dumps(status(db), indent=2))
    elif cfg.command == "export":
        for table in ("events", "equity"):
            path = Path(cfg.db).with_name(table + ".csv")
            with path.open("w", newline="") as f:
                rows = db.execute("SELECT * FROM " + table + " ORDER BY 1")
                writer = csv.writer(f)
                writer.writerow([x[0] for x in rows.description])
                writer.writerows(rows)
            print(path)
    elif cfg.command == "demo":
        # Separate in-memory state: demonstrates a buy and stop; no market/API calls.
        test_db = connect(":memory:")
        state = load(test_db)
        sample = demo_market()
        tick(test_db, state, cfg, sample,
             lambda s, m: ({"action": "BUY", "reason": "synthetic example",
                            "stop_pct": 2.0, "target_pct": 8.0}, {}))
        sample[2]["bid"] = state["stop"] * .995
        tick(test_db, state, cfg, sample, lambda s, m: ({"action": "HOLD", "reason": "demo",
                                                         "stop_pct": None, "target_pct": None}, {}))
        print(json.dumps(status(test_db), indent=2))
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            p.error("OPENAI_API_KEY required for once/run; demo works without it")
        while True:
            try:
                tick(db, load(db), cfg)
                print(json.dumps(status(db)), flush=True)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                event(db, "ERROR", {"stage": "market", "error": str(exc)})
                print(f"{utc_now()} market error: {exc}", file=sys.stderr, flush=True)
            if cfg.command == "once":
                break
            time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
