#!/usr/bin/env python3
"""
Bangun database SQLite baru dari CSV Dukascopy (XAUUSD M5).

- Tidak pernah menulis ke data/patterns.db live.
- Output DB harus path baru; script menolak menimpa DB live.
- CSV format: timestamp(ms UTC),open,high,low,close,volume.
- Volume Dukascopy (default millions) dikonversi ke integer tick volume.
- Spread diset 0 karena Dukascopy CSV tidak membawa spread.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE_DB = (ROOT / "data" / "patterns.db").resolve()
SCHEMA = """
CREATE TABLE IF NOT EXISTS candles_m5 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    t INTEGER NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
    tv INTEGER NOT NULL, spread INTEGER NOT NULL,
    dt_created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pattern_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_start_t INTEGER NOT NULL,
    actual_end_t INTEGER NOT NULL,
    predicted_start_t INTEGER NOT NULL,
    similarity_pct REAL NOT NULL,
    top_pattern_rank INTEGER,
    mape_usd REAL,
    hit_target INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engine_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    last_candle_t INTEGER NOT NULL,
    bars_count INTEGER NOT NULL,
    n_matches INTEGER NOT NULL,
    best_similarity REAL,
    data_sufficient INTEGER NOT NULL DEFAULT 0,
    predict_mode TEXT, predict_k INTEGER, band_json TEXT, direction_json TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    run_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
    PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS accuracy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    idx INTEGER,
    actual_close_price REAL,
    predicted_close_price REAL,
    error_pct REAL,
    evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_t_uniq ON candles_m5(t);
CREATE INDEX IF NOT EXISTS idx_candles_t ON candles_m5(t);
"""


def utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(raw: str) -> int:
    value = float(raw)
    # Dukascopy CLI default: epoch milliseconds. Terima detik juga.
    return int(value / 1000) if value > 10_000_000_000 else int(value)


def import_csvs(input_dir: Path, db_path: Path, volume_multiplier: float,
                min_bars: int, report_path: Path | None) -> dict:
    files = sorted(input_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"Tidak ada CSV di {input_dir}")

    db_path = db_path.resolve()
    if db_path == LIVE_DB:
        raise SystemExit("Menolak menimpa data/patterns.db live. Pakai path DB baru.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")

        insert_sql = """INSERT OR REPLACE INTO candles_m5
            (t,o,h,l,c,tv,spread,dt_created) VALUES (?,?,?,?,?,?,?,?)"""
        batch: list[tuple] = []
        total_rows = 0
        invalid_rows = 0
        empty_files: list[str] = []
        for path in files:
            file_rows = 0
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.DictReader(f)
                required = {"timestamp", "open", "high", "low", "close"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    raise SystemExit(f"Header CSV tidak dikenali: {path}")
                for row in reader:
                    try:
                        t = parse_timestamp(row["timestamp"])
                        o = float(row["open"])
                        h = float(row["high"])
                        l = float(row["low"])
                        c = float(row["close"])
                        vol = float(row.get("volume") or 0.0)
                    except (TypeError, ValueError, KeyError):
                        invalid_rows += 1
                        continue
                    if min(o, h, l, c) <= 0 or h < l or h < max(o, c) or l > min(o, c):
                        invalid_rows += 1
                        continue
                    tv = max(0, int(round(vol * volume_multiplier)))
                    batch.append((t, o, h, l, c, tv, 0, utc_iso(t)))
                    file_rows += 1
                    total_rows += 1
                    if len(batch) >= 50_000:
                        conn.executemany(insert_sql, batch)
                        batch.clear()
            if file_rows == 0:
                empty_files.append(path.name)
            print(f"[import] {path.name}: {file_rows:,} baris")

        if batch:
            conn.executemany(insert_sql, batch)
        conn.commit()

        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("ANALYZE")

        count, distinct_t, min_t, max_t = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT t), MIN(t), MAX(t) FROM candles_m5"
        ).fetchone()
        per_year_rows = conn.execute(
            "SELECT strftime('%Y', t, 'unixepoch') AS y, COUNT(*) "
            "FROM candles_m5 GROUP BY y ORDER BY y"
        ).fetchall()
        bad_ohlc = conn.execute(
            "SELECT COUNT(*) FROM candles_m5 "
            "WHERE o<=0 OR h<=0 OR l<=0 OR c<=0 OR h<l OR h<MAX(o,c) OR l>MIN(o,c)"
        ).fetchone()[0]

        meta = {
            "source": "dukascopy-node xauusd m5 bid",
            "input_dir": str(input_dir),
            "db": str(db_path),
            "files": [p.name for p in files],
            "empty_files": empty_files,
            "rows_seen": total_rows,
            "invalid_rows": invalid_rows,
            "count": count,
            "distinct_t": distinct_t,
            "duplicates": count - distinct_t,
            "bad_ohlc": bad_ohlc,
            "min_t": min_t,
            "max_t": max_t,
            "min_utc": utc_iso(min_t) if min_t else None,
            "max_utc": utc_iso(max_t) if max_t else None,
            "span_years": round((max_t - min_t) / (365.25 * 86400), 2) if min_t and max_t else 0,
            "per_year": {str(y): n for y, n in per_year_rows},
            "volume_multiplier": volume_multiplier,
            "spread": 0,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }
        conn.executemany("INSERT OR REPLACE INTO dataset_meta(key,value) VALUES (?,?)",
                         [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        conn.commit()

        if count < min_bars:
            raise SystemExit(f"Baris kurang: {count:,} < minimal {min_bars:,}")
        if duplicates := (count - distinct_t):
            raise SystemExit(f"Masih ada duplikat timestamp: {duplicates}")
        if bad_ohlc:
            raise SystemExit(f"OHLC tidak valid: {bad_ohlc}")

        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        print(f"[import] selesai: {count:,} bar | {meta['min_utc']} -> {meta['max_utc']} "
              f"| {meta['span_years']} tahun | DB {db_path}")
        return meta
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bangun DB baru dari CSV Dukascopy XAUUSD M5.")
    parser.add_argument("--input-dir", type=Path,
                        default=ROOT / "backtest" / "data" / "dukascopy" / "raw")
    parser.add_argument("--db", type=Path,
                        default=ROOT / "data" / "patterns_dukascopy_new.db")
    parser.add_argument("--volume-multiplier", type=float, default=1_000_000.0,
                        help="Dukascopy volume default millions; 1e6 -> units")
    parser.add_argument("--min-bars", type=int, default=1_000_000)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    meta = import_csvs(args.input_dir, args.db, args.volume_multiplier,
                       args.min_bars, args.report)
    print(json.dumps({k: meta[k] for k in ("count", "distinct_t", "duplicates",
                                          "min_utc", "max_utc", "span_years")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
