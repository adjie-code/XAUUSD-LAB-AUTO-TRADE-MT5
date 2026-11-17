#!/usr/bin/env python3
"""Inisialisasi / upgrade database SQLite untuk dashboard (aman dipanggil berulang)."""
import os
import sqlite3

DB_PATH = os.environ.get(
    "DASHBOARD_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "patterns.db"),
)

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

TABLES = {
    "candles_m5": """CREATE TABLE IF NOT EXISTS candles_m5 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        t INTEGER NOT NULL,
        o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
        tv INTEGER NOT NULL, spread INTEGER NOT NULL,
        dt_created TEXT NOT NULL)""",
    "pattern_matches": """CREATE TABLE IF NOT EXISTS pattern_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_start_t INTEGER NOT NULL,
        actual_end_t INTEGER NOT NULL,
        predicted_start_t INTEGER,
        similarity_pct REAL NOT NULL,
        top_pattern_rank INTEGER,
        mape_usd REAL,
        hit_target INTEGER DEFAULT 0,
        created_at TEXT NOT NULL)""",
    # Fase 4/6: satu baris per satu run mesin (trigger tiap N candle)
    "engine_runs": """CREATE TABLE IF NOT EXISTS engine_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT NOT NULL,
        last_candle_t INTEGER NOT NULL,
        bars_count INTEGER NOT NULL,
        n_matches INTEGER NOT NULL,
        best_similarity REAL,
        data_sufficient INTEGER NOT NULL DEFAULT 0)""",
    # Fase 5: estimasi 10 candle hasil satu run (10 baris / run)
    "predictions": """CREATE TABLE IF NOT EXISTS predictions (
        run_id INTEGER NOT NULL,
        idx INTEGER NOT NULL,
        o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
        PRIMARY KEY (run_id, idx))""",
    # Fase 8: satu baris per candle index yang sudah matang (bisa dievaluasi)
    "accuracy_history": """CREATE TABLE IF NOT EXISTS accuracy_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        idx INTEGER,
        actual_close_price REAL,
        predicted_close_price REAL,
        error_pct REAL,
        evaluated_at TEXT NOT NULL)""",
}

for name, stmt in TABLES.items():
    c.execute(stmt)

# migrasi DB lama: kolom idx belum ada
conn.execute("CREATE TEMP TABLE IF NOT EXISTS _m (x)")
cols = [r[1] for r in conn.execute("PRAGMA table_info(accuracy_history)").fetchall()]
if cols and "idx" not in cols:
    conn.execute("ALTER TABLE accuracy_history ADD COLUMN idx INTEGER")

# migrasi: mode prediksi (mean lama / topk_median baru) + band & direction
for tbl, col, ddl in (
    ("engine_runs", "predict_mode", "TEXT"),
    ("engine_runs", "predict_k", "INTEGER"),
    ("engine_runs", "band_json", "TEXT"),
    ("engine_runs", "direction_json", "TEXT"),
):
    _c = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
    if _c and col not in _c:
        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")

# migrasi model arah (16 Nov 2026)
for col, ddl in (
    ("forecast_dir", "INTEGER"),
    ("forecast_confidence", "TEXT"),
    ("forecast_rule", "TEXT"),
):
    _c = [r[1] for r in conn.execute("PRAGMA table_info(engine_runs)").fetchall()]
    if _c and col not in _c:
        conn.execute(f"ALTER TABLE engine_runs ADD COLUMN {col} {ddl}")

# Indeks + unique t (dedup dulu supaya unique index tidak gagal pada DB lama)
c.execute("CREATE INDEX IF NOT EXISTS idx_candles_t ON candles_m5(t)")
c.execute("""DELETE FROM candles_m5 WHERE id NOT IN
             (SELECT MAX(id) FROM candles_m5 GROUP BY t)""")
c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_t_uniq ON candles_m5(t)")

conn.commit()
conn.close()
print("Database siap:", DB_PATH)
