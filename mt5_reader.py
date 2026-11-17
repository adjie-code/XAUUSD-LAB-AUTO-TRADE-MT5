#!/usr/bin/env python3
"""
XAUUSD Pattern Dashboard - Pembaca data candle MT5 (Fase 2)

Sumber: EA `XAUUSDPatternExporter.mq5` yang berjalan di chart XAUUSDc M5
di MT5 (container linux-mt5 / broker Exness). EA men-tulis CSV ke folder
FILE_COMMON milik MT5; modul ini membaca & mem-validiasinya.

Format CSV (dibuat EA, delimiter ';'):
  time;o;h;l;c;tick_volume;real_volume;spread
  time = unix epoch (detik, UTC) awal candle M5 yang SELESAI.

Mode riset-saja: modul ini pasif, tidak menyentuh MT5 selain membaca file.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

# Jalur Common/Files MT5 di host (mount container linux-mt5)
MT5_COMMON_FILES = os.environ.get(
    "MT5_COMMON_FILES",
    "/DATA/AppData/mt5-dockerized/linux/linux-mt5-data/wine-prefix/.mt5/"
    "drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files",
)
EA_FOLDER = os.path.join(MT5_COMMON_FILES, "XAUUSDPattern")
CSV_PATH = os.path.join(EA_FOLDER, "candles_m5.csv")
FULL_CSV_PATH = os.path.join(EA_FOLDER, "candles_m5_full.csv")
BACKFILL_CSV_PATH = os.path.join(EA_FOLDER, "backfill_m5.csv")   # sumber live (EA backfill di chart)
HEARTBEAT_PATH = os.path.join(EA_FOLDER, "heartbeat.txt")


@dataclass
class Candle:
    t: int  # epoch detik (UTC), awal candle
    o: float
    h: float
    l: float
    c: float
    tick_volume: int = 0
    spread: int = 0


# Kalau EA menulis heartbeat TANPA pemisah ';' (bug format), kita tetap
# bisa menyalin isiannya: [status][symbol][timeframe][bars][3 x epoch 10-digit].
# Contoh aktual: 'OKXAUUSDcM55000179386050017938608001793860800'
def _parse_flat(line: str) -> list[str] | None:
    """Coba salin isi heartbeat yang menempel tanpa ';'. Return list field atau None."""
    m = re.search(
        r"^(?P<status>[A-Z][A-Z0-9_]{1,15}?)"
        r"(?P<symbol>[A-Z]{3,7}[A-Za-z]{0,2})"
        r"(?P<tf>M\d{1,2})"
        r"(?P<bars>\d{4,7})"
        r"(?P<t1>\d{10})"
        r"(?P<t2>\d{10})"
        r"(?:\d{10})?$",
        line,
    )
    if not m:
        return None
    return [m.group("status"), m.group("symbol"), m.group("tf"),
            m.group("bars"), m.group("t1"), m.group("t2"), ""]


def heartbeat() -> dict:
    """Baca heartbeat.txt EA. Isi: status;symbol;timeframe;bars;last_close;synced;write_time.
    Toleran terhadap heartbeat yang ditulis tanpa pemisah ';' (fallback regex)."""
    out = {"installed": os.path.isdir(EA_FOLDER), "running": False,
           "status": "-", "symbol": "-", "bars": 0,
           "last_close": None, "synced": None, "age_sec": None}
    if not out["installed"]:
        out["status"] = "folder EA tidak ditemukan"
        return out
    try:
        with open(HEARTBEAT_PATH, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readline().strip().replace("\r", "").replace("\n", "")
        parts = raw.split(";") if ";" in raw else (_parse_flat(raw) or [])
        if len(parts) >= 7:
            out["status"] = parts[0] or "-"
            out["symbol"] = parts[1] or "-"
            out["timeframe"] = parts[2] or "-"
            out["bars"] = int(parts[3] or 0)
            out["last_close"] = int(parts[4]) if parts[4] else None
            out["synced"] = int(parts[5]) if parts[5] else None
            if out["synced"]:
                out["age_sec"] = max(0, int(time.time()) - out["synced"])
                # dianggap 'running' kalau EA sempat menulis & umur < 10 menit
                out["running"] = out["age_sec"] < 600
        else:
            out["status"] = f"format heartbeat tidak dikenali: {raw[:40]!r}"
    except FileNotFoundError:
        out["status"] = "EA belum menulis heartbeat (EA belum terpasang di chart?)"
    except Exception as e:  # noqa: BLE001
        out["status"] = f"heartbeat tidak terbaca: {e}"
    return out


def load_candles(max_bars: int = 5000) -> list[Candle]:
    """Baca & parse CSV candle M5 dari EA. Return list candle terurut naik (terlama->terbaru)."""
    return _load_csv(CSV_PATH, max_bars)


def load_backfill_candles(max_bars: int = 20000) -> list[Candle]:
    """Baca ekor CSV backfill (EA Backfill di chart live — sumber candle realtime)."""
    return _load_csv(BACKFILL_CSV_PATH, max_bars)


def load_full_candles() -> list[Candle]:
    """Baca CSV full-history (Fase 3, ditulis EA TryBackfill). Boleh sangat besar."""
    return _load_csv(FULL_CSV_PATH, max_bars=1_000_000)


def _load_csv(path: str, max_bars: int) -> list[Candle]:
    if not os.path.isfile(path):
        return []
    size = os.path.getsize(path)
    if size > 5_000_000 and max_bars and max_bars < 1_000_000:
        # file besar (mis. CSV backfill 10+ thn): cukup baca ekor — hemat IO 99%+
        block = (max_bars + 300) * 72   # est. ±72 byte/baris + aman
        with open(path, "rb") as f:
            f.seek(max(0, size - block))
            blob = f.read().decode("utf-8", errors="replace")
        lines = blob.splitlines()[1:]    # buang baris pertama (kemungkinan terpotong)
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    candles: list[Candle] = []
    for line in lines:
        parts = line.strip().split(";")
        if len(parts) < 5:
            continue
        try:
            t = int(parts[0])
            o, h, l, c = (float(parts[i]) for i in range(1, 5))
            tv = int(parts[5]) if len(parts) > 5 and parts[5] else 0
            sp = int(parts[7]) if len(parts) > 7 and parts[7] else 0
        except ValueError:
            continue  # baris tidak valid (sebagian tulis) diabaikan
        candles.append(Candle(t, o, h, l, c, tv, sp))
    # validasi urutan & duplikat
    candles.sort(key=lambda x: x.t)
    dedup: list[Candle] = []
    for cd in candles[-max_bars:]:
        if not dedup or cd.t != dedup[-1].t:
            dedup.append(cd)
    return dedup


def is_fresh(candles: list[Candle], max_age_sec: int = 12 * 60) -> bool:
    """Fresh = candle terakhir cukup dekat (lebar 1-2 candle M5)."""
    if not candles:
        return False
    return max(0, time.time() - candles[-1].t) <= max_age_sec
