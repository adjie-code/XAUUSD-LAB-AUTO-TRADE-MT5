#!/usr/bin/env python3
"""Agregator monitoring per strategi. Read-only, tanpa order."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import ea_generator
import executor
import pattern_engine
import strategy_engine

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "backtest" / "results"
POSITIONS_PATH = Path(executor.EA_FOLDER) / "positions.txt"
PNL_PATH = Path(executor.EA_FOLDER) / "pnl.txt"
MAGIC_MAP = {20261111: "pattern", 20261113: "pullback",
             20261114: "meanrev", 20261115: "breakout", 20261116: "confluence"}
_CACHE = {"at": 0.0, "data": None}


def _latest_summary(name: str) -> dict | None:
    files = sorted(RESULTS.glob(f"strategy_{name}/run_*/summary.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        d = json.loads(files[0].read_text(encoding="utf-8"))
        d["_path"] = str(files[0])
        return d
    except (OSError, ValueError):
        return None


def _strategy_card(sid: str, name: str, mode: str, magic, status: str,
                   rules: str, latest: dict | None, metrics: dict | None,
                   note: str = "") -> dict:
    verdict = None
    if metrics:
        try:
            verdict = ea_generator.evaluate_summary(metrics)
        except Exception:
            verdict = None
    return {"id": sid, "name": name, "mode": mode, "magic": magic,
            "status": status, "rules": rules, "latest": latest,
            "metrics": metrics, "verdict": verdict, "note": note}


def _read_positions() -> tuple[list[dict], str | None]:
    if not POSITIONS_PATH.is_file():
        return [], None
    try:
        mtime = datetime.fromtimestamp(POSITIONS_PATH.stat().st_mtime,
                                       timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines = POSITIONS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], None
    out = []
    for line in lines:
        p = line.strip().split(";")
        if len(p) < 12 or p[0] != "POS":
            continue
        try:
            magic = int(p[1])
            sid = MAGIC_MAP.get(magic)
            if not sid:
                continue
            out.append({
                "strategy": sid, "label": p[2], "ticket": p[3],
                "side": p[4], "volume": float(p[5]), "entry": float(p[6]),
                "sl": float(p[7]), "tp": float(p[8]),
                "current": float(p[9]), "profit": float(p[10]),
                "open_time": int(p[11]),
            })
        except (TypeError, ValueError):
            continue
    return out, mtime


def _read_pnl() -> tuple[list[dict], str | None, str | None]:
    if not PNL_PATH.is_file():
        return [], None, None
    try:
        mtime = datetime.fromtimestamp(PNL_PATH.stat().st_mtime,
                                       timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines = PNL_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], None, None
    rows = []
    today = None
    for line in lines:
        p = line.strip().split(";")
        if len(p) >= 2 and p[0] == "META":
            today = p[1]
            continue
        if len(p) < 6 or p[0] != "PNL":
            continue
        try:
            magic = int(p[2])
            sid = MAGIC_MAP.get(magic)
            if not sid:
                continue
            rows.append({"date": p[1], "magic": magic, "strategy": sid,
                         "label": p[3], "trades": int(p[4]),
                         "realized": float(p[5])})
        except (TypeError, ValueError):
            continue
    return rows, mtime, today


def payload(force: bool = False) -> dict:
    import time
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["at"] < 10:
        return _CACHE["data"]
    positions, positions_updated = _read_positions()
    positions_by = {}
    for row in positions:
        positions_by.setdefault(row["strategy"], []).append(row)
    floating_pnl = round(sum(r["profit"] for r in positions), 2)

    pnl_rows, pnl_updated, pnl_today = _read_pnl()
    realized_by = {sid: 0.0 for sid in MAGIC_MAP.values()}
    trades_by = {sid: 0 for sid in MAGIC_MAP.values()}
    daily = {}
    for row in pnl_rows:
        sid = row["strategy"]
        realized_by[sid] = realized_by.get(sid, 0.0) + row["realized"]
        trades_by[sid] = trades_by.get(sid, 0) + row["trades"]
        d = daily.setdefault(row["date"], {"date": row["date"], "total": 0.0,
                                           "trades": 0, "by_strategy": {}})
        d["by_strategy"][sid] = d["by_strategy"].get(sid, 0.0) + row["realized"]
        d["total"] += row["realized"]
        d["trades"] += row["trades"]
    daily_rows = sorted(daily.values(), key=lambda x: x["date"], reverse=True)
    for d in daily_rows:
        d["total"] = round(d["total"], 2)
        d["by_strategy"] = {k: round(v, 2) for k, v in d["by_strategy"].items()}
    pnl_by_strategy = {}
    for sid in MAGIC_MAP.values():
        ps = positions_by.get(sid, [])
        fl = round(sum(r["profit"] for r in ps), 2)
        real = round(realized_by.get(sid, 0.0), 2)
        pnl_by_strategy[sid] = {"realized": real, "floating": fl,
                                "total": round(real + fl, 2),
                                "trades": trades_by.get(sid, 0),
                                "open_count": len(ps)}
    realized_total = round(sum(v["realized"] for v in pnl_by_strategy.values()), 2)
    total_pnl = round(realized_total + floating_pnl, 2)

    candles = strategy_engine.load_candles(8000)
    forecast = pattern_engine.direction_forecast(candles) if candles else None
    shadow = strategy_engine.latest_shadow_signals(candles, forecast) if candles else []
    live = executor.executor_payload()
    trend = live.get("trend")
    if not trend:
        try:
            trend = executor.detect_trend(candles, executor.load_cfg_safe())
        except Exception:
            trend = None
    try:
        logs = executor.read_exec_log(200) or live.get("exec_log") or []
    except Exception:
        logs = live.get("exec_log") or []
    def _exec_rows(prefix):
        return [x for x in logs if str(x.get("id", "")).startswith(prefix)]
    def _exec_tail(prefix):
        return [x for x in _exec_rows(prefix) if x.get("result") != "refuse"][-5:]
    pat_logs = _exec_tail("PAT-")
    pb_logs = _exec_tail("PB-")
    mr_logs = _exec_tail("MR-")
    bo_logs = _exec_tail("BO-")
    cf_logs = _exec_tail("CF-")
    pat_refused = sum(1 for x in _exec_rows("PAT-") if x.get("result") == "refuse")
    pb_refused = sum(1 for x in _exec_rows("PB-") if x.get("result") == "refuse")
    mr_refused = sum(1 for x in _exec_rows("MR-") if x.get("result") == "refuse")
    bo_refused = sum(1 for x in _exec_rows("BO-") if x.get("result") == "refuse")
    cf_refused = sum(1 for x in _exec_rows("CF-") if x.get("result") == "refuse")
    now_ts = int(__import__("time").time())
    day0 = now_ts - (now_ts % 86400)
    entries_today = {
        "pattern": sum(1 for x in logs if str(x.get("id", "")).startswith("PAT-")
                        and x.get("result") == "ok" and (x.get("epoch") or 0) >= day0),
        "pullback": sum(1 for x in logs if str(x.get("id", "")).startswith("PB-")
                         and x.get("result") == "ok" and (x.get("epoch") or 0) >= day0),
        "meanrev": sum(1 for x in logs if str(x.get("id", "")).startswith("MR-")
                        and x.get("result") == "ok" and (x.get("epoch") or 0) >= day0),
        "breakout": sum(1 for x in logs if str(x.get("id", "")).startswith("BO-")
                         and x.get("result") == "ok" and (x.get("epoch") or 0) >= day0),
        "confluence": sum(1 for x in logs if str(x.get("id", "")).startswith("CF-")
                           and x.get("result") == "ok" and (x.get("epoch") or 0) >= day0),
    }
    active = live.get("active_signals") or []
    conf = []
    for s in active:
        fd = (forecast or {}).get("dir", 0)
        side = s.get("side")
        if fd > 0 and side == "BUY" or fd < 0 and side == "SELL":
            align = "konfirmasi"
        elif fd == 0:
            align = "netral"
        else:
            align = "konflik"
        conf.append({"id": s.get("id"), "side": side, "entry": s.get("entry"),
                     "sl": s.get("sl"), "tp": s.get("tp"), "align": align})

    by = {s["strategy"]: s for s in shadow}
    mr = _latest_summary("meanrev")
    bo = _latest_summary("breakout")
    def _live_latest(sig, logs, entries, refused, extra=None):
        d = dict(sig) if sig else {}
        d["logs"] = logs
        d["entries_today"] = entries
        d["refused_recent"] = refused
        if extra:
            d.update(extra)
        return d

    slots = {"pattern": 3, "pullback": 2, "meanrev": 5,
             "breakout": 5, "confluence": 5}
    cards = [
        _strategy_card(
            "pattern", "PATTERN", "LIVE", 20261111,
            ("sinyal aktif" if active else "siaga") if live.get("enabled") else "nonaktif",
            "signal.txt · EMA13 · RR min 1.0 · exit kontradiksi + time stop 240m + tren berbalik · maks 3 slot",
            {"active": active, "logs": pat_logs,
             "entries_today": entries_today["pattern"],
             "refused_recent": pat_refused}, None,
            "Live DEMO; slot PATTERN tetap 3; RR aktual <1 ditolak/ditutup; time stop dan exit tren aktif."),
        _strategy_card(
            "pullback", "PULLBACK TREN", "LIVE", 20261113,
            "aktif",
            "H1 EMA50/200 + M5 EMA20 + ATR + trailing + time stop",
            {"logs": pb_logs, "entries_today": entries_today["pullback"],
             "refused_recent": pb_refused}, None,
            "Live DEMO; aturan dan slot 2 tidak diubah; exit otomatis SL/TP, trailing, time stop, dan tren H1 berbalik."),
        _strategy_card(
            "meanrev", "MEAN REVERSION H1", "LIVE", 20261114,
            "sinyal" if by.get("meanrev") else "aktif",
            "RSI<30 / lower BB + H1 tidak turun; RSI>70 / upper BB + H1 tidak naik",
            _live_latest(by.get("meanrev"), mr_logs, entries_today["meanrev"], mr_refused),
            mr,
            "Live DEMO, lot 0.01, slot 5. Backtest masih Tolak; dipakai atas permintaan user."),
        _strategy_card(
            "breakout", "SESSION BREAKOUT", "LIVE", 20261115,
            "sinyal" if by.get("breakout") else "aktif",
            "Range Asia 00-07 UTC, breakout 07-12 UTC, SL/TP ATR",
            _live_latest(by.get("breakout"), bo_logs, entries_today["breakout"], bo_refused),
            bo,
            "Live DEMO, lot 0.01, slot 5. Backtest masih Tolak; dipakai atas permintaan user."),
        _strategy_card(
            "confluence", "PATTERN + FORECAST", "LIVE", 20261116,
            "aktif",
            "Order tambahan hanya bila sinyal PATTERN searah forecast arah",
            {"logs": cf_logs, "alignments": conf,
             "entries_today": entries_today["confluence"],
             "refused_recent": cf_refused}, None,
            "Live DEMO, lot 0.01, slot 5; PATTERN tetap dibatasi 3."),
    ]
    for c in cards:
        c["slots"] = slots.get(c["id"], 0)
        ps = positions_by.get(c["id"], [])
        c["positions"] = ps
        c["open_count"] = len(ps)
        c["floating_pnl"] = round(sum(r["profit"] for r in ps), 2)
        c["pnl"] = pnl_by_strategy.get(c["id"])
    validation = None
    vpath = ROOT / "data" / "direction_validation.json"
    if vpath.is_file():
        try:
            validation = json.loads(vpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            validation = None
    out = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "trend": trend,
        "direction_validation": validation,
        "forecast": forecast,
        "strategies": cards,
        "slot_allocation": slots,
        "open_positions": positions,
        "positions_updated": positions_updated,
        "position_count": len(positions),
        "floating_pnl": floating_pnl,
        "pnl": {"realized_total": realized_total,
                "floating_total": floating_pnl,
                "total": total_pnl,
                "per_strategy": pnl_by_strategy,
                "daily": daily_rows,
                "today": pnl_today,
                "updated": pnl_updated},
        "shadow_signals": shadow,
        "executor": {"enabled": live.get("enabled"),
                     "signal_active": live.get("signal_active"),
                     "active_signals": active,
                     "reason": live.get("reason")},
    }
    _CACHE["at"] = now
    _CACHE["data"] = out
    return out
