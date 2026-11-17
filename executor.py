#!/usr/bin/env python3
"""
XAUUSD Pattern Dashboard - Eksekutor MT5 (DEMO ONLY)

Jembatan sinyal -> eksekusi, lewat file di folder Common/Files MT5 yang sama
dengan EA exporter (pola komunikasi yang sudah terbukti):

    server (modul ini) menulis  signal.txt   ->  EA XAUUSDPatternExecutor baca
    server (modul ini) membaca exec_log.txt  <-  EA XAUUSDPatternExecutor tulis

Aturan main (WAJIB, tidak bisa dilewati dari config):
  - EA menolak total bila akun MT5 bukan DEMO (cek ACCOUNT_TRADE_MODE di sisi EA).
  - Header signal.txt selalu memuat penanda DEMO_ONLY.
  - Default config: enabled=false (mati). Nyala hanya bila user ubah config.

Sinyal dihitung dari hasil engine terakhir dengan logika yang SAMA dengan
tabel "Saran Riset": SL = band 80% candle yang sama, TP = median close,
prob arah >= prob_min (default 75%) BUY / <= 100-prob_min SELL, R:R >= rr_min.
Eksekusi: maks `max_orders_per_candle` order per candle (default 2:
R:R terbaik + candle pertama yang layak), lot tetap, maks `max_positions`.

Mode tetap eksperimental: tanpa money management di luar batas di atas.
"""
from __future__ import annotations

import hashlib
import os
import time

# folder EA (sama dengan mt5_reader) — di-dup sengaja agar modul ini mandiri
MT5_COMMON_FILES = os.environ.get(
    "MT5_COMMON_FILES",
    "/DATA/AppData/mt5-dockerized/linux/linux-mt5-data/wine-prefix/.mt5/"
    "drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files",
)
EA_FOLDER = os.path.join(MT5_COMMON_FILES, "XAUUSDPattern")
SIGNAL_PATH = os.path.join(EA_FOLDER, "signal.txt")
EXEC_LOG_PATH = os.path.join(EA_FOLDER, "exec_log.txt")

PERIOD_SEC = 300          # M5
MAX_FRESH_SEC = 12 * 60   # anchor candle harus lebih baru dari ini

# state in-memory utk /api/executor
LAST = {
    "enabled": False,
    "last_publish_t": None,     # epoch server saat terakhir menulis signal.txt
    "last_anchor_t": None,      # candle anchor saat terakhir
    "active_signals": [],       # sinyal yang sedang ditawarkan ke EA
    "trend": None,              # hasil detect_trend() run terakhir
    "reason": "belum berjalan",
}


def load_cfg_safe() -> dict:
    """config.json -> dict ({} bila gagal)."""
    import json as _json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _prob_min(cfg: dict) -> float:
    """Probabilitas arah minimum untuk open order (%, 50-95). Default 75."""
    at = cfg.get("auto_trade") or {}
    try:
        v = float(at.get("prob_min", 75.0))
    except (TypeError, ValueError):
        v = 75.0
    return max(50.0, min(95.0, v))


