#!/usr/bin/env python3
"""
Backfill historis XAUUSD (M5) dari Dukascopy — HTTP stdlib, tanpa instalasi.

Cara kerja:
  * Unduh file tick per-jam ".bi5" (LZMA) dari datafeed.dukascopy.com
    (IP di-pin via /etc/hosts; bulan pada URL 0-based).
  * Record tick = 5 x int32 BIG-ENDIAN (20 byte):
      (ms_offset_dalam_jam, bid, ask, vol_bid, vol_ask), harga x1000.
  * Agregasi jadi candle M5 (tEpoch, O/H/L/C sisi bid, jumlah tik).
  * Upsert langsung ke data/patterns.db tabel candles_m5 hanya untuk candle
    yang LEBIH LAMA dari data existing (t < FLOOR) — data live tidak disentuh.
  * State resume JSON: jika mati/restart, dijalankan ulang langsung lanjut.

Penggunaan:
    python3 backfill_dukascopy.py [START_YYYY] [END_YYYY]
    default: mulai 2016, sampai 1 hari sebelum candle pertama yang ada di DB.

Etika unduh: 4 worker, jeda antar request + jitter, retry backoff utk 429/503,
kept-alive per thread, file kosong (akhir pekan/libur) dilewati cepat.
"""

import datetime as dt
import http.client
import json
import lzma
import os
import random
import sqlite3
import ssl
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

BASE_HOST = "datafeed.dukascopy.com"
INSTRUMENT = "XAUUSD"
TICK_STRUCT = struct.Struct(">5i")          # ms, bid, ask, vol_b, vol_a (BE)
PRICE_DIV = 1000.0
BUCKET = 300                                # M5
START_DEFAULT = 2016
DB_PATH = "data/patterns.db"
STATE_PATH = "backfill_state.json"
WORKERS = 4
REQUEST_GAP = 0.28                          # jeda antar request per worker
MAX_RETRIES = 6

TLS_CTX = ssl.create_default_context()
UA_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DukaFetch/1.0",
           "Accept": "*/*", "Connection": "keep-alive"}

_tls = threading.local()
_lock = threading.Lock()                    # proteksi stats & state file
STATS = {"files": 0, "hours_with_data": 0, "ticks": 0, "fail_files": 0}


# --------------------------------------------------------------------------- #
# HTTP per-thread
# --------------------------------------------------------------------------- #
def _conn():
    if getattr(_tls, "conn", None) is None:
        _tls.conn = http.client.HTTPSConnection(BASE_HOST, timeout=30, context=TLS_CTX)
    return _tls.conn


