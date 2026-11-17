#!/usr/bin/env python3
"""
Engine riset strategi tambahan (shadow/backtest), terpisah dari EA live.

Strategi:
- meanrev : mean reversion RSI/Bollinger + filter tren H1
- breakout: breakout range Asia pada sesi London
- pattern_confluence: lapisan konfirmasi PATTERN + forecast arah
- ema_cross: baseline pembanding

Tidak mengirim order dan tidak mengubah EA/PULLBACK.
"""
from __future__ import annotations

import csv
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "patterns.db"
RESULTS = ROOT / "backtest" / "results"
PERIOD = 300
SPREAD_PRICE = 0.30


@dataclass
class Candle:
    t: int
    o: float
    h: float
    l: float
    c: float
    tv: int = 0
    spread: int = 0


@dataclass
class Trade:
    side: str
    entry_t: int
    exit_t: int
    entry: float
    exit: float
    sl: float
    tp: float
    bars: int
    pnl: float
    reason: str


def load_candles(limit: int = 2_000_000, db_path: str | Path | None = None) -> list[Candle]:
    """Baca candle read-only. Backtest wajib memberi salinan DB sendiri."""
    path = Path(db_path or DB_PATH).resolve()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT t,o,h,l,c,tv,spread FROM candles_m5 ORDER BY t DESC LIMIT ?",
        (limit,)).fetchall()
    con.close()
    return [Candle(*r) for r in reversed(rows)]


