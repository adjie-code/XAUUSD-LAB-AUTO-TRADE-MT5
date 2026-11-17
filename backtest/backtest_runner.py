#!/usr/bin/env python3
"""
Backtest runner XAUUSD — terpisah dari runtime MT5/EA.

Prinsip keselamatan:
- Hanya membaca snapshot DB di /tmp/opencode; DB asli tidak pernah dibuka untuk ditulis.
- Snapshot dihapus otomatis di finally/atexit, termasuk saat terjadi error.
- Output hanya ditulis ke folder backtest/results/ (atau --output-dir yang aman).
- CPU dibatasi lewat sched_setaffinity + nice; default core 2,3.
- Tidak mengimpor app.py, executor.py, MT5, Docker, atau file runtime strategi.

Strategi bawaan adalah baseline EMA cross + ATR SL/TP untuk menguji pipeline.
Ini bukan rekomendasi strategi produksi.
"""
from __future__ import annotations

import argparse
import atexit
import csv
import json
import math
import os
import re
import shutil
import signal
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "patterns.db"
DEFAULT_OUTPUT = ROOT / "backtest" / "results"
TMP_ROOT = Path("/tmp/opencode")
FORBIDDEN_OUTPUTS = (
    ROOT / "data",
    ROOT / "ea",
    ROOT / "static",
    ROOT / "skills",
    ROOT / "backups",
)


@dataclass(frozen=True)
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float
    tv: int
    spread: int


@dataclass
class Position:
    side: int                 # 1 = BUY, -1 = SELL
    entry_idx: int
    entry_t: int
    entry_price: float
    sl: float
    tp: float


@dataclass
class Trade:
    no: int
    side: str
    entry_t: int
    exit_t: int
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    bars_held: int
    gross_pnl: float
    commission: float
    net_pnl: float
    reason: str