def _rr_min(cfg: dict) -> float:
    at = cfg.get("auto_trade") or {}
    try:
        v = float(at.get("rr_min", 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return max(0.1, v)


def _rr_min_trend(cfg: dict) -> float:
    """R:R minimum saat sinyal SEARAH dengan tren. Default 1.0 agar TP tidak
    lebih kecil dari SL (revisi 17 Nov 2026)."""
    at = cfg.get("auto_trade") or {}
    try:
        v = float(at.get("rr_min_trend", 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return max(0.05, min(_rr_min(cfg), v))


def _trend_filter(cfg: dict) -> bool:
    """Filter tren aktif? (default true). Saat aktif: sinyal LAWAN tren
    diblok total (walau R:R besar), sinyal SEARAH tren boleh R:R longgar."""
    at = cfg.get("auto_trade") or {}
    return bool(at.get("trend_filter", True))


def _trend_period(cfg: dict) -> int:
    """Periode EMA tren (permintaan user 12 Nov 2026: EMA 13)."""
    at = cfg.get("auto_trade") or {}
    try:
        v = int(at.get("trend_period", 13))
    except (TypeError, ValueError):
        v = 13
    return max(2, min(200, v))


def detect_trend(candles_actual: list, cfg: dict) -> dict:
    """Tren dari EMA `trend_period` (default 13) pada close aktual, dibanding
    dgn candle terakhir (permintaan user 12 Nov 2026):
      - candle utuh DI BAWAH EMA (high < EMA)   -> DOWN
      - candle utuh DI ATAS EMA  (low  > EMA)   -> UP
      - EMA DI TENGAH candle (low <= EMA <= high) -> SIDEWAYS: hanya sinyal
        dgn R:R >= rr_min normal (default 1.0), bukan blok total
    candles_actual: list objek/dict dgn .o/.h/.l/.c (tertua -> terbaru)."""
    per = _trend_period(cfg)

    def g(cd, k):
        if isinstance(cd, dict):
            return cd.get(k)
        return getattr(cd, k, None)

    closes = []
    for cd in candles_actual:
        c = g(cd, "c")
        if isinstance(c, (int, float)):
            closes.append(float(c))
    n = len(closes)
    if n < per:
        return {"dir": "SIDE", "ema": None, "reason":
                f"data kurang ({n} < {per} candle)"}
    last = candles_actual[-1]
    o, h, l, c = (g(last, "o"), g(last, "h"), g(last, "l"), g(last, "c"))
    if not all(isinstance(x, (int, float)) for x in (o, h, l, c)):
        return {"dir": "SIDE", "ema": None, "reason": "candle terakhir tak lengkap"}
    # EMA: seed = SMA `per` pertama, lalu EMA standar
    k = 2.0 / (per + 1.0)
    ema = sum(closes[:per]) / per
    for v in closes[per:]:
        ema = v * k + ema * (1.0 - k)
    if l <= ema <= h:
        dir_ = "SIDE"          # EMA menembus candle -> arah tak jelas
    elif ema > h:
        dir_ = "DOWN"          # candle utuh di bawah EMA
    else:
        dir_ = "UP"            # candle utuh di atas EMA
    return {"dir": dir_, "ema": round(ema, 2), "period": per,
            "close": float(c), "high": float(h), "low": float(l)}


def _lot(cfg: dict) -> float:
    """Lot normal untuk sinyal biasa (prob >= 55%)."""
    at = cfg.get("auto_trade") or {}
    try:
        v = float(at.get("lot", 0.01))
    except (TypeError, ValueError):
        v = 0.01
    return max(0.01, min(10.0, v))


def _lot_strong(cfg: dict) -> float:
    """Lot 'kuat' untuk sinyal dengan prob >= prob_min (permintaan user
    11 Nov 2026: 0.05 utk >=75%, 0.01 tetap utk sinyal biasa)."""
    at = cfg.get("auto_trade") or {}
    try:
        v = float(at.get("lot_strong", 0.05))
    except (TypeError, ValueError):
        v = 0.05
    return max(_lot(cfg), min(20.0, v))


def _max_positions(cfg: dict) -> int:
    at = cfg.get("auto_trade") or {}
    try:
        v = int(at.get("max_positions", 5))
    except (TypeError, ValueError):
        v = 5
    return max(1, min(50, v))


def _max_orders(cfg: dict) -> int:
    at = cfg.get("auto_trade") or {}
    try:
        v = int(at.get("max_orders_per_candle", 2))
    except (TypeError, ValueError):
        v = 2
    return max(1, min(5, v))


def _symbol(cfg: dict) -> str:
    at = cfg.get("auto_trade") or {}
    s = (at.get("symbol") or "").strip()
    return s or str(cfg.get("pair", "XAUUSD"))


def market_closed_window(now_ts=None) -> bool:
    """Akhir pekan: emas tutup Jumat ±22:00 UTC s/d buka Minggu ±22:00 UTC.
    (saling dikunci dengan app.py — sengaja didup agar modul mandiri)"""
    import datetime as _dt
    now = _dt.datetime.fromtimestamp(now_ts if now_ts else time.time(),
                                     _dt.timezone.utc)
    wd = now.weekday()
    if wd == 4 and now.hour >= 22:
        return True
    if wd == 5:
        return True
    if wd == 6 and now.hour < 22:
        return True
    return False


def compute_signals(result: dict, anchor_t: int, anchor_c: float,
                    cfg: dict, candles_actual: list | None = None) -> list[dict]:
    """Sinyal layak dari 1 run engine — SL = band 80% candle yang sama,
    TP = median close, prob arah >=55% BUY / <=45% SELL.
    Lot bertingkat: prob >= prob_min (default 75%) -> lot_strong (0.05);
    sinyal biasa 55-75% -> lot normal (0.01).
    Filter tren (permintaan user 12 Nov 2026, default aktif):
      - sinyal LAWAN tren (BUY saat DOWN / SELL saat UP) -> DIBLOK total,
        walaupun R:R-nya besar;
      - sinyal SEARAH tren (SELL saat DOWN / BUY saat UP) -> R:R cukup
        rr_min_trend (default 1.0) — TP tidak boleh lebih kecil dari SL;
      - sideways -> pakai rr_min normal (default 1.0)."""
    rr_min = _rr_min(cfg)
    rr_min_trend = _rr_min_trend(cfg)
    trend_on = _trend_filter(cfg)
    trend = detect_trend(candles_actual, cfg) if (trend_on and candles_actual) \
        else {"dir": "SIDE", "ema": None}
    lot_normal, lot_strong = _lot(cfg), _lot_strong(cfg)
    prob_min = _prob_min(cfg)
    pred = result.get("predicted") or []
    band = result.get("band") or []
    drst = result.get("direction") or []
    out = []
    for idx, c in enumerate(pred):
        b = band[idx] if idx < len(band) else None
        s = drst[idx] if idx < len(drst) else None
        if not isinstance(c, dict) or not isinstance(c.get("c"), (int, float)):
            continue
        if not isinstance(b, dict) or not isinstance(b.get("p10"), (int, float)) \
                or not isinstance(b.get("p90"), (int, float)):
            continue
        if not isinstance(s, dict) or not s.get("n"):
            continue
        tp = float(c["c"])
        up_pct = 100.0 * s["up"] / s["n"]
        if 45.0 < up_pct < 55.0:
            continue                                   # netral
        side = "BUY" if up_pct >= 55.0 else "SELL"
        sl = float(b["p10"] if side == "BUY" else b["p90"])   # band candle yang sama
        reward = (tp - anchor_c) if side == "BUY" else (anchor_c - tp)
        risk = (anchor_c - sl) if side == "BUY" else (sl - anchor_c)
        if risk <= 0 or reward <= 0:
            continue                                   # band salah sisi / tak untung
        rr = reward / risk
        # --- filter tren ---
        aligned = (side == "BUY" and trend["dir"] == "UP") or \
                  (side == "SELL" and trend["dir"] == "DOWN")
        anti = (side == "BUY" and trend["dir"] == "DOWN") or \
               (side == "SELL" and trend["dir"] == "UP")
        if anti:
            continue                                   # lawan tren: blok total
        need = rr_min_trend if (aligned and trend_on) else rr_min
        if rr < need:
            continue
        out.append({
            "id": hashlib.md5(f"{anchor_t}-{idx}-{side}".encode()).hexdigest()[:12],
            "idx": idx, "t": c.get("t"), "side": side,
            "entry": round(anchor_c, 2), "sl": round(sl, 2), "tp": round(tp, 2),
            "rr": round(rr, 2), "up_pct": round(up_pct, 0), "n": s["n"],
            "lot": lot_strong if up_pct >= prob_min else lot_normal,
        })
    out.sort(key=lambda x: x["idx"])
    LAST["trend"] = trend
    return out


def _pick(signals: list[dict], max_orders: int) -> list[dict]:
    """Maks N order per candle: sinyal R:R terbaik + sinyal candle pertama
    yang layak (dedup bila keduanya sama)."""
    if not signals:
        return []
    best_rr = max(signals, key=lambda x: x["rr"])
    chosen = [best_rr]
    first = signals[0]
    if first["id"] != best_rr["id"]:
        chosen.append(first)
    return chosen[:max_orders]


def _write_signal_file(signals: list[dict], anchor_t: int, run_id, cfg: dict):
    """Tulis signal.txt atomik (tmp + rename). Header selalu DEMO_ONLY.
    Format (11 Nov 2026, v1 revisi exit kontradiksi):
      PATDASH;v1;DEMO_ONLY;ACTIVE;n;run_id;SYMBOL;anchor_t;rr_min;maxpos;prob_min
      SIG;id;SIDE;entry;sl;tp;lot;idx;prob
    prob = probabilitas arah sinyal (%); EA menutup posisi lawan saat prob
    sinyal baru >= prob_min (exit kontradiksi: TP manual / cut loss)."""
    os.makedirs(EA_FOLDER, exist_ok=True)
    active = "YES" if signals else "NO"
    lines = [f"PATDASH;v1;DEMO_ONLY;{active};{len(signals)};{run_id};"
             f"{_symbol(cfg)};{anchor_t};{_rr_min(cfg)};{_max_positions(cfg)};"
             f"{_prob_min(cfg)}"]
    for sg in signals:
        lines.append("SIG;%s;%s;%.2f;%.2f;%.2f;%.2f;%d;%.0f" % (
            sg["id"], sg["side"], sg["entry"], sg["sl"], sg["tp"],
            sg["lot"], sg["idx"], sg.get("up_pct", 0.0)))
    tmp = SIGNAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, SIGNAL_PATH)


def _signal_active_now() -> bool:
    """signal.txt masih menawarkan sinyal aktif? (header YES + belum stale)"""
    try:
        with open(SIGNAL_PATH, "r", encoding="utf-8", errors="replace") as f:
            head = f.readline().strip()
        if ";YES;" not in f";{head};":
            return False
        return LAST.get("active_signals", []) and not LAST.get("stale", True)
    except OSError:
        return False


def publish(result: dict, anchor_candle, cfg: dict,
            candles_actual: list | None = None):
    """Dipanggil scheduler setiap engine run selesai. anchor_candle = candle
    aktual terakhir (objek dgn .t dan .c); candles_actual = riwayat candle
    aktual (tertua -> terbaru) untuk deteksi tren EMA."""
    at = cfg.get("auto_trade") or {}
    enabled = bool(at.get("enabled", False))
    LAST["enabled"] = enabled
    LAST["active_signals"] = []
    LAST["stale"] = True

    if not enabled:
        LAST["reason"] = "auto_trade.enabled = false (mati di config)"
        _write_signal_file([], 0, "-", cfg)   # header NO — EA memastikan idle
        return

    if result is None or anchor_candle is None:
        LAST["reason"] = "belum ada hasil engine"
        _write_signal_file([], 0, "-", cfg)
        return
    if result.get("predict_mode") != "topk_median" or not (result.get("band") or []):
        LAST["reason"] = "mode prediksi tanpa band (mean) — eksekusi dilewati"
        _write_signal_file([], 0, "-", cfg)
        return

    anchor_t, anchor_c = int(anchor_candle.t), float(anchor_candle.c)
    LAST["last_anchor_t"] = anchor_t
    age = max(0, int(time.time()) - anchor_t)
    if age > MAX_FRESH_SEC:
        LAST["reason"] = f"candle anchor tidak fresh (umur {age} dtk)"
        _write_signal_file([], 0, "-", cfg)
        return
    if market_closed_window():
        LAST["reason"] = "pasar tutup (akhir pekan)"
        _write_signal_file([], 0, "-", cfg)
        return

    signals = compute_signals(result, anchor_t, anchor_c, cfg, candles_actual)
    chosen = _pick(signals, _max_orders(cfg))
    trend = LAST.get("trend") or {"dir": "SIDE"}
    t_lbl = {"UP": "NAIK", "DOWN": "TURUN", "SIDE": "SIDEWAYS"}.get(trend["dir"], "-")
    if not chosen:
        LAST["reason"] = ("tidak ada sinyal (tren %s, rr_min %.1f" %
                          (t_lbl, _rr_min(cfg)))
        if trend["dir"] != "SIDE":
            LAST["reason"] += (", searah tren cukup %.1f, lawan tren diblok)" %
                               _rr_min_trend(cfg))
        else:
            LAST["reason"] += ")"
        _write_signal_file([], 0, "-", cfg)
        return

    _write_signal_file(chosen, anchor_t, result.get("run_id", "-"), cfg)
    LAST["active_signals"] = chosen
    LAST["stale"] = False
    LAST["last_publish_t"] = int(time.time())
    LAST["reason"] = ("tren %s · sinyal aktif: %s" %
                      (t_lbl,
                       ", ".join(f"{s['side']} #{s['idx'] + 1} R:R 1:{s['rr']}"
                                 for s in chosen)))


def read_exec_log(limit=30) -> list[dict]:
    """Ekor exec_log.txt dari EA (terbaru di akhir). Format baris:
    EXEC;<epoch>;<id>;<side>;<retcode>;<ticket>;<ok|fail>;<alasan>"""
    try:
        with open(EXEC_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for ln in lines:
        p = ln.strip().split(";")
        if len(p) >= 7 and p[0] == "EXEC":
            try:
                epoch = int(p[1])
            except ValueError:
                epoch = None
            out.append({"epoch": epoch, "id": p[2], "side": p[3],
                        "retcode": p[4], "ticket": p[5],
                        "result": p[6], "reason": ";".join(p[7:]) or "-"})
    return out


def cfg_public() -> dict:
    """Subset config auto_trade utk frontend (aturan tabel Saran Riset
    harus cermin eksekutor)."""
    cfg = load_cfg_safe()
    return {
        "trend_filter": _trend_filter(cfg),
        "rr_min": _rr_min(cfg),
        "rr_min_trend": _rr_min_trend(cfg),
        "prob_min": _prob_min(cfg),
        "trend_period": _trend_period(cfg),
    }


def executor_payload() -> dict:
    import json as _json
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
    except Exception:  # noqa: BLE001
        cfg = {}
    at = cfg.get("auto_trade") or {}
    return {
        "ok": True,
        "enabled": bool(at.get("enabled", False)),
        "lot": _lot(cfg),
        "lot_strong": _lot_strong(cfg),
        "prob_min": _prob_min(cfg),
        "max_positions": _max_positions(cfg),
        "max_orders_per_candle": _max_orders(cfg),
        "rr_min": _rr_min(cfg),
        "rr_min_trend": _rr_min_trend(cfg),
        "trend_filter": _trend_filter(cfg),
        "trend": LAST.get("trend"),
        "symbol": _symbol(cfg),
        "signal_file": SIGNAL_PATH,
        "signal_file_exists": os.path.isfile(SIGNAL_PATH),
        "signal_active": _signal_active_now(),
        "last_publish_t": LAST.get("last_publish_t"),
        "last_anchor_t": LAST.get("last_anchor_t"),
        "active_signals": LAST.get("active_signals", []),
        "reason": LAST.get("reason"),
        "exec_log": read_exec_log(),
    }
