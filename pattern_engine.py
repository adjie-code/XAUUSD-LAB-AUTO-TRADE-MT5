#!/usr/bin/env python3
"""
Fase 4 + 5 — Mesin pencarian pola & estimasi candle berikutnya.

Fase 4 — pencarian pola:
  1. Ambil 10 candle M5 terakhir yang SUDAH SELESAI sebagai pola acuan.
  2. DTW murni (stdlib) membandingkan pola close vs semua window 10-candle riwayat.
  3. Filter kemiripan >= threshold (default 70%), urut: sesi Asia dulu (ROADMAP:
     "prioritas sesi Asia" — bukan eksklusi), lalu kemiripan tertinggi, top N.

Fase 5 — estimasi:
  Untuk setiap pola terbaik, ambil 10 candle SETELAH pola itu terjadi sebagai
  sampel statistik. Estimasi 10 candle berikutnya = rata-rata semua sampel
  per index (bukan random dummy). Kalau tidak ada sampel, index kosong.

Mode riset-saja: modul ini pasif, tidak menyentuh MT5/web apapun.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from statistics import mean, median

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "patterns.db")

ACTUAL_LEN = 10          # pola acuan 10 candle M5 (roadmap)
FUTURE_LEN = 10          # estimasi 10 candle berikutnya (roadmap)
SUFFICIENT_BARS = 20_000  # di bawah ini: data historis dianggap terbatas
PERIOD_SEC = 300         # 1 candle M5 = 300 detik; window hanya valid bila candle
                         # benar-benar berurutan (tanpa gap) — data sparse/akhir
                         # pekan tidak boleh tercampur jadi satu pola.


# ---- mesin ------------------------------------------------------------------
def _dtw_cost(a: list[float], b: list[float], band: int) -> float:
    """DTW dengan batas band Sakoe-Chiba (opsi percepatan murni Python)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("inf")
    dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        j_min = max(1, i - band)
        j_max = min(m, i + band)
        for j in range(j_min, j_max + 1):
            cost = abs(a[i - 1] - b[j - 1])
            dp[i][j] = cost + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m]


def similarity_pct(seq1, seq2, band: int = 3) -> float:
    """Kemiripan % dua seri, sesuai prinsip DTW roadmap (0-100, 100 = identik)."""
    n_len, m_len = len(seq1), len(seq2)
    if n_len == 0 or m_len == 0:
        return 0.0
    dist = _dtw_cost(seq1, seq2, band)
    norm = dist / (sum(abs(x) for x in seq1) + sum(abs(x) for x in seq2) or 1.0)
    return round(min(max(100.0 - norm * 100.0, 0.0), 100.0), 2)


def is_asia_session(ts_epoch: int) -> bool:
    """Sesi Asia ~01:00-09:00 UTC (roadmap: prioritas sesi Asia)."""
    return 1 <= datetime.fromtimestamp(ts_epoch, tz=timezone.utc).hour <= 9


def session_name(ts_epoch: int) -> str:
    h = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).hour
    if 1 <= h <= 9:
        return "Asia"
    if 7 <= h < 16:
        return "Eropa"
    if 16 <= h < 23:
        return "AS"
    return "Lain"