def utc_iso(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_day(value: str, end_of_day: bool = False) -> int:
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    return ts + 86399 if end_of_day else ts


def parse_cpus(value: str) -> set[int]:
    cpu_count = os.cpu_count() or 1
    cpus: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            cpu = int(part)
        except ValueError:
            continue
        if 0 <= cpu < cpu_count:
            cpus.add(cpu)
    if not cpus:
        cpus = {max(0, cpu_count - 1)}
    return cpus


def apply_limits(cpus: set[int], nice_value: int) -> None:
    try:
        os.sched_setaffinity(0, cpus)
        print(f"[limit] CPU affinity: {sorted(cpus)}")
    except (AttributeError, OSError) as exc:
        print(f"[limit] peringatan: gagal set CPU affinity ({exc})")
    try:
        current = os.nice(nice_value)
        print(f"[limit] nice: {current}")
    except (AttributeError, OSError) as exc:
        print(f"[limit] peringatan: gagal set nice ({exc})")


def ensure_safe_output(path: Path) -> Path:
    resolved = path.resolve()
    for forbidden in FORBIDDEN_OUTPUTS:
        if resolved == forbidden or forbidden in resolved.parents:
            raise SystemExit(f"Output tidak boleh di dalam folder runtime: {resolved}")
    return resolved


def snapshot_db(source: Path, destination: Path) -> None:
    """Buat snapshot konsisten via SQLite backup API (source read-only)."""
    if not source.is_file():
        raise SystemExit(f"DB tidak ditemukan: {source}")
    source_uri = source.resolve().as_uri() + "?mode=ro"
    src = sqlite3.connect(source_uri, uri=True, timeout=30)
    dst = sqlite3.connect(str(destination))
    try:
        src.execute("PRAGMA busy_timeout=10000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if not destination.is_file() or destination.stat().st_size == 0:
        raise SystemExit("Snapshot DB gagal dibuat.")
    print(f"[db] snapshot: {destination} ({destination.stat().st_size / 1024 / 1024:.1f} MB)")


def load_bars(copy_path: Path, start_ts: int, end_ts: int | None) -> tuple[list[Bar], dict]:
    uri = copy_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.execute("PRAGMA query_only=ON")
    try:
        if end_ts is None:
            row = conn.execute("SELECT MAX(t) FROM candles_m5").fetchone()
            if not row or row[0] is None:
                raise SystemExit("Tabel candles_m5 kosong.")
            end_ts = int(row[0])
        if start_ts < parse_day("2018-01-01"):
            try:
                meta = conn.execute(
                    "SELECT value FROM dataset_meta WHERE key='source'").fetchone()
            except sqlite3.OperationalError:
                meta = None
            if not meta or "dukascopy" not in str(meta[0]).lower():
                raise SystemExit(
                    "Rentang sebelum 2018 hanya untuk DB Dukascopy 2006+; "
                    "DB ini tidak punya metadata source=dukascopy. "
                    "Gunakan --start 2018-01-01.")
        query = """
            WITH base AS (
                SELECT t, o, h, l, c, tv, spread,
                       ROW_NUMBER() OVER (
                           PARTITION BY t - (t % 300)
                           ORDER BY t
                       ) AS rn
                FROM candles_m5
                WHERE t >= ? AND t <= ?
            )
            SELECT t, o, h, l, c, tv, spread
            FROM base
            WHERE rn = 1
            ORDER BY t
        """
        rows = conn.execute(query, (start_ts, end_ts)).fetchall()
    finally:
        conn.close()

    if len(rows) < 1000:
        raise SystemExit(
            f"Data terlalu sedikit: {len(rows)} bar. "
            "Gunakan --start 2018-01-01 atau rentang yang lebih panjang."
        )

    bars = [Bar(int(t), float(o), float(h), float(l), float(c), int(tv), int(sp))
            for t, o, h, l, c, tv, sp in rows]

    gaps = [bars[i].t - bars[i - 1].t for i in range(1, len(bars))]
    gaps_gt_1h = sum(1 for g in gaps if g > 3600)
    data_info = {
        "bars": len(bars),
        "start": utc_iso(bars[0].t),
        "end": utc_iso(bars[-1].t),
        "start_ts": bars[0].t,
        "end_ts": bars[-1].t,
        "max_gap_hours": round(max(gaps) / 3600.0, 2) if gaps else 0.0,
        "gaps_gt_1h": gaps_gt_1h,
        "dedup_method": "ROW_NUMBER per bucket 300 detik",
        "filter": "t >= start; bucket t-(t%300); rn=1",
    }
    print(f"[data] {data_info['bars']} bar unik | {data_info['start']} -> {data_info['end']}")
    return bars, data_info


def ema(values: list[float], period: int) -> list[float]:
    out = [math.nan] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    for i in range(period, len(values)):
        out[i] = values[i] * alpha + out[i - 1] * (1.0 - alpha)
    return out


def atr(bars: list[Bar], period: int) -> list[float]:
    n = len(bars)
    out = [math.nan] * n
    if n < period + 1:
        return out
    trs = [0.0] * n
    trs[0] = bars[0].h - bars[0].l
    for i in range(1, n):
        prev_close = bars[i - 1].c
        trs[i] = max(
            bars[i].h - bars[i].l,
            abs(bars[i].h - prev_close),
            abs(bars[i].l - prev_close),
        )
    out[period] = sum(trs[1:period + 1]) / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def close_trade(
    pos: Position,
    exit_t: int,
    exit_raw: float,
    reason: str,
    args: argparse.Namespace,
    spread: float,
    slippage: float,
    trade_no: int,
    bars_held: int,
) -> Trade:
    if pos.side == 1:
        exit_price = exit_raw - slippage
        gross = (exit_price - pos.entry_price) * args.lot * args.contract_size
        side = "BUY"
    else:
        exit_price = exit_raw + spread + slippage
        gross = (pos.entry_price - exit_price) * args.lot * args.contract_size
        side = "SELL"
    commission = args.commission_per_lot * args.lot
    return Trade(
        no=trade_no,
        side=side,
        entry_t=pos.entry_t,
        exit_t=exit_t,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        sl=pos.sl,
        tp=pos.tp,
        bars_held=bars_held,
        gross_pnl=gross,
        commission=commission,
        net_pnl=gross - commission,
        reason=reason,
    )


def run_backtest(bars: list[Bar], args: argparse.Namespace) -> list[Trade]:
    closes = [b.c for b in bars]
    fast = ema(closes, args.fast)
    slow = ema(closes, args.slow)
    atr_values = atr(bars, args.atr)
    point = args.point_size
    spread = args.spread_points * point
    slippage = args.slippage_points * point
    warmup = max(args.slow, args.atr) + 3

    trades: list[Trade] = []
    pos: Position | None = None
    trade_no = 0

    def close(pos_obj: Position, idx: int, raw_exit: float, reason: str) -> None:
        nonlocal trade_no
        trade_no += 1
        tr = close_trade(
            pos_obj, bars[idx].t, raw_exit, reason, args, spread, slippage,
            trade_no, idx - pos_obj.entry_idx)
        trades.append(tr)

    for i in range(warmup, len(bars)):
        bar = bars[i]

        if pos is not None:
            exit_raw: float | None = None
            reason = ""
            if pos.side == 1:
                if bar.o <= pos.sl:
                    exit_raw, reason = bar.o, "SL_GAP"
                elif bar.l <= pos.sl:
                    exit_raw, reason = pos.sl, "SL"
                elif bar.o >= pos.tp:
                    exit_raw, reason = bar.o, "TP_GAP"
                elif bar.h >= pos.tp:
                    exit_raw, reason = pos.tp, "TP"
            else:
                if bar.o >= pos.sl:
                    exit_raw, reason = bar.o, "SL_GAP"
                elif bar.h >= pos.sl:
                    exit_raw, reason = pos.sl, "SL"
                elif bar.o <= pos.tp:
                    exit_raw, reason = bar.o, "TP_GAP"
                elif bar.l <= pos.tp:
                    exit_raw, reason = pos.tp, "TP"
            if exit_raw is not None:
                close(pos, i, exit_raw, reason)
                pos = None

        if pos is None and i + 1 < len(bars):
            if math.isnan(fast[i]) or math.isnan(slow[i]) or math.isnan(atr_values[i]):
                continue
            cross_up = fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]
            cross_dn = fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]
            if not (cross_up or cross_dn):
                continue
            signal_atr = atr_values[i]
            if signal_atr <= 0:
                continue
            next_open = bars[i + 1].o
            if cross_up:
                entry = next_open + spread + slippage
                sl = entry - signal_atr * args.sl_atr
                tp = entry + signal_atr * args.tp_atr
                pos = Position(1, i + 1, bars[i + 1].t, entry, sl, tp)
            else:
                entry = next_open - slippage
                sl = entry + signal_atr * args.sl_atr
                tp = entry - signal_atr * args.tp_atr
                pos = Position(-1, i + 1, bars[i + 1].t, entry, sl, tp)

    if pos is not None:
        close(pos, len(bars) - 1, bars[-1].c, "END_OF_DATA")
    return trades