def _close_conn():
    c = getattr(_tls, "conn", None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
        _tls.conn = None


def fetch_hour(day: dt.date, hour: int) -> bytes:
    """Unduh 1 file .bi5 jam. Return bytes (boleh b''), atau raise RuntimeError."""
    url = (f"/datafeed/{INSTRUMENT}/{day.year - 2000:02d}/"
           f"{day.month - 1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5")
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            c = _conn()
            c.request("GET", url, headers=UA_HDRS)
            r = c.getresponse()
            body = r.read()
            if r.status in (200, 204):
                return body
            if r.status == 404:
                return b""                     # jam tanpa data → dilewati
            last = f"HTTP {r.status}"
            _close_conn()
        except Exception as e:
            last = str(e)
            _close_conn()
        time.sleep(min(2 ** attempt, 20) + random.random())
    raise RuntimeError(f"fetch {url}: {last}")


# --------------------------------------------------------------------------- #
# Agregasi tick → M5
# --------------------------------------------------------------------------- #
def bi5_to_m5(raw: bytes, base_t: int) -> dict:
    """1 file .bi5 → {t_epoch: [o,h,l,c,count]} untuk rentang 1 jam.
    base_t = epoch awal jam. Record BE 20 byte, harga x1000."""
    try:
        raw = lzma.decompress(raw)
    except lzma.LZMAError:
        return {}
    out = {}
    unpack_from = TICK_STRUCT.unpack_from
    size = TICK_STRUCT.size
    for i in range(len(raw) // size):
        ms, bid, ask, _vb, _va = unpack_from(raw, i * size)
        if ms < 0 or ms >= 3_600_000:          # offset di luar jam → buang
            continue
        t = base_t + ms // 1000
        key = t - t % BUCKET
        price = min(bid, ask) / PRICE_DIV      # sisi bid (dari dua harga)
        slot = out.get(key)
        if slot is None:
            out[key] = [price, price, price, price, 1]
        else:
            if price < slot[2]:
                slot[2] = price
            if price > slot[1]:
                slot[1] = price
            slot[3] = price
            slot[4] += 1
    return out


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def db_floor_ts(db: sqlite3.Connection) -> int:
    """T candle paling lama di DB (FLOOR)."""
    row = db.execute("SELECT MIN(t) FROM candles_m5").fetchone()
    if row and row[0]:
        return row[0]
    raise SystemExit("DB belum memuat data; jalankan python3 import_csv.py dulu.")


def upsert_day(db: sqlite3.Connection, day_rows: dict, floor_t: int) -> int:
    """Insert/replace candle yang t < floor_t. Return jumlah baris ter-eksekusi."""
    if not day_rows:
        return 0
    rows = [(t, round(r[0], 2), round(r[1], 2), round(r[2], 2), round(r[3], 2), r[4])
            for t, r in day_rows.items() if t < floor_t]
    if not rows:
        return 0
    with db:
        db.executemany(
            "INSERT OR REPLACE INTO candles_m5"
            " (t,o,h,l,c,tv,spread,created_at) VALUES (?,?,?,?,?,?,'0','')",
            [(t, o, h, l, c, tv) for t, o, h, l, c, tv in rows])
    return len(rows)


def load_state():
    if os.path.isfile(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE_PATH)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def main():
    # argv[1] boleh tahun (2016) atau tanggal ISO (2025-06-05); default 2016-01-01
    start_year = (int(sys.argv[1].split("-")[0])
                  if len(sys.argv) > 1 else START_DEFAULT)
    db = sqlite3.connect(DB_PATH)
    floor_t = db_floor_ts(db)
    end = dt.datetime.fromtimestamp(floor_t - 1, dt.timezone.utc).date()
    if len(sys.argv) > 1 and "-" in sys.argv[1]:
        start = dt.date.fromisoformat(sys.argv[1])
    else:
        start = dt.date(start_year, 1, 1)

    st = load_state()
    if st.get("resume_day"):
        rd = dt.date.fromisoformat(st["resume_day"])
        if start < rd <= end:
            start = rd                          # lanjut dari hari terakhir belum selesai
    if end <= start:
        print("Tidak ada rentang for backfill (DB sudah menutupi rentang ini).")
        return

    days = list(iter_days(start, end))
    total_files = len(days) * 24
    print(f"Backfill {INSTRUMENT} M5 Dukascopy: {start} → {days[-1]}")
    print(f"{len(days)} hari = {total_files} file jam. State: {STATE_PATH}")
    import datetime as _d
    print(f"FLOOR DB = {_d.datetime.fromtimestamp(floor_t, _d.timezone.utc):%Y-%m-%d %H:%M} UTC"
          f" (baris baru tidak masuk bila t >= FLOOR)")

    st.setdefault("rows_imported", 0)
    task_q = Queue()
    for d in days:                              # hari terlama dulu, enak buat resume
        task_q.put(d)

    save_state(st)

    def worker():
        while True:
            try:
                day = task_q.get_nowait()
            except Empty:
                return
            hour_maps = []
            for h in range(24):
                try:
                    raw = fetch_hour(day, h)
                except Exception:
                    with _lock:
                        STATS["fail_files"] += 1
                        STATS["files"] += 1
                    continue                    # 1 jam gagal tidak mematikan hari
                base_t = int(dt.datetime(day.year, day.month, day.day, h,
                                         tzinfo=dt.timezone.utc).timestamp())
                mapping = bi5_to_m5(raw, base_t)
                hour_maps.append(mapping)
                with _lock:
                    STATS["files"] += 1
                    if mapping:
                        STATS["hours_with_data"] += 1
                        STATS["ticks"] += sum(v[4] for v in mapping.values())
                time.sleep(REQUEST_GAP + random.random() * 0.1)

            # gabung 24 jam jadi 1 hari (slot v[4] dgn tick count)
            day_rows = {}
            for m in hour_maps:
                for t, slot in m.items():
                    cur = day_rows.get(t)
                    if cur is None:
                        day_rows[t] = slot
                    else:
                        cur[1] = max(cur[1], slot[1])
                        cur[2] = min(cur[2], slot[2])
                        cur[3] = slot[3]
                        cur[4] += slot[4]
            try:
                rows = upsert_day(db, day_rows, floor_t)
            except Exception as e:
                print(f"DB error {day}: {e}")
                rows = 0
            with _lock:
                st["rows_imported"] += rows
                st["resume_day"] = (day + dt.timedelta(days=1)).isoformat()
                save_state(st)
                if STATS["files"] % STATS_EVERY < WORKERS + 1:
                    print(f"  ... {STATS['files']}/{total_files} file, "
                          f"{STATS['ticks']:,} tik, {st['rows_imported']:,} candle",
                          flush=True)

    pool = ThreadPoolExecutor(max_workers=WORKERS)
    for _ in range(WORKERS):
        pool.submit(worker)
    try:
        pool.shutdown(wait=True)
    except KeyboardInterrupt:
        print("\nDihentikan — state resume tersimpan; jalankan ulang utk lanjut.")
    save_state(st)

    print("\nSELESAI.")
    print(f"  file jam diproses : {STATS['files']}/{total_files}")
    print(f"  gagal             : {STATS['fail_files']}")
    print(f"  jam dengan data   : {STATS['hours_with_data']}")
    print(f"  total tik         : {STATS['ticks']:,}")
    print(f"  candle ter-impor  : {st['rows_imported']:,} (akumulasi)")
    row = db.execute("SELECT COUNT(*), MIN(t), MAX(t) FROM candles_m5").fetchone()
    if row[0]:
        t0 = dt.datetime.fromtimestamp(row[1], dt.timezone.utc)
        t1 = dt.datetime.fromtimestamp(row[2], dt.timezone.utc)
        print(f"  DB candles_m5     : {row[0]:,} bar  ({t0:%Y-%m-%d} → {t1:%Y-%m-%d})")


def iter_days(start: dt.date, end: dt.date):
    d = start
    while d < end:
        yield d
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