def ema_list(vals: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < period:
        return out
    k = 2.0 / (period + 1.0)
    e = sum(vals[:period]) / period
    out[period - 1] = e
    for i in range(period, len(vals)):
        e = vals[i] * k + e * (1.0 - k)
        out[i] = e
    return out


def ema_last(vals: list[float], period: int) -> float | None:
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = v * k + e * (1.0 - k)
    return e


def rsi_list(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gain += max(d, 0.0)
        loss += max(-d, 0.0)
    ag, al = gain / period, loss / period
    out[period] = 100.0 * ag / (ag + al) if ag + al else 50.0
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 * ag / (ag + al) if ag + al else 50.0
    return out


def atr_list(bars: list[Candle], period: int = 14) -> list[float | None]:
    n = len(bars)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(bars[i].h - bars[i].l,
                     abs(bars[i].h - bars[i - 1].c),
                     abs(bars[i].l - bars[i - 1].c))
    out[period] = sum(trs[1:period + 1]) / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def sma_std_list(closes: list[float], period: int = 20):
    n = len(closes)
    sma: list[float | None] = [None] * n
    sd: list[float | None] = [None] * n
    for i in range(period - 1, n):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        sma[i] = m
        sd[i] = math.sqrt(sum((x - m) ** 2 for x in w) / period)
    return sma, sd


def h1_state(candles: list[Candle]) -> dict:
    """EMA50/200 H1 dari candle H1 yang sudah selesai."""
    if len(candles) < 5000:
        return {"dir": 0, "ema50": None, "ema200": None, "close": None}
    bars = candles[-20000:]
    closes = []
    cur = None
    last = None
    for cd in bars:
        hh = cd.t // 3600 * 3600
        if hh != cur:
            if cur is not None and last is not None:
                closes.append(last)
            cur = hh
        last = cd.c
    if len(closes) < 200:
        return {"dir": 0, "ema50": None, "ema200": None, "close": None}
    e50 = ema_last(closes, 50)
    e200 = ema_last(closes, 200)
    if e50 is None or e200 is None:
        return {"dir": 0, "ema50": e50, "ema200": e200, "close": closes[-1]}
    if e50 > e200 and closes[-1] > e200:
        d = 1
    elif e50 < e200 and closes[-1] < e200:
        d = -1
    else:
        d = 0
    return {"dir": d, "ema50": e50, "ema200": e200, "close": closes[-1]}


def _h1_dir_map(candles: list[Candle]) -> dict[int, int]:
    """Map timestamp H1 selesai -> arah -1/0/1 (seluruh riwayat backtest)."""
    bars = candles
    h1t = []
    h1c = []
    cur = None
    last = None
    for cd in bars:
        hh = cd.t // 3600 * 3600
        if hh != cur:
            if cur is not None and last is not None:
                h1t.append(cur)
                h1c.append(last)
            cur = hh
        last = cd.c
    e50 = ema_list(h1c, 50)
    e200 = ema_list(h1c, 200)
    out = {}
    for i in range(len(h1t)):
        if e50[i] is None or e200[i] is None:
            out[h1t[i]] = 0
        elif e50[i] > e200[i] and h1c[i] > e200[i]:
            out[h1t[i]] = 1
        elif e50[i] < e200[i] and h1c[i] < e200[i]:
            out[h1t[i]] = -1
        else:
            out[h1t[i]] = 0
    return out


def _day_start(ts: int) -> int:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def asia_range(candles: list[Candle], day_ts: int) -> dict | None:
    start = day_ts
    end = day_ts + 7 * 3600
    rows = [c for c in candles if start <= c.t < end]
    if len(rows) < 12:
        return None
    return {"start": start, "end": end,
            "high": max(c.h for c in rows),
            "low": min(c.l for c in rows),
            "bars": len(rows)}


def latest_shadow_signals(candles: list[Candle], forecast: dict | None = None) -> list[dict]:
    """Sinyal terbaru untuk halaman monitor (bukan order)."""
    if len(candles) < 300:
        return []
    closes = [c.c for c in candles]
    rsi = rsi_list(closes, 14)
    sma, sd = sma_std_list(closes, 20)
    atr = atr_list(candles, 14)
    last = candles[-1]
    i = len(candles) - 1
    out = []
    h1 = h1_state(candles)
    if rsi[i] is not None and sma[i] is not None and sd[i] is not None and atr[i]:
        up = (rsi[i] < 30.0 or last.c < sma[i] - 2.0 * sd[i]) and h1["dir"] >= 0
        dn = (rsi[i] > 70.0 or last.c > sma[i] + 2.0 * sd[i]) and h1["dir"] <= 0
        if up and not dn:
            sl = last.c - atr[i] * 1.5
            tp = last.c + atr[i] * 2.0
            out.append({"strategy": "meanrev", "side": "BUY", "time": last.t,
                        "entry": round(last.c, 2), "sl": round(sl, 2),
                        "tp": round(tp, 2), "status": "shadow",
                        "reason": "RSI/BB ekstrem + H1 tidak turun",
                        "h1": h1["dir"], "rsi": round(rsi[i], 2)})
        elif dn and not up:
            sl = last.c + atr[i] * 1.5
            tp = last.c - atr[i] * 2.0
            out.append({"strategy": "meanrev", "side": "SELL", "time": last.t,
                        "entry": round(last.c, 2), "sl": round(sl, 2),
                        "tp": round(tp, 2), "status": "shadow",
                        "reason": "RSI/BB ekstrem + H1 tidak naik",
                        "h1": h1["dir"], "rsi": round(rsi[i], 2)})

    # breakout Asia -> London
    day = _day_start(last.t)
    rng = asia_range(candles, day)
    hour = datetime.fromtimestamp(last.t, timezone.utc).hour
    if rng and 7 <= hour < 12 and atr[i]:
        if last.c > rng["high"]:
            sl = last.c - atr[i] * 1.5
            tp = last.c + atr[i] * 2.0
            out.append({"strategy": "breakout", "side": "BUY", "time": last.t,
                        "entry": round(last.c, 2), "sl": round(sl, 2),
                        "tp": round(tp, 2), "status": "shadow",
                        "reason": "breakout high Asia",
                        "range": f'{rng["low"]:.2f}-{rng["high"]:.2f}'})
        elif last.c < rng["low"]:
            sl = last.c + atr[i] * 1.5
            tp = last.c - atr[i] * 2.0
            out.append({"strategy": "breakout", "side": "SELL", "time": last.t,
                        "entry": round(last.c, 2), "sl": round(sl, 2),
                        "tp": round(tp, 2), "status": "shadow",
                        "reason": "breakout low Asia",
                        "range": f'{rng["low"]:.2f}-{rng["high"]:.2f}'})
    return out


# ---------------------------------------------------------------------------
# Backtest sederhana (satu posisi, fixed lot, spread)
# ---------------------------------------------------------------------------
def _close_trade(pos, i, bars, reason, spread, raw_exit=None):
    raw = bars[i].c if raw_exit is None else raw_exit
    if pos["side"] == "BUY":
        exit_p = raw - spread
        pnl = (exit_p - pos["entry"]) * 1.0  # 0.01 lot XAUUSD = 1 oz
    else:
        exit_p = raw + spread
        pnl = (pos["entry"] - exit_p) * 1.0
    return Trade(pos["side"], bars[pos["i"]].t, bars[i].t, pos["entry"], exit_p,
                 pos["sl"], pos["tp"], i - pos["i"], pnl, reason)


def backtest_meanrev(candles: list[Candle]) -> list[Trade]:
    closes = [c.c for c in candles]
    rsi = rsi_list(closes, 14)
    sma, sd = sma_std_list(closes, 20)
    atr = atr_list(candles, 14)
    h1map = _h1_dir_map(candles)
    trades = []
    pos = None
    start = 300
    for i in range(start, len(candles) - 1):
        bar = candles[i]
        if pos:
            sl_hit = (bar.l <= pos["sl"] if pos["side"] == "BUY"
                      else bar.h >= pos["sl"])
            tp_hit = (bar.h >= pos["tp"] if pos["side"] == "BUY"
                      else bar.l <= pos["tp"])
            if sl_hit:
                trades.append(_close_trade(pos, i, candles, "SL", SPREAD_PRICE, pos["sl"]))
                pos = None
            elif tp_hit:
                trades.append(_close_trade(pos, i, candles, "TP", SPREAD_PRICE, pos["tp"]))
                pos = None
            elif i - pos["i"] >= 10:
                trades.append(_close_trade(pos, i, candles, "TIME", SPREAD_PRICE))
                pos = None
        if pos is not None or None in (rsi[i], sma[i], sd[i], atr[i]):
            continue
        hh = bar.t // 3600 * 3600
        h1d = h1map.get(hh - 3600, h1map.get(hh, 0))
        up = (rsi[i] < 30.0 or closes[i] < sma[i] - 2.0 * sd[i]) and h1d >= 0
        dn = (rsi[i] > 70.0 or closes[i] > sma[i] + 2.0 * sd[i]) and h1d <= 0
        if up and not dn:
            entry = candles[i + 1].o + SPREAD_PRICE
            pos = {"side": "BUY", "i": i + 1, "entry": entry,
                   "sl": entry - atr[i] * 1.5, "tp": entry + atr[i] * 2.0}
        elif dn and not up:
            entry = candles[i + 1].o
            pos = {"side": "SELL", "i": i + 1, "entry": entry,
                   "sl": entry + atr[i] * 1.5, "tp": entry - atr[i] * 2.0}
    if pos:
        trades.append(_close_trade(pos, len(candles) - 1, candles, "END", SPREAD_PRICE))
    return trades


def backtest_breakout(candles: list[Candle]) -> list[Trade]:
    atr = atr_list(candles, 14)
    ranges = {}
    for c in candles:
        day = _day_start(c.t)
        hh = datetime.fromtimestamp(c.t, timezone.utc).hour
        if hh >= 7:
            continue
        r = ranges.get(day)
        if r is None:
            r = {"start": day, "end": day + 7 * 3600,
                 "high": c.h, "low": c.l, "bars": 1}
            ranges[day] = r
        else:
            r["high"] = max(r["high"], c.h)
            r["low"] = min(r["low"], c.l)
            r["bars"] += 1
    ranges = {d: r for d, r in ranges.items() if r["bars"] >= 12}
    trades = []
    pos = None
    traded_days = set()
    for i in range(300, len(candles) - 1):
        bar = candles[i]
        if pos:
            sl_hit = (bar.l <= pos["sl"] if pos["side"] == "BUY"
                      else bar.h >= pos["sl"])
            tp_hit = (bar.h >= pos["tp"] if pos["side"] == "BUY"
                      else bar.l <= pos["tp"])
            if sl_hit:
                trades.append(_close_trade(pos, i, candles, "SL", SPREAD_PRICE, pos["sl"]))
                pos = None
            elif tp_hit:
                trades.append(_close_trade(pos, i, candles, "TP", SPREAD_PRICE, pos["tp"]))
                pos = None
            elif i - pos["i"] >= 12:
                trades.append(_close_trade(pos, i, candles, "TIME", SPREAD_PRICE))
                pos = None
        if pos is not None or not atr[i]:
            continue
        day = _day_start(bar.t)
        hour = datetime.fromtimestamp(bar.t, timezone.utc).hour
        r = ranges.get(day)
        if not r or day in traded_days or not (7 <= hour < 12):
            continue
        if bar.c > r["high"]:
            entry = candles[i + 1].o + SPREAD_PRICE
            pos = {"side": "BUY", "i": i + 1, "entry": entry,
                   "sl": entry - atr[i] * 1.5, "tp": entry + atr[i] * 2.0}
            traded_days.add(day)
        elif bar.c < r["low"]:
            entry = candles[i + 1].o
            pos = {"side": "SELL", "i": i + 1, "entry": entry,
                   "sl": entry + atr[i] * 1.5, "tp": entry - atr[i] * 2.0}
            traded_days.add(day)
    if pos:
        trades.append(_close_trade(pos, len(candles) - 1, candles, "END", SPREAD_PRICE))
    return trades


def subset_metrics(trades: list[Trade]) -> dict:
    """Metrik dari subset trade (untuk OOS), tanpa asumsi tahun."""
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    net = sum(t.pnl for t in trades)
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    bal = 10000.0
    peak = bal
    maxdd = 0.0
    for t in trades:
        bal += t.pnl
        peak = max(peak, bal)
        maxdd = max(maxdd, peak - bal)
    return {
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2) if trades else 0,
        "net_pnl": round(net, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "max_drawdown_pct": round(100.0 * maxdd / peak, 2) if peak else 0,
        "return_pct": round(100.0 * net / 10000.0, 2),
    }


def split_metrics(trades: list[Trade], cutoff_ts: int) -> dict:
    """Latih <= cutoff, OOS setelah cutoff. Bukan optimasi parameter."""
    train = [t for t in trades if t.entry_t < cutoff_ts]
    oos = [t for t in trades if t.entry_t >= cutoff_ts]
    return {"cutoff": datetime.fromtimestamp(cutoff_ts, timezone.utc).strftime("%Y-%m-%d"),
            "train": subset_metrics(train), "oos": subset_metrics(oos)}


def summarize(trades: list[Trade], bars: list[Candle], name: str) -> dict:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    net = sum(t.pnl for t in trades)
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    pf = gp / gl if gl > 0 else None
    bal = 10000.0
    peak = bal
    maxdd = 0.0
    for t in trades:
        bal += t.pnl
        peak = max(peak, bal)
        maxdd = max(maxdd, peak - bal)
    per_year = {}
    for t in trades:
        y = datetime.fromtimestamp(t.exit_t, timezone.utc).year
        d = per_year.setdefault(str(y), {"trades": 0, "wins": 0, "pnl": 0.0})
        d["trades"] += 1
        d["wins"] += 1 if t.pnl > 0 else 0
        d["pnl"] += t.pnl
    for d in per_year.values():
        d["win_rate"] = round(100.0 * d["wins"] / d["trades"], 2) if d["trades"] else 0
        d["pnl"] = round(d["pnl"], 2)
    years = (bars[-1].t - bars[0].t) / 86400.0 / 365.25 if bars else 0
    return {
        "strategy": name,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2) if trades else 0,
        "net_pnl": round(net, 2),
        "profit_factor": round(pf, 3) if pf is not None else None,
        "max_drawdown": round(maxdd, 2),
        "max_drawdown_pct": round(100.0 * maxdd / peak, 2) if peak else 0,
        "return_pct": round(100.0 * net / 10000.0, 2),
        "expectancy": round(net / len(trades), 2) if trades else 0,
        "years": round(years, 2),
        "bars": len(bars),
        "start": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if bars else None,
        "end": datetime.fromtimestamp(bars[-1].t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if bars else None,
        "per_year": dict(sorted(per_year.items())),
    }


def write_run(root: Path, name: str, summary: dict, trades: list[Trade],
              stamp: str) -> Path:
    out = root / name / f"run_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["side", "entry_time", "exit_time", "entry", "exit",
                    "sl", "tp", "bars", "pnl", "reason"])
        for t in trades:
            w.writerow([t.side,
                        datetime.fromtimestamp(t.entry_t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        datetime.fromtimestamp(t.exit_t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        f"{t.entry:.2f}", f"{t.exit:.2f}", f"{t.sl:.2f}",
                        f"{t.tp:.2f}", t.bars, f"{t.pnl:.2f}", t.reason])
    return out