def build_metrics(
    trades: list[Trade],
    bars: list[Bar],
    data_info: dict,
    args: argparse.Namespace,
    runtime_sec: float,
) -> tuple[dict, list[tuple[Trade, float, float]]]:
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    breakeven = [t for t in trades if t.net_pnl == 0]
    win_net = sum(t.net_pnl for t in wins)
    loss_net = abs(sum(t.net_pnl for t in losses))
    gross_profit = sum(t.gross_pnl for t in wins)
    gross_loss = abs(sum(t.gross_pnl for t in losses))
    net = sum(t.net_pnl for t in trades)
    if loss_net > 0:
        profit_factor: float | None = win_net / loss_net
        profit_factor_note = "finite_net"
    elif win_net > 0:
        profit_factor = None
        profit_factor_note = "no_losses"
    else:
        profit_factor = None
        profit_factor_note = "undefined"

    balance = args.initial_balance
    peak = balance
    max_dd = 0.0
    equity_rows = []
    for t in trades:
        balance += t.net_pnl
        peak = max(peak, balance)
        dd = peak - balance
        max_dd = max(max_dd, dd)
        equity_rows.append((t, balance, dd))

    per_year: dict[str, dict] = {}
    for t in trades:
        year = utc_iso(t.exit_t)[:4]
        item = per_year.setdefault(year, {"trades": 0, "wins": 0, "net_pnl": 0.0})
        item["trades"] += 1
        item["wins"] += 1 if t.net_pnl > 0 else 0
        item["net_pnl"] += t.net_pnl

    for item in per_year.values():
        item["net_pnl"] = round(item["net_pnl"], 2)
        item["win_rate"] = round(100.0 * item["wins"] / item["trades"], 2) if item["trades"] else 0.0

    years = (bars[-1].t - bars[0].t) / 86400.0 / 365.25
    metrics = {
        "strategy": args.strategy,
        "params": {
            "fast": args.fast,
            "slow": args.slow,
            "atr": args.atr,
            "sl_atr": args.sl_atr,
            "tp_atr": args.tp_atr,
            "lot": args.lot,
            "contract_size": args.contract_size,
            "spread_points": args.spread_points,
            "slippage_points": args.slippage_points,
            "commission_per_lot": args.commission_per_lot,
            "initial_balance": args.initial_balance,
            "point_size": args.point_size,
        },
        "data": data_info,
        "runtime_sec": round(runtime_sec, 3),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2) if trades else 0.0,
        "net_pnl": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "profit_factor_note": profit_factor_note,
        "expectancy_per_trade": round(net / len(trades), 2) if trades else 0.0,
        "avg_win": round(win_net / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-loss_net / len(losses), 2) if losses else 0.0,
        "largest_win": round(max((t.net_pnl for t in wins), default=0.0), 2),
        "largest_loss": round(min((t.net_pnl for t in losses), default=0.0), 2),
        "avg_bars_held": round(sum(t.bars_held for t in trades) / len(trades), 1) if trades else 0.0,
        "buy_trades": sum(1 for t in trades if t.side == "BUY"),
        "sell_trades": sum(1 for t in trades if t.side == "SELL"),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(100.0 * max_dd / peak, 2) if peak > 0 else 0.0,
        "return_pct": round(100.0 * net / args.initial_balance, 2) if args.initial_balance else 0.0,
        "years": round(years, 2),
        "per_year": dict(sorted(per_year.items())),
        "notes": [
            "Baseline EMA cross + ATR SL/TP; bukan rekomendasi strategi produksi.",
            "Sinyal dihitung di close bar, entry di open bar berikutnya.",
            "Jika SL dan TP tersentuh di bar yang sama, SL dianggap lebih dulu (konservatif).",
            "Spread/slippage/commission adalah asumsi input, bukan data tick.",
            "Data 2015-2016 (daily) tidak dipakai; default mulai 2018.",
        ],
    }
    return metrics, equity_rows


