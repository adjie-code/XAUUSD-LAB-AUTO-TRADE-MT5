#!/usr/bin/env python3
"""Jalankan backtest strategi shadow: meanrev + breakout (bukan EA live)."""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import strategy_engine as se


def main() -> int:
    started = time.perf_counter()
    try:
        os.sched_setaffinity(0, {2, 3})
    except (AttributeError, OSError):
        pass
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    # Wajib: backtest memakai snapshot DB read-only, bukan DB aktif.
    tmp_base = Path("/tmp/opencode")
    tmp_base.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="xauusd-strategy-", dir=tmp_base))
    db_copy = tmpdir / "patterns.db"
    try:
        # SQLite backup API = snapshot konsisten walau dashboard sedang menulis.
        src = sqlite3.connect(f"file:{se.DB_PATH.resolve()}?mode=ro", uri=True)
        dst = sqlite3.connect(db_copy)
        src.backup(dst)
        dst.close()
        src.close()
        candles = se.load_candles(db_path=db_copy)
        if len(candles) < 10_000:
            raise SystemExit("data candle kurang")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_root = se.RESULTS
        print(f"[data] {len(candles):,} candle | {se.datetime.fromtimestamp(candles[0].t, se.timezone.utc)} -> {se.datetime.fromtimestamp(candles[-1].t, se.timezone.utc)}")
        print(f"[db] salinan read-only: {db_copy}")

        for name, fn in (("meanrev", se.backtest_meanrev), ("breakout", se.backtest_breakout)):
            t0 = time.perf_counter()
            trades = fn(candles)
            summary = se.summarize(trades, candles, name)
            summary["oos"] = se.split_metrics(
                trades, int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()))
            summary["runtime_sec"] = round(time.perf_counter() - t0, 2)
            out = se.write_run(out_root, f"strategy_{name}", summary, trades, stamp)
            print(f"[{name}] {summary['trades']} trades | net {summary['net_pnl']} | "
                  f"PF {summary['profit_factor']} | DD {summary['max_drawdown_pct']}% | "
                  f"{summary['runtime_sec']}s -> {out}")
        print(f"[done] total {time.perf_counter() - started:.1f}s")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
