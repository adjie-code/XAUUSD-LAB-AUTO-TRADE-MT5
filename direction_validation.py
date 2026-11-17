#!/usr/bin/env python3
"""Validasi out-of-sample model arah (2024 -> sekarang), tanpa lookahead."""
import json
import math
import sqlite3
from datetime import datetime, timezone

DB = "data/patterns.db"
OUT = "data/direction_validation.json"
START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
H = 10

con = sqlite3.connect(DB)
rows = con.execute("SELECT t,o,h,l,c FROM candles_m5 ORDER BY t").fetchall()
con.close()
t = [int(r[0]) for r in rows]
h = [float(r[2]) for r in rows]
l = [float(r[3]) for r in rows]
c = [float(r[4]) for r in rows]
n = len(c)

def ema(vals, period):
    out = [None] * len(vals)
    if len(vals) < period:
        return out
    k = 2.0 / (period + 1.0)
    e = sum(vals[:period]) / period
    out[period - 1] = e
    for i in range(period, len(vals)):
        e = vals[i] * k + e * (1.0 - k)
        out[i] = e
    return out

tr = [0.0] * n
for i in range(1, n):
    tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
atr = [None] * n
if n > 15:
    atr[14] = sum(tr[1:15]) / 14
    for i in range(15, n):
        atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
rsi = [None] * n
if n > 15:
    ag = al = 0.0
    for i in range(1, 15):
        d = c[i] - c[i - 1]
        ag += max(d, 0.0)
        al += max(-d, 0.0)
    ag /= 14; al /= 14
    rsi[14] = 100.0 * ag / (ag + al) if ag + al else 50.0
    for i in range(15, n):
        d = c[i] - c[i - 1]
        ag = (ag * 13 + max(d, 0.0)) / 14
        al = (al * 13 + max(-d, 0.0)) / 14
        rsi[i] = 100.0 * ag / (ag + al) if ag + al else 50.0
sma = [None] * n
sd = [None] * n
for i in range(19, n):
    w = c[i - 19:i + 1]
    m = sum(w) / 20
    sma[i] = m
    sd[i] = math.sqrt(sum((x - m) ** 2 for x in w) / 20)
e200 = ema(c, 200)

# H1 trend untuk filter rezim (candle H1 selesai)
h1t = []
h1c = []
cur = None
last = None
for i in range(n):
    hh = t[i] // 3600 * 3600
    if hh != cur:
        if cur is not None and last is not None:
            h1t.append(cur)
            h1c.append(last)
        cur = hh
    last = c[i]
h1_ema50 = ema(h1c, 50)
h1_ema200 = ema(h1c, 200)
h1_index = {tt: i for i, tt in enumerate(h1t)}


def h1_dir(ts):
    j = h1_index.get(ts // 3600 * 3600)
    if j is None or j < 1:
        return 0
    j -= 1
    if h1_ema50[j] is None or h1_ema200[j] is None:
        return 0
    if h1_ema50[j] > h1_ema200[j] and h1c[j] > h1_ema200[j]:
        return 1
    if h1_ema50[j] < h1_ema200[j] and h1c[j] < h1_ema200[j]:
        return -1
    return 0


ok = tot = high_ok = high_n = med_ok = med_n = total_bars = 0
for i in range(250, n - H):
    if t[i + H] - t[i] != H * 300 or t[i] < START:
        continue
    if None in (rsi[i], sma[i], sd[i], e200[i]):
        continue
    hour = datetime.fromtimestamp(t[i], tz=timezone.utc).hour
    up_med = (rsi[i] < 30.0) or (c[i] < sma[i] - 2.0 * sd[i])
    dn_med = (rsi[i] > 70.0) or (c[i] > sma[i] + 2.0 * sd[i])
    up_high = (c[i] > e200[i]) and (rsi[i] < 35.0) and (0 <= hour < 7)
    dn_high = (c[i] < e200[i]) and (c[i] > sma[i] + 2.0 * sd[i]) and (13 <= hour < 21)
    if up_med and not dn_med:
        d = 1
    elif dn_med and not up_med:
        d = -1
    else:
        d = 0
    conf = "neutral"
    if d:
        hd = h1_dir(t[i])
        if hd and d != hd:
            d = 0
        elif d == 1:
            conf = "high" if (up_high and hd == 1) else "medium"
        else:
            conf = "high" if (dn_high and hd == -1) else "medium"
    total_bars += 1
    if not d:
        continue
    actual = 1 if c[i + H] > c[i] else (-1 if c[i + H] < c[i] else 0)
    if not actual:
        continue
    tot += 1
    good = (d == actual)
    ok += good
    if conf == "high":
        high_n += 1; high_ok += good
    else:
        med_n += 1; med_ok += good

result = {
    "period": "2024-01-01 -> " + datetime.fromtimestamp(t[-1], tz=timezone.utc).strftime("%Y-%m-%d"),
    "horizon_candles": H,
    "n_signals": tot,
    "n_bars": total_bars,
    "coverage_pct": round(100.0 * tot / total_bars, 2) if total_bars else None,
    "hit_pct": round(100.0 * ok / tot, 2) if tot else None,
    "n_high": high_n,
    "high_hit_pct": round(100.0 * high_ok / high_n, 2) if high_n else None,
    "n_medium": med_n,
    "medium_hit_pct": round(100.0 * med_ok / med_n, 2) if med_n else None,
    "rule": "mean-reversion RSI/Bollinger + trend/session high-confidence",
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(json.dumps(result, indent=2))