def write_outputs(
    output_dir: Path,
    metrics: dict,
    trades: list[Trade],
    equity_rows: list[tuple[Trade, float, float]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (output_dir / "trades.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "no", "side", "entry_time", "exit_time", "entry_price", "exit_price",
            "sl", "tp", "bars_held", "gross_pnl", "commission", "net_pnl", "reason",
        ])
        for t in trades:
            writer.writerow([
                t.no, t.side, utc_iso(t.entry_t), utc_iso(t.exit_t),
                f"{t.entry_price:.2f}", f"{t.exit_price:.2f}",
                f"{t.sl:.2f}", f"{t.tp:.2f}", t.bars_held,
                f"{t.gross_pnl:.2f}", f"{t.commission:.2f}", f"{t.net_pnl:.2f}",
                t.reason,
            ])

    with (output_dir / "equity.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["trade_no", "exit_time", "net_pnl", "cumulative_pnl", "balance", "drawdown"])
        cumulative = 0.0
        for t, balance, dd in equity_rows:
            cumulative += t.net_pnl
            writer.writerow([
                t.no, utc_iso(t.exit_t), f"{t.net_pnl:.2f}",
                f"{cumulative:.2f}", f"{balance:.2f}", f"{dd:.2f}",
            ])

    (output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")


def render_report(metrics: dict) -> str:
    d = metrics["data"]
    p = metrics["params"]
    lines = [
        "# Backtest Report — XAUUSD",
        "",
        "> Baseline pipeline test, bukan rekomendasi strategi produksi.",
        "",
        "## Data",
        f"- Bar unik: **{d['bars']:,}**",
        f"- Periode: **{d['start']} UTC → {d['end']} UTC**",
        f"- Tahun: **{metrics['years']}**",
        f"- Gap > 1 jam: **{d['gaps_gt_1h']}**",
        f"- Max gap: **{d['max_gap_hours']} jam**",
        f"- Metode: {d['dedup_method']}",
        "",
        "## Parameter",
        f"- Strategi: `{metrics['strategy']}`",
        f"- EMA fast/slow: **{p['fast']}/{p['slow']}**",
        f"- ATR: **{p['atr']}**, SL **{p['sl_atr']}×ATR**, TP **{p['tp_atr']}×ATR**",
        f"- Lot: **{p['lot']}**, contract size **{p['contract_size']}**",
        f"- Spread: **{p['spread_points']} poin**, slippage **{p['slippage_points']} poin**",
        f"- Commission: **{p['commission_per_lot']} per lot**",
        f"- Modal awal: **{p['initial_balance']} USD**",
        "",
        "## Hasil",
        f"- Trades: **{metrics['trades']}** (BUY {metrics['buy_trades']} / SELL {metrics['sell_trades']})",
        f"- Win rate: **{metrics['win_rate_pct']}%**",
        f"- Net PnL: **{metrics['net_pnl']} USD**",
        f"- Return: **{metrics['return_pct']}%**",
        f"- Profit factor: **{metrics['profit_factor']}** ({metrics['profit_factor_note']})",
        f"- Expectancy/trade: **{metrics['expectancy_per_trade']} USD**",
        f"- Max drawdown: **{metrics['max_drawdown']} USD** ({metrics['max_drawdown_pct']}%)",
        f"- Avg bars held: **{metrics['avg_bars_held']}**",
        "",
        "## Per tahun",
        "| Tahun | Trades | Win rate | Net PnL |",
        "|---|---:|---:|---:|",
    ]
    for year, item in metrics["per_year"].items():
        lines.append(
            f"| {year} | {item['trades']} | {item['win_rate']}% | {item['net_pnl']} |")
    lines += [
        "",
        "## Catatan",
        *[f"- {note}" for note in metrics["notes"]],
        "",
    ]
    return "\n".join(lines)


def cleanup_workdir(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.exists():
            shutil.rmtree(path)
            print(f"[cleanup] DB copy dihapus: {path}")
    except OSError as exc:
        print(f"[cleanup] peringatan: gagal hapus {path}: {exc}", file=sys.stderr)


def main() -> int:
    def _stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)

    parser = argparse.ArgumentParser(
        description="Backtest XAUUSD dari snapshot SQLite, terpisah dari MT5/EA.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", default="2006-01-01",
                        help="Tanggal mulai UTC, format YYYY-MM-DD (default: 2006)")
    parser.add_argument("--end", default=None,
                        help="Tanggal akhir UTC, format YYYY-MM-DD")
    parser.add_argument("--strategy", default="ema_cross", choices=["ema_cross"])
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=50)
    parser.add_argument("--atr", type=int, default=14)
    parser.add_argument("--sl-atr", type=float, default=1.5)
    parser.add_argument("--tp-atr", type=float, default=2.5)
    parser.add_argument("--spread-points", type=float, default=30.0)
    parser.add_argument("--slippage-points", type=float, default=0.0)
    parser.add_argument("--commission-per-lot", type=float, default=0.0)
    parser.add_argument("--lot", type=float, default=0.01)
    parser.add_argument("--contract-size", type=float, default=100.0)
    parser.add_argument("--point-size", type=float, default=0.01)
    parser.add_argument("--initial-balance", type=float, default=10000.0)
    parser.add_argument("--cpus", default="2,3",
                        help="Core yang dipakai, mis. 2,3 (default: 2,3)")
    parser.add_argument("--nice", type=int, default=19)
    parser.add_argument("--run-id", default=None,
                        help="Id run untuk folder output (default: timestamp)")
    args = parser.parse_args()

    if args.run_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("--run-id hanya boleh huruf/angka/_/- maksimal 64 karakter")

    if args.fast < 2 or args.slow < 3 or args.fast >= args.slow:
        parser.error("--fast harus >=2 dan lebih kecil dari --slow")
    if args.atr < 2:
        parser.error("--atr minimal 2")
    if args.lot <= 0 or args.contract_size <= 0 or args.point_size <= 0:
        parser.error("lot/contract-size/point-size harus > 0")

    start_ts = parse_day(args.start)
    end_ts = parse_day(args.end, end_of_day=True) if args.end else None
    if start_ts < parse_day("2006-01-01"):
        parser.error("Dataset Dukascopy yang tersedia dimulai 2006-01-01.")

    apply_limits(parse_cpus(args.cpus), args.nice)
    output_dir = ensure_safe_output(args.output_dir)
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_path = output_dir / f"run_{run_id}"

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="xauusd-backtest-", dir=str(TMP_ROOT)))
    copy_path = workdir / "patterns.db"
    atexit.register(cleanup_workdir, workdir)

    started = time.perf_counter()
    try:
        snapshot_db(args.db, copy_path)
        bars, data_info = load_bars(copy_path, start_ts, end_ts)
        trades = run_backtest(bars, args)
        runtime = time.perf_counter() - started
        metrics, equity_rows = build_metrics(trades, bars, data_info, args, runtime)
        write_outputs(out_path, metrics, trades, equity_rows)
        print(f"[done] {metrics['trades']} trades | net {metrics['net_pnl']} USD | "
              f"PF {metrics['profit_factor']} | DD {metrics['max_drawdown_pct']}%")
        print(f"[done] output: {out_path}")
        return 0
    except KeyboardInterrupt:
        print("\n[stop] dibatalkan oleh user", file=sys.stderr)
        return 130
    finally:
        cleanup_workdir(workdir)
        atexit.unregister(cleanup_workdir)


if __name__ == "__main__":
    raise SystemExit(main())