# ---------------------------------------------------------------------------
# Model arah (forecast) — mean reversion + filter tren
# ---------------------------------------------------------------------------
def _ema_last(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def _rsi_last(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gain += max(d, 0.0)
        loss += max(-d, 0.0)
    ag, al = gain / period, loss / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    return 100.0 * ag / (ag + al) if (ag + al) > 0 else 50.0


def _sma_std_last(values: list[float], period: int = 20) -> tuple[float, float] | None:
    if len(values) < period:
        return None
    w = values[-period:]
    m = sum(w) / period
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / period)
    return m, sd



def _h1_trend(candles: list) -> int:
    """Tren H1 dari EMA50/200; hanya candle H1 yang sudah selesai."""
    if not candles or len(candles) < 3000:
        return 0
    bars = candles[-20000:]
    h1_closes = []
    cur = None
    last = None
    for cd in bars:
        hh = cd.t // 3600 * 3600
        if hh != cur:
            if cur is not None and last is not None:
                h1_closes.append(float(last))
            cur = hh
        last = cd.c
    # current hour is intentionally not appended (belum selesai)
    if len(h1_closes) < 200:
        return 0
    e50 = _ema_last(h1_closes, 50)
    e200 = _ema_last(h1_closes, 200)
    if e50 is None or e200 is None:
        return 0
    close = h1_closes[-1]
    if e50 > e200 and close > e200:
        return 1
    if e50 < e200 and close < e200:
        return -1
    return 0

def direction_forecast(candles: list) -> dict:
    """Arah 10 candle ke depan dari kondisi terakhir (tanpa lookahead)."""
    if not candles or len(candles) < 220:
        return {"dir": 0, "label": "NETRAL", "confidence": "neutral",
                "rule": "data kurang", "rsi": None, "bb": None}
    w = candles[-300:]
    closes = [float(x.c) for x in w]
    close = float(w[-1].c)
    rsi = _rsi_last(closes)
    ss = _sma_std_last(closes, 20)
    ema200 = _ema_last(closes, 200)
    if rsi is None or ss is None or ema200 is None or close <= 0:
        return {"dir": 0, "label": "NETRAL", "confidence": "neutral",
                "rule": "indikator belum siap", "rsi": rsi, "bb": None}
    sma, sd = ss
    bb = (close - sma) / (2.0 * sd) if sd > 0 else 0.0
    hour = datetime.fromtimestamp(w[-1].t, tz=timezone.utc).hour
    up_med = (rsi < 30.0) or (close < sma - 2.0 * sd)
    dn_med = (rsi > 70.0) or (close > sma + 2.0 * sd)
    up_high = (close > ema200) and (rsi < 35.0) and (0 <= hour < 7)
    dn_high = (close < ema200) and (close > sma + 2.0 * sd) and (13 <= hour < 21)
    h1 = _h1_trend(candles)
    if up_med and not dn_med and h1 >= 0:
        high = up_high and h1 == 1
        return {"dir": 1, "label": "NAIK",
                "confidence": "high" if high else "medium",
                "rule": ("uptrend H1 + M5 pullback" if high
                         else "RSI<30 / lower Bollinger + H1 tidak turun"),
                "rsi": round(rsi, 2), "bb": round(bb, 3),
                "ema200": round(ema200, 2), "h1_trend": h1}
    if dn_med and not up_med and h1 <= 0:
        high = dn_high and h1 == -1
        return {"dir": -1, "label": "TURUN",
                "confidence": "high" if high else "medium",
                "rule": ("downtrend H1 + M5 rally" if high
                         else "RSI>70 / upper Bollinger + H1 tidak naik"),
                "rsi": round(rsi, 2), "bb": round(bb, 3),
                "ema200": round(ema200, 2), "h1_trend": h1}
    return {"dir": 0, "label": "NETRAL", "confidence": "neutral",
            "rule": "tidak ada edge", "rsi": round(rsi, 2),
            "bb": round(bb, 3), "ema200": round(ema200, 2)}


def engine(candles: list, cfg: dict) -> dict:
    """
    Kerjakan Fase 4 & 5 bersama. candles: list[Candle] terurut naik.
    Return dict berisi actual, final top_matches, predicted (estimasi),
    dan info kecukupan data — siap disajikan ke UI & dipersist ke DB.

    Panjang pola (jumlah candle) kini dari config: 'candles_per_pattern'
    (default 10, dibatasi 5-60). Pola & estimasi memakai panjang yang sama.
    """
    try:
        N = int(cfg.get("candles_per_pattern", ACTUAL_LEN))
    except (TypeError, ValueError):
        N = ACTUAL_LEN
    N = max(5, min(60, N))
    try:
        threshold = float(cfg.get("similarity_threshold_pct", 70))
    except (TypeError, ValueError):
        threshold = 70.0
    threshold = max(0.0, min(100.0, threshold))
    try:
        top_n = int(cfg.get("top_patterns", 20) or 20)
    except (TypeError, ValueError):
        top_n = 20
    top_n = max(1, min(500, top_n))   # batas aman memori heap (audit 12 Nov)
    prioritize = cfg.get("prioritize_session", "Asia")
    prioritized = (prioritize or "Semua").split(",")
    prioritized = [s.strip() for s in prioritized if s.strip()]
    band = max(2, round(N * 0.3))   # Sakoe-Chiba tumbuh mengikuti panjang window

    closes = [cd.c for cd in candles]
    n = len(closes)
    sufficient = n >= SUFFICIENT_BARS
    actual = candles[-N:]
    actual_close = closes[-N:]
    last_end_t = actual[-1].t

    # ---- prasyarat kontinuitas -------------------------------------------
    # reach[i] = banyak langkah 300s kontinu dari candle i ke depan.
    # Window N candle @shift valid bila reach[shift] >= N-1, dan N candle
    # akibatnya hanya diambil sepanjang tetap berurutan 300s.
    reach = [0] * max(n + 1, 1)
    if n:
        reach[n - 1] = 0
    for i in range(n - 2, -1, -1):
        reach[i] = (reach[i + 1] + 1) if (candles[i + 1].t - candles[i].t == PERIOD_SEC) else 0

    # ---- Fase 4: scan riwayat penuh --------------------------------------
    # Optimasi memori: riwayat bisa jutaan bar; hanya simpan TOP-N di heap,
    # sisanya hanya dihitung (n_matches).
    top = []          # heap of (rank_key, match_dict); rank terburuk di root
    n_matches = 0
    def heap_key(m):
        chosen = m["session"] in prioritized or "Semua" in prioritized
        return (0 if chosen else 1, -m["similarity_pct"], m["pattern_start_t"])

    if n > N:
        for shift in range(n - N):
            if shift >= n - 2 * N + 1:
                continue  # skip window yang overlap dgn pola acuan (self-match)
            if reach[shift] < N - 1:
                continue  # candle tidak benar-benar berurutan (gap/sparse) — skip
            window = closes[shift:shift + N]
            sim = similarity_pct(actual_close, window, band)
            if sim < threshold:
                continue
            n_matches += 1
            pattern_start_t = candles[shift].t
            pred_i = shift + N
            m = {
                "pattern_start_t": pattern_start_t,
                "actual_end_t": last_end_t,
                "predicted_start_t": candles[pred_i].t if pred_i < n else None,
                "pred_i": pred_i if pred_i < n else None,   # indeks langsung (optimasi)
                "similarity_pct": sim,
                "session": session_name(pattern_start_t),
            }
            k = heap_key(m)
            if len(top) < top_n:
                heapq.heappush(top, (k, m))
            elif k < top[0][0]:
                heapq.heapreplace(top, (k, m))

    top_matches = [m for _, m in sorted(top, key=lambda x: x[0])]

    # ---- Fase 5: estimasi statistik dari sampel --------------------------
    # % perubahan relatif ke baseline (close penutupan pola masing-masing),
    # BUKAN harga absolut — pola lintas-era ($1.2xx, $3.3xx, $4.0xx) tidak boleh
    # dicampur levelnya; yang boleh dirata-rata hanya bentuk/arahnnya.
    # Mode (config predict_mode):
    #   "mean"        : rata-rata SEMUA pola tercocok           (metode lama)
    #   "topk_median" : hanya K pola paling mirip -> MEDIAN per
    #                   index + band p10-p90 + prob arah        (metode baru)
    sl_mode = cfg.get("predict_mode", "mean")
    try:
        K = int(cfg.get("predict_top_k", 10))
    except (TypeError, ValueError):
        K = 10
    K = max(3, min(50, K or 10))
    K_used = len(top_matches) if sl_mode == "mean" else min(K, len(top_matches))

    by_index = {i: {"o": [], "h": [], "l": [], "c": []} for i in range(N)}
    for m in top_matches[:K_used]:
        base = m["pred_i"]          # indeks windows setelah pola; None = tak ada sampel
        if base is None or base == 0:
            continue
        anchor_c = candles[base - 1].c   # close candle penutupan pola (= "harga saat itu")
        if not anchor_c:
            continue
        for j in range(N):
            idx = base + j
            if idx >= n:
                break
            if j > 0 and candles[idx].t - candles[idx - 1].t != PERIOD_SEC:
                break  # sampel akibat harus tetap berurutan 300s — berhenti saat gap
            cd = candles[idx]
            by_index[j]["o"].append((cd.o - anchor_c) / anchor_c * 100.0)
            by_index[j]["h"].append((cd.h - anchor_c) / anchor_c * 100.0)
            by_index[j]["l"].append((cd.l - anchor_c) / anchor_c * 100.0)
            by_index[j]["c"].append((cd.c - anchor_c) / anchor_c * 100.0)

    # dianchor ke harga penutupan terakhir DB = "harga sekarang"
    anchor_now = actual[-1].c if actual else None

    def _r(x):
        return None if x is None else round(x, 2)

    def _pctl(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * p
        f = int(k)
        ce = min(f + 1, len(s) - 1)
        return s[f] + (k - f) * (s[ce] - s[f])

    _agg = median if sl_mode == "topk_median" else mean

    predicted, band, direction = [], [], []
    for j in range(N):
        s = by_index[j]
        if not s["c"] or anchor_now is None:
            predicted.append({"t": None, "o": None, "h": None, "l": None, "c": None})
            band.append({"p10": None, "p90": None, "n": 0})
            direction.append({"n": 0, "up": 0, "down": 0})
            continue
        po, ph, pl, pc = (_agg(s["o"]), _agg(s["h"]),
                          _agg(s["l"]), _agg(s["c"]))
        predicted.append({
            "t": None,  # waktu sebenarnya dibilang oleh scheduler, biar engine murni statistik
            "o": _r(anchor_now * (1 + po / 100)),
            "h": _r(max(anchor_now * (1 + ph / 100),
                        anchor_now * (1 + pc / 100))),  # jangan sampai h < c
            "l": _r(min(anchor_now * (1 + pl / 100),
                        anchor_now * (1 + pc / 100))),  # jangan sampai l > c
            "c": _r(anchor_now * (1 + pc / 100)),
        })
        # band 80% (p10-p90) dari distribusi close — hanya meaningful saat median mode
        p10v = anchor_now * (1 + _pctl(s["c"], 0.10) / 100)
        p90v = anchor_now * (1 + _pctl(s["c"], 0.90) / 100)
        band.append({"p10": _r(p10v), "p90": _r(p90v),
                     "n": len(s["c"]) if sl_mode == "topk_median" else 0})
        up = sum(1 for v in s["c"] if v > 0)
        dn = sum(1 for v in s["c"] if v < 0)
        direction.append({"n": len(s["c"]), "up": up, "down": dn})

    return {
        "ok": True,
        "actual": [{"t": cd.t, "o": cd.o, "h": cd.h, "l": cd.l, "c": cd.c} for cd in actual],
        "predicted": predicted,          # N statistik; t diisi scheduler
        "predict_mode": sl_mode,         # "mean" (lama) / "topk_median" (baru)
        "predict_k": K_used,             # berapa pola ikut mewakili statistik
        "band": band,                    # p10/p90 close per index (anchor harga sekarang)
        "direction": direction,          # prob arah per index dari sampel
        "matches": top_matches,          # top matches (info sesi simpan)
        "best_similarity": top_matches[0]["similarity_pct"] if top_matches else None,
        "n_matches": n_matches,
        "forecast": direction_forecast(candles),
        "sufficient_data": sufficient,
        "bars_count": n,
        "last_candle_t": last_end_t,
    }


def persist(conn: sqlite3.Connection, result: dict, run_at: str) -> int:
    """Simpan hasil satu run: engine_runs + pattern_matches + predictions.
    Return run_id. (Fase 4/5 -> DB)"""
    c = conn.cursor()
    c.execute(
        "INSERT INTO engine_runs (run_at, last_candle_t, bars_count, n_matches,"
        " best_similarity, data_sufficient, predict_mode, predict_k,"
        " band_json, direction_json, forecast_dir, forecast_confidence, forecast_rule)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_at, result["last_candle_t"], result["bars_count"], result["n_matches"],
         result["best_similarity"], 1 if result["sufficient_data"] else 0,
         result.get("predict_mode"), result.get("predict_k"),
         json.dumps(result.get("band") or [], separators=(",", ":")),
         json.dumps(result.get("direction") or [], separators=(",", ":")),
         (result.get("forecast") or {}).get("dir", 0),
         (result.get("forecast") or {}).get("confidence", "neutral"),
         (result.get("forecast") or {}).get("rule")),
    )
    run_id = c.lastrowid
    for i, m in enumerate(result["matches"], start=1):
        c.execute(
            "INSERT INTO pattern_matches (pattern_start_t, actual_end_t,"
            " predicted_start_t, similarity_pct, top_pattern_rank, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (m["pattern_start_t"], m["actual_end_t"], m["predicted_start_t"],
             m["similarity_pct"], i, run_at),
        )
    for j, p in enumerate(result["predicted"]):
        if p["t"] is None:
            continue
        c.execute(
            "INSERT OR REPLACE INTO predictions (run_id, idx, o, h, l, c)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, j, p["o"], p["h"], p["l"], p["c"]),
        )
    conn.commit()
    return run_id
