#!/usr/bin/env python3
"""
Fase 3 — Import / backfill candle M5 dari file CSV milik EA ke SQLite:
- candles_m5.csv       rolling (max 5000 bar, ditulis ulang EA tiap candle)
- candles_m5_full.csv  full history (Fase 3, ditulis EA TryBackfill, <= 2 tahun)

Keduanya upsert (INSERT OR REPLACE) berdasarkan timestamp t, jadi aman dipanggil
berulang dan tidak pernah menduplikasi baris. Riwayat pattern_matches/accuracy
tidak dihancurkan. (Versi lama dengan DELETE-all sudah dihapus.)
"""
import csv
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "patterns.db")
CSV_ROLLING = os.environ.get(
    "MT5_CANDLES_CSV",
    os.path.join(os.environ.get(
        "MT5_COMMON_FILES",
        "/DATA/AppData/mt5-dockerized/linux/linux-mt5-data/wine-prefix/.mt5/"
        "drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files",
    ), "XAUUSDPattern", "candles_m5.csv"),
)
CSV_FULL = CSV_ROLLING.replace("candles_m5.csv", "candles_m5_full.csv")
CSV_BACKFILL = CSV_ROLLING.replace("candles_m5.csv", "backfill_m5.csv")   # keluaran EA tester (2016-sekarang)


def upsert_csv(conn, path: str, min_t: int = 0) -> tuple[int, int]:
    """Upsert baris CSV dengan t >= min_t. Return (imported, skipped_ok)."""
    if not os.path.isfile(path):
        return 0, 0
    cur = conn.cursor()
    imported = skipped = 0
    batch = []
    _SQL = ("INSERT OR REPLACE INTO candles_m5 (t, o, h, l, c, tv, spread, dt_created)"
            " VALUES (?,?,?,?,?,?,?,?)")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) < 5:
                continue
            try:
                t = int(row[0])
                o, h, l, c_ = (float(x) for x in row[1:5])
                tv = int(row[5]) if len(row) > 5 and row[5] else 0
                sp = int(row[7]) if len(row) > 7 and row[7] else 0
            except (ValueError, IndexError):
                continue  # baris sisa tidak valid / tulis sebagian
            if t < min_t:
                skipped += 1
                continue
            dt_str = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            batch.append((t, o, h, l, c_, tv, sp, dt_str))
            if len(batch) >= 50_000:
                cur.executemany(_SQL, batch)
                imported += len(batch)
                batch.clear()
    if batch:
        cur.executemany(_SQL, batch)
        imported += len(batch)
    return imported, skipped


_bf_mtime = 0.0   # mtime backfill_m5.csv yang sudah terimport

def import_backfill(conn) -> int:
    """Import ekor backfill_m5.csv (sumber live EA Backfill di chart).
    Hanya bila file berubah (mtime), dan hanya baris barunya (t >= db_max-300)
    supaya run per-candle tidak memindai ulang ratusan ribu baris.
    Invoice penuh (semua baris) hanya terjadi pada pemanggilan pertama."""
    global _bf_mtime
    if not os.path.isfile(CSV_BACKFILL):
        return 0
    m = os.path.getmtime(CSV_BACKFILL)
    if m <= _bf_mtime:
        return 0
    cur = conn.cursor()
    db_max = cur.execute("SELECT MAX(t) FROM candles_m5").fetchone()[0]
    min_t = max(0, (db_max or 0) - 300)
    imported, _ = upsert_csv(conn, CSV_BACKFILL, min_t=min_t)
    _bf_mtime = m
    return imported


def backfill(verbose: bool = True) -> dict:
    """Jalankan kedua import. Return ringkasan untuk scheduler & CLI."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # ambang sementara utk rolling: supaya file full (memuat baris sama) tidak
    # import dua kali tanpa kebutuhan; rolling selalu upsert penuh (murah, 5000 bar)
    full_rows, _ = upsert_csv(conn, CSV_FULL)
    roll_rows, _ = upsert_csv(conn, CSV_ROLLING)
    # CSV khusus backfill dari tester (backfill_m5.csv) — upsert juga; file bisa besar
    # (jutaan baris) sehingga hanya diimport bila mtime berubah (dihдler ogup di upsert_csv).
    backfill_rows = import_backfill(conn)
    conn.commit()
    before = full_rows + roll_rows + backfill_rows

    total = cur.execute("SELECT COUNT(*) FROM candles_m5").fetchone()[0]
    lo, hi = cur.execute("SELECT MIN(t), MAX(t) FROM candles_m5").fetchone()
    conn.close()
    out = {
        "ok": True,
        "full_imported": full_rows,
        "rolling_imported": roll_rows,
        "backfill_imported": backfill_rows,
        "total_bars": total,
        "range_t": [lo, hi],
    }
    if verbose:
        span_days = ((hi - lo) / 86400) if lo else 0
        print(f"✅ {total} candle M5 di DB "
              f"(+{before} upsert; rentang {span_days:.1f} hari)")
    return out


if __name__ == "__main__":
    backfill()
