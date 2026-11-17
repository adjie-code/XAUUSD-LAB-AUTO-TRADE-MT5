#!/usr/bin/env python3
"""
XAUUSD Pattern Dashboard — Backend (Fase 1 s/d 8).

- Fase 1: dashboard dasar (fallback dummy tetap dipertahankan, BERLABEL JELAS).
- Fase 2: data asli MT5 via EA exporter (mt5_reader).
- Fase 3: backfill full-history EA -> SQLite (import_csv.upsert_csv).
- Fase 4/5: engine pola + estimasi (pattern_engine.engine).
- Fase 6: scheduler thread — tiap candle M5 baru selesai, hitung ulang;
  jalankan run resmi tiap update_every_n_candles candle.
- Fase 7: /api/history — riwayat run prediksi.
- Fase 8: evaluasi otomatis -> accuracy_history; /api/accuracy agregat.

Tidak ada library eksternal (Python stdlib + sqlite3).
"""
import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import mt5_reader
import pattern_engine
import executor
import backtest_api
import ea_generator
import strategy_monitor
import broker_login
from import_csv import CSV_ROLLING, CSV_FULL, import_backfill, upsert_csv

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
CONFIG_PATH = os.path.join(ROOT, "config.json")
DB_PATH = os.environ.get("DASHBOARD_DB", os.path.join(ROOT, "data", "patterns.db"))
BROKER_LOGIN_REQUIRED = os.environ.get("BROKER_LOGIN_REQUIRED", "0").lower() in ("1", "true", "yes", "on")
_BROKER_ATTEMPTS = {}
AUTH_COOKIE = "xau_admin"
SESSION_SECRET_PATH = os.path.join(ROOT, "data", ".session_secret")

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}
PERIOD_SEC = 300          # M5 = 300 detik (roadmap: timeframe fix M5)
MAX_HISTORY_BARS = 2_000_000   # 20 tahun M5; DB 2006-2026


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Autentikasi admin — melindungi /api/config dan panel parameter.
# Tidak memakai library eksternal: cookie sesi ditandatangani HMAC-SHA256,
# password disimpan sebagai hash PBKDF2 di config.json (bukan plaintext).
# ---------------------------------------------------------------------------
def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

def _load_session_secret():
    """Baca/buat secret sesi persisten (0600) agar login tetap valid setelah restart."""
    try:
        os.makedirs(os.path.dirname(SESSION_SECRET_PATH), exist_ok=True)
        if os.path.isfile(SESSION_SECRET_PATH):
            with open(SESSION_SECRET_PATH, "rb") as f:
                data = f.read(32)
            if len(data) == 32:
                return data
        data = secrets.token_bytes(32)
        fd = os.open(SESSION_SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            os.chmod(SESSION_SECRET_PATH, 0o600)
        except OSError:
            pass
        return data
    except OSError as e:  # fallback aman: sesi berlaku sampai service restart
        sys.stderr.write(f"[auth] session secret: {type(e).__name__}: {e}\n")
        return secrets.token_bytes(32)

_SESSION_SECRET = _load_session_secret()

def _auth_cfg():
    try:
        return load_config().get("auth") or {}
    except Exception:  # noqa: BLE001
        return {}

def auth_username():
    return os.environ.get("XAUUSD_DASH_USER") or _auth_cfg().get("username") or "admin"

def _session_hours():
    try:
        hours = int(_auth_cfg().get("session_hours", 12))
    except (TypeError, ValueError):
        hours = 12
    return max(1, min(72, hours))

def hash_password(password, iterations=260_000):
    """Buat hash PBKDF2-SHA256 untuk disimpan di config.json."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(digest)}"

def verify_password(password):
    """Verifikasi password terhadap hash di config; env var boleh menimpa."""
    env_pass = os.environ.get("XAUUSD_DASH_PASS")
    if env_pass is not None:
        return hmac.compare_digest(str(password).encode("utf-8"),
                                   str(env_pass).encode("utf-8"))
    encoded = _auth_cfg().get("password_hash") or ""
    try:
        algo, iteration_s, salt_s, hash_s = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iteration_s)
        if iterations < 100_000:
            return False
        salt = _b64d(salt_s)
        expected = _b64d(hash_s)
        actual = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:  # hash/config rusak harus gagal tertutup, bukan error 500
        return False

def verify_login(username, password):
    user_ok = hmac.compare_digest(str(username or "").encode("utf-8"),
                                  str(auth_username()).encode("utf-8"))
    pass_ok = verify_password(password)   # tetap dihitung walau user salah (anti-timing)
    return user_ok and pass_ok

def create_session(username):
    expires = int(time.time()) + _session_hours() * 3600
    payload = {"u": username, "iat": int(time.time()), "exp": expires}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_SESSION_SECRET, body, hashlib.sha256).digest()
    return _b64e(body) + "." + _b64e(sig), expires

def parse_session(token):
    if not token or "." not in token:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64d(body_b64)
        sig = _b64d(sig_b64)
        expected = hmac.new(_SESSION_SECRET, body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(body.decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        if not hmac.compare_digest(str(payload.get("u", "")).encode("utf-8"),
                                   str(auth_username()).encode("utf-8")):
            return None
        return payload
    except Exception:  # noqa: BLE001 — token rusak/kedaluwarsa harus dianggap tidak login
        return None

# Pembatas percobaan login sederhana (in-memory, 8 gagal / 15 menit per IP).
_AUTH_FAIL_LOCK = threading.Lock()
_AUTH_FAILS = {}
_AUTH_WINDOW_SEC = 15 * 60
_AUTH_MAX_FAILS = 8

def login_allowed(ip):
    now = time.time()
    with _AUTH_FAIL_LOCK:
        arr = [t for t in _AUTH_FAILS.get(ip, []) if now - t < _AUTH_WINDOW_SEC]
        _AUTH_FAILS[ip] = arr
        return len(arr) < _AUTH_MAX_FAILS

def login_failed(ip):
    now = time.time()
    with _AUTH_FAIL_LOCK:
        arr = [t for t in _AUTH_FAILS.get(ip, []) if now - t < _AUTH_WINDOW_SEC]
        arr.append(now)
        _AUTH_FAILS[ip] = arr

def login_succeeded(ip):
    with _AUTH_FAIL_LOCK:
        _AUTH_FAILS.pop(ip, None)

def sanitized_config(cfg):
    safe = dict(cfg)
    safe.pop("auth", None)
    return safe


def now_utc():
    return datetime.now(timezone.utc)

def ms_utc(dt):
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Dummy generator (fallback Fase 1 — HARUS berlabel dummy di UI)
# ---------------------------------------------------------------------------
def generate_history(n, seed=20261105, end_time=None):
    rnd = random.Random(seed)
    if end_time is None:
        base = now_utc().replace(second=0, microsecond=0, tzinfo=timezone.utc)
        end_time = base.replace(minute=(base.minute // 5) * 5)
    price = 4002.50
    candles = []
    for i in range(n):
        t = int((end_time - timedelta(seconds=PERIOD_SEC * (n - 1 - i))).timestamp())
        open_p = price
        close_p = round(open_p + rnd.uniform(-0.9, 1.0), 2)
        high_p = round(max(open_p, close_p) + rnd.uniform(0.05, 1.4), 2)
        low_p = round(min(open_p, close_p) - rnd.uniform(0.05, 1.2), 2)
        price = close_p
        candles.append({"t": t, "o": round(open_p, 2), "h": high_p, "l": low_p, "c": close_p})
    return candles


# ---------------------------------------------------------------------------
# Pencarian data — sumber resmi: SQLite (diisi dari EA CSV, Fase 3)
# ---------------------------------------------------------------------------
def db_connect():
    return sqlite3.connect(DB_PATH, timeout=30)

def load_db_candles(limit=MAX_HISTORY_BARS):
    conn = db_connect()
    rows = conn.execute(
        "SELECT t, o, h, l, c, tv, spread FROM candles_m5 ORDER BY t DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    from mt5_reader import Candle
    return [Candle(*r) for r in reversed(rows)]

def mt5_state():
    """Status MT5 + pilih sumber candle LIVE paling segar (rolling / backfill EA).

    Sumber yang valid: file dengan candle terakhir paling baru. EA Backfill di
    chart live menulis backfill_m5.csv; EA Exporter menulis candles_m5.csv.
    """
    hb = mt5_reader.heartbeat()
    candles = mt5_reader.load_candles()
    source = "candles_m5.csv"
    # backfill_m5.csv bisa besar (~35 MB) — cukup ekor 20 ribu bar terakhir utk live
    if os.path.isfile(mt5_reader.BACKFILL_CSV_PATH):
        bf = mt5_reader.load_backfill_candles()
        if bf and (not candles or bf[-1].t >= candles[-1].t):
            candles = bf
            source = "backfill_m5.csv"
    hb["csv_exists"] = os.path.isfile(mt5_reader.CSV_PATH)
    hb["backfill_exists"] = os.path.isfile(mt5_reader.BACKFILL_CSV_PATH)
    hb["source_file"] = source
    hb["csv_bars"] = len(candles)
    hb["bars"] = len(candles)   # bars = yang benar-benar dipakai (bukan angka heartbeat)
    hb["fresh"] = mt5_reader.is_fresh(candles)
    hb["last_candle"] = None
    if hb["csv_exists"]:
        hb["csv_mtime"] = int(os.path.getmtime(mt5_reader.CSV_PATH))
    if candles:                 # apa pun sumber filenya (rolling/backfill)
        hb["last_candle"] = {"t": candles[-1].t, "o": candles[-1].o,
                             "h": candles[-1].h, "l": candles[-1].l,
                             "c": candles[-1].c}
    hb["full_exists"] = os.path.isfile(mt5_reader.FULL_CSV_PATH)
    if hb["full_exists"]:
        m = os.path.getmtime(mt5_reader.FULL_CSV_PATH)
        if m != _full_cache["mtime"]:
            with open(mt5_reader.FULL_CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
                _full_cache["bars"] = sum(1 for line in f if line.strip())
            _full_cache["mtime"] = m
    hb["full_bars"] = _full_cache["bars"]
    return hb, candles


def mt5_symbol(candles=None, fallback=None):
    """Simbol dgn fallback heuristik (heartbeat terverifikasi maupun data)."""
    hb = mt5_reader.heartbeat()
    if hb["symbol"] not in (None, "-", ""):
        return hb["symbol"]
    return f"{fallback or 'XAUUSD'} (est.)"


# ---------------------------------------------------------------------------
# Fase 3: import incremental  (dipanggil scheduler)
# ---------------------------------------------------------------------------
_full_state = {"mtime": 0.0, "imported": None}   # state file full (importer)
_full_cache = {"mtime": 0.0, "bars": 0}          # cache jumlah baris full (status)

def import_new(force=False):
    """Upsert candle baru ke SQLite. Return ringkas import."""
    conn = db_connect()
    cur = conn.cursor()
    db_max = cur.execute("SELECT MAX(t) FROM candles_m5").fetchone()[0]
    db_min = cur.execute("SELECT MIN(t) FROM candles_m5").fetchone()[0]

    ri = fi = 0
    # Full history: import bila file baru/berubah atau DB masih kosong.
    # PENTING: min_t = 0 — bagian LAMA full CSV justru yang paling berharga
    # (data rolling hanya menyanggut ~25 hari ke belakang).
    if os.path.isfile(CSV_FULL):
        m = os.path.getmtime(CSV_FULL)
        if force or db_max is None or m != _full_state["mtime"]:
            fi = upsert_csv(conn, CSV_FULL)[0]
            _full_state["mtime"] = m
    # Rolling: sesekali candle baru saja
    if os.path.isfile(CSV_ROLLING):
        if db_max is None and not os.path.isfile(CSV_FULL):
            ri = upsert_csv(conn, CSV_ROLLING)[0]
        elif db_max is not None:
            ri = upsert_csv(conn, CSV_ROLLING, min_t=db_max)[0]
    # Backfill (EA Backfill di chart live): ekor baru saja — sumber candle realtime
    bi = import_backfill(conn)
    conn.commit()
    stats = cur.execute("SELECT COUNT(*), MIN(t), MAX(t) FROM candles_m5").fetchone()
    conn.close()
    return {"rolling": ri, "full": fi, "backfill": bi,
            "bars": stats[0], "range_t": [stats[1], stats[2]]}


# ---------------------------------------------------------------------------
# Fase 4/5 + 6: engine run + scheduler  (thread aman)
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_result = None
        self.last_error = None
        self.run_count = 0
        self._bootstrapped = False   # agar hasil analisa tetap tampil walau EA belum live
        self.stop = threading.Event()

    def run(self, force=False):
        """Eksekusi satu run resmi. Dipanggil scheduler maupun bootstrap."""
        cfg = load_config()
        with self.lock:
            try:
                candles = load_db_candles()
                try:
                    N = int(cfg.get("candles_per_pattern", 10))
                except (TypeError, ValueError):
                    N = 10
                N = max(5, min(60, N))
                if len(candles) < 2 * N:
                    self.last_error = f"data candle di DB kurang dari {2 * N}"
                    self.last_result = None
                    return None
                prev = None
                if not force:
                    conn = db_connect()
                    prev = conn.execute(
                        "SELECT last_candle_t FROM engine_runs ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    conn.close()
                    if prev and prev[0] >= candles[-1].t:
                        return self.last_result      # candle belum berubah
                result = pattern_engine.engine(candles, cfg)
                if result["best_similarity"] is None:
                    result["predicted"] = []          # tidak ada pola >= threshold
                # sisi waktu estimasi (WIB -1 dst.): candle berikutnya
                for j, p in enumerate(result["predicted"]):
                    if p["t"] is None and p["c"] is not None:
                        p["t"] = result["last_candle_t"] + (j + 1) * PERIOD_SEC
                run_at = now_utc().strftime("%Y-%m-%d %H:%M:%S")
                conn = db_connect()
                run_id = pattern_engine.persist(conn, result, run_at)
                conn.close()
                result["run_id"] = run_id
                result["run_at"] = run_at
                self.last_result = result
                self.last_error = None
                self.run_count += 1
                # Fase 8: evaluasi run lama yang sudah matang
                evaluate_ready(result["last_candle_t"])
                # Eksekutor (DEMO ONLY): tawarkan sinyal ke EA bila auto_trade
                # enabled di config. Default mati — selalu aman.
                try:
                    executor.publish(result, candles[-1], load_config(),
                                     candles)
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write(f"[executor] {type(e).__name__}: {e}\n")
                return result
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                sys.stderr.write(f"[engine] ERROR: {self.last_error}\n")
                return None

    def loop(self):
        """Fase 6: tiap-20 detik cek candle baru; run tiap N candle selesai."""
        last_seen_t = 0
        candles_completed = 0
        while not self.stop.is_set():
            try:
                # Fase 3: import incremental tiap tick (murah — dijaga mtime):
                # candle live dari EA Backfill/Exporter masuk DB sebelum engine run.
                try:
                    import_new()
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write(f"[scheduler] import {type(e).__name__}: {e}\n")
                state, candles = mt5_state()
                if state["fresh"] and candles:
                    t = candles[-1].t
                    if t != last_seen_t:
                        candles_completed += max(0, (t - last_seen_t) // PERIOD_SEC) if last_seen_t else 0
                        last_seen_t = t
                        cfg = load_config()
                        try:
                            n = max(1, int(cfg.get("update_every_n_candles", 10) or 10))
                        except (TypeError, ValueError):
                            n = 10
                        if candles_completed >= n or self.run_count == 0:
                            self.run()
                            candles_completed = 0
                            # DB bisa sudah punya run utk candle ini (server restart):
                            # run() non-force akan me-return None -> paksa satu run
                            # agar UI tidak menampilkan prediksi kosong/dummy.
                            if self.last_result is None:
                                self.run(force=True)
                elif not self._bootstrapped:
                    # Server baru hidup dan EA belum menulis candle: jalankan satu
                    # analisa dari data DB supaya UI/table/panel tidak kosong.
                    self._bootstrapped = True
                    try:
                        self.run(force=True)   # force: candle bisa saja sudah pernah dianalisa
                    except Exception as e:  # noqa: BLE001
                        sys.stderr.write(f"[scheduler] bootstrap {type(e).__name__}: {e}\n")
                time.sleep(20)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"[scheduler] {type(e).__name__}: {e}\n")
                time.sleep(20)

def mt5_server_offset_hours(now=None):
    """Offset waktu server broker MT5 dari UTC, gaya klasik MetaQuotes:
    server menyejajarkan jam 00:00 = 17:00 New York.
    - NY DST (Minggu ke-2 Maret s/d Minggu ke-1 November): GMT+3
    - sisa tahun (winter): GMT+2
    Dipakai supaya jam di dashboard == jam di chart MT5 (HP/VPS)."""
    import datetime as _dt
    _now = now or _dt.datetime.now(_dt.timezone.utc)
    d = _now.date()
    def _nth_sunday(y, m, n):
        first = _dt.date(y, m, 1)
        return first + _dt.timedelta(days=((6 - first.weekday()) % 7) + 7 * (n - 1))
    dst_start = _nth_sunday(d.year, 3, 2)
    dst_end = _nth_sunday(d.year, 11, 1)
    return 3 if dst_start <= d < dst_end else 2


def market_closed_window(now_ts=None):
    """Akhir pekan: emas tutup Jumat ±22:00 UTC s/d buka Minggu ±22:00 UTC.
    WIB: tutup Sabtu ±05:00, buka Senin ±05:00."""
    import datetime as _dt
    now = _dt.datetime.fromtimestamp(now_ts if now_ts else time.time(),
                                     _dt.timezone.utc)
    wd = now.weekday()  # Senin=0 ... Jumat=4, Sabtu=5, Minggu=6
    if wd == 4 and now.hour >= 22:
        return True
    if wd == 5:
        return True
    if wd == 6 and now.hour < 22:
        return True
    return False


# evaluasi akurasi hanya dari run dengan metodologi baru (% perubahan dianchor).
# Run sebelum tanggal ini memakai metode lama (level absolut antar-era) yang
# hasilnya tidak bisa dibandingkan apple-to-apple.
ACCURACY_CUTOFF = "2026-11-08 00:00:00"


def evaluate_ready(last_complete_t):
    """Fase 8: bandingkan prediksi matang dgn candle aktual -> accuracy_history.
    Dedup via COUNT row per run (baris dimasukkan urut idx 0..9)."""
    conn = db_connect()
    c = conn.cursor()
    evaluated = 0
    try:
        runs = c.execute(
            "SELECT id, last_candle_t FROM engine_runs"
            " WHERE run_at >= ? ORDER BY id DESC LIMIT 200", (ACCURACY_CUTOFF,)
        ).fetchall()
        for run_id, base_t in runs:
            pred_start = base_t + PERIOD_SEC
            # harga acuan: candle sebelum prediksi dimulai (baseline level)
            baseline_row = c.execute(
                "SELECT c FROM candles_m5 WHERE t=? ORDER BY t ASC", (base_t,)
            ).fetchone()
            if not baseline_row:
                continue
            base_c = baseline_row[0]
            # dedup: bandingkan dgn JUMLAH prediksi run ini (N bisa 5-60, bukan
            # hardcode 10 — bug audit 12 Nov 2026).
            n_pred = c.execute(
                "SELECT COUNT(*) FROM predictions WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if n_pred == 0:
                continue
            done = c.execute(
                "SELECT COUNT(*) FROM accuracy_history WHERE match_id=?", (run_id,)
            ).fetchone()[0]
            if done >= n_pred:
                continue
            for row in c.execute(
                "SELECT rowid, idx, c FROM predictions WHERE run_id=? ORDER BY idx", (run_id,)
            ).fetchall():
                rowid, idx, predicted_c = row
                if idx < done:
                    continue                                  # sudah dievaluasi
                actual_t = pred_start + idx * PERIOD_SEC
                if last_complete_t is None or actual_t > last_complete_t:
                    continue                                  # belum matang
                act = c.execute(
                    "SELECT c FROM candles_m5 WHERE t=?", (actual_t,)
                ).fetchone()
                if not act:
                    continue
                # bandingkan % perubahan, bukan level harga absolut — pola historis
                # berulang dalam bentuk/arah, bukan level absolut.
                pred_chg_pct = round((predicted_c - base_c) / base_c * 100, 4) if base_c else None
                actual_chg_pct = round((act[0] - base_c) / base_c * 100, 4) if base_c else None
                err_pct = round(abs(actual_chg_pct - pred_chg_pct), 4) if pred_chg_pct is not None else None
                c.execute(
                    "INSERT INTO accuracy_history (match_id, idx, actual_close_price,"
                    " predicted_close_price, error_pct, evaluated_at) VALUES (?,?,?,?,?,?)",
                    (run_id, idx, act[0], predicted_c, err_pct,
                     now_utc().strftime("%Y-%m-%d %H:%M:%S")),
                )
                evaluated += 1
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[accuracy] {type(e).__name__}: {e}\n")
    conn.commit()
    conn.close()
    return evaluated


# ---------------------------------------------------------------------------
# handler HTTP
# ---------------------------------------------------------------------------
ENGINE = None   # diinisialisasi di main()

def dashboard_payload():
    """Composisi payload /api/dashboard (Fase 1..8)."""
    cfg = load_config()
    hb, mt5_candles = mt5_state()
    use_mt5 = bool(mt5_candles) and hb["fresh"]
    result = ENGINE.last_result if ENGINE and ENGINE.last_result else None
    try:
        N_cfg = max(5, min(60, int(cfg.get("candles_per_pattern", 10) or 10)))
    except (TypeError, ValueError):
        N_cfg = 10

    if use_mt5:
        src_candles = mt5_candles
        data_source = (f"MT5 EA — data asli broker ({hb.get('source_file', 'CSV')}), "
                       f"symbol={mt5_symbol(fallback=cfg.get('pair'))}")
        actual = [{"t": cd.t, "o": cd.o, "h": cd.h, "l": cd.l, "c": cd.c}
                  for cd in src_candles[-N_cfg:]]
    else:
        # Fallback JUJUR: pakai candle asli terakhir dari DB (pasar tutup / EA
        # tidak menulis). Data sintetis dummy hanya jika DB kosong.
        db_recent = None
        try:
            db_recent = load_db_candles(N_cfg)
        except Exception:  # noqa: BLE001
            db_recent = None
        if db_recent:
            actual = [{"t": cd.t, "o": cd.o, "h": cd.h, "l": cd.l, "c": cd.c}
                      for cd in db_recent[-N_cfg:]]
            if market_closed_window():
                data_source = ("PASAR TUTUP (akhir pekan) — ini candle penutupan "
                               "Jumat yang sama dengan harga di MT5. Bukan data "
                               "lama; pasar buka lagi Minggu ±22:00 UTC.")
            else:
                data_source = ("stale — candle terakhir dari DB (EA tidak menulis). "
                               "Cek EA/terminal MT5.")
        else:
            actual = generate_history(N_cfg)
            data_source = "dummy (EA MT5 belum berjalan — bukan data broker)"

    if result:
        predicted = result["predicted"]
        similarity = result["best_similarity"]
        matched_at = result["matches"][0]["pattern_start_t"] if result["matches"] else None
        sufficient = result["sufficient_data"]
        predict_mode = result.get("predict_mode") or "mean"
        predict_k = result.get("predict_k")
        band = result.get("band") or []
        direction_stats = result.get("direction") or []
        history = [{
            "generated_at": result["run_at"],
            "run_id": result["run_id"],
            "similarity_pct": similarity,
            "matched_pattern_time": matched_at,
            "direction": (None if not predicted or predicted[0]["c"] is None
                          else ("naik" if predicted[0]["c"] >= predicted[0]["o"] else "turun")),
            "mae_usd": None,
            "hit_target_p10": None,
        }]
        engine_meta = {
            "active": True, "run_at": result["run_at"],
            "n_matches": result["n_matches"],
            "bars_count": result["bars_count"],
            "top_matches": result["matches"][:max(1, min(100, int(cfg.get("top_patterns", 20) or 20)))],
            "error": None,
        }
    else:
        # Jujur: engine belum berjalan -> JANGAN tampilkan prediksi sintetis
        # (dulu dummy 4002.xx tampil seolah prediksi asli — bug audit 12 Nov).
        predicted = []
        similarity = None
        matched_at = None
        sufficient = False
        predict_mode = cfg.get("predict_mode", "mean")
        predict_k = None
        band, direction_stats = [], []
        history = []
        engine_meta = {
            "active": False, "run_at": None,
            "n_matches": 0, "bars_count": None,
            "top_matches": [],
            "error": ENGINE.last_error if ENGINE else "belum berjalan",
        }

    # --- Perbandingan visual (Fase 4/5 di UI): pola tercocok + 10 candle aktual setelahnya ---
    comparison = None
    if result and result.get("matches"):
        best = result["matches"][0]
        pst = best.get("pattern_start_t")
        if pst:
            conn_c = db_connect()
            try:
                rows = conn_c.execute(
                    "SELECT t,o,h,l,c,tv,spread FROM candles_m5 WHERE t>=? ORDER BY t ASC LIMIT 60",
                    (pst,)).fetchall()
                if len(rows) >= 2 * N_cfg:
                    comparison = {
                        "pattern_start_t": rows[0][0],
                        "follow_start_t": rows[N_cfg][0],
                        "similarity_pct": best.get("similarity_pct"),
                        "pattern_candles": [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4]}
                                            for r in rows[:N_cfg]],
                        "following_candles": [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4]}
                                              for r in rows[N_cfg:2 * N_cfg]],
                    }
            finally:
                conn_c.close()

    # --- Cakupan data (transparansi): rentang & jumlah candle di SQLite ---
    coverage = None
    conn_d = db_connect()
    try:
        n_bars, t_min, t_max = conn_d.execute(
            "SELECT COUNT(*), MIN(t), MAX(t) FROM candles_m5").fetchone()
        if n_bars and t_min and t_max:
            span_years = max(0.0, (t_max - t_min) / (365.0 * 86400.0))
            # baris yang diharap jika rentang itu penuh dikenal ~ 80% hari trading
            expected_in_span = int(span_years * 365 * 24 * 12 * 0.8)
            target_years = 20
            target_bars = int(target_years * 365 * 24 * 12 * 0.8)
            gap_pct = 1.0 - (n_bars / expected_in_span) if expected_in_span > 0 else 0.0
            coverage = {
                "bars": n_bars, "from": t_min, "to": t_max,
                "span_years": round(span_years, 2),
                "fill_pct": round(100.0 * min(1.0, (1.0 - max(0.0, gap_pct))), 1),
                "has_gap": gap_pct > 0.05,
                "target_years": target_years,
                "percent_of_target": round(100.0 * n_bars / target_bars, 1),
                "contiguous": abs(n_bars - expected_in_span) / max(1, expected_in_span) < 0.08,
            }
    finally:
        conn_d.close()

    return {
        "ok": True,
        "phase": int(cfg.get("phase", 1)),
        "data_source": data_source,
        "mt5": {"status": hb["status"], "running": hb["running"],
                "installed": hb["installed"], "symbol": hb["symbol"],
                "bars": hb["bars"], "fresh": hb["fresh"],
                "source_file": hb.get("source_file"),
                "full_bars": hb.get("full_bars"), "full_exists": hb.get("full_exists")},
        "pair": cfg["pair"],
        "timeframe": cfg["timeframe"],
        "prioritize_session": cfg.get("prioritize_session", "Asia"),
        "similarity_threshold_pct": cfg.get("similarity_threshold_pct", 70),
        "top_patterns": cfg.get("top_patterns", 20),
        "update_every_n_candles": cfg.get("update_every_n_candles", 10),
        "candles_per_pattern": N_cfg,
        "time_display": cfg.get("time_display", "MT5"),
        "time_offset_hours": (0 if cfg.get("time_display") == "UTC"
                              else 7 if cfg.get("time_display") == "WIB"
                              else mt5_server_offset_hours()),
        "generated_at": ms_utc(now_utc()),
        "similarity_pct": similarity,
        "matched_pattern_time": matched_at,
        "actual_candles": actual,
        "predicted_candles": predicted,
        "predict_mode": predict_mode,
        "predict_top_k": predict_k,
        "predict_band": band,          # p10/p90 per index (mode topk_median)
        "predict_direction": direction_stats,  # {n, up, down} per index
        "forecast": (result.get("forecast") if result else None),
        "trend": executor.LAST.get("trend"),   # tren SMA untuk filter saran/eksekusi
        "auto_trade_cfg": executor.cfg_public(),  # cermin aturan eksekutor utk tabel
        "history": history,
        "engine": engine_meta,
        "comparison": comparison,
        "coverage": coverage,
        "sufficient_data": sufficient,
    }


def candles_payload(count=200, before=None, after=None):
    """Candle historis utk chart interaktif (ala MT5): browsable dari DB 667rb bar."""
    conn = db_connect()
    c = conn.cursor()
    try:
        count = max(10, min(3000, int(count or 200)))
        q = "SELECT t,o,h,l,c,tv,spread FROM candles_m5"
        args = []
        if before:
            q += " WHERE t < ?"
            args.append(int(before))
        q += " ORDER BY t DESC LIMIT ?"
        args.append(count)
        rows = c.execute(q, args).fetchall()
        rows.reverse()
        oldest = rows[0][0] if rows else None
        return {
            "ok": True,
            "count": len(rows),
            "oldest_t": oldest,
            "candles": [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "tv": r[5]}
                        for r in rows],
        }
    finally:
        conn.close()


def history_payload(limit=20):
    """Fase 7: riwayat run prediksi terakhir."""
    conn = db_connect()
    c = conn.cursor()
    out = []
    rows = c.execute(
        "SELECT id, run_at, last_candle_t, bars_count, n_matches,"
        " best_similarity, data_sufficient FROM engine_runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    for run_id, run_at, base_t, bars, n_matches, best, suff in rows:
        p0 = c.execute(
            "SELECT o, c FROM predictions WHERE run_id=? AND idx=0", (run_id,)
        ).fetchone()
        direction = None
        if p0:
            direction = "naik" if p0[1] >= p0[0] else "turun"
        errs = c.execute(
            "SELECT AVG(error_pct), COUNT(*), AVG(ABS(actual_close_price - predicted_close_price))"
            " FROM accuracy_history WHERE match_id=?", (run_id,)
        ).fetchone()
        out.append({
            "run_id": run_id, "run_at": run_at,
            "last_candle_t": base_t, "bars_count": bars,
            "n_matches": n_matches, "similarity_pct": best,
            "sufficient_data": bool(suff),
            "direction": direction,
            "avg_error_pct": errs[0],
            "n_evaluated": errs[1],
            "avg_abs_error_usd": round(errs[2], 4) if errs[2] is not None else None,
        })
    conn.close()
    return {"ok": True, "history": out}


def accuracy_payload():
    """Akurasi live + uji historis model arah. Hanya run setelah cutoff."""
    import json as _json
    conn = db_connect()
    c = conn.cursor()
    e = c.execute(
        "SELECT COUNT(*), AVG(a.error_pct), AVG(ABS(a.actual_close_price - a.predicted_close_price)),"
        " SUM(CASE WHEN ABS(a.actual_close_price - a.predicted_close_price) <= 1.0 THEN 1 ELSE 0 END),"
        " SUM(CASE WHEN ABS(a.actual_close_price - a.predicted_close_price) <= 10.0 THEN 1 ELSE 0 END),"
        " SUM(CASE WHEN a.actual_close_price > 0 AND "
        " ABS(a.actual_close_price - a.predicted_close_price)/a.actual_close_price*100 <= 0.25 THEN 1 ELSE 0 END)"
        " FROM accuracy_history a JOIN engine_runs r ON r.id=a.match_id"
        " WHERE r.run_at >= ?", (ACCURACY_CUTOFF,)
    ).fetchone()
    max_idx = c.execute(
        "SELECT MAX(a.idx) FROM accuracy_history a JOIN engine_runs r"
        " ON r.id=a.match_id WHERE r.run_at >= ?", (ACCURACY_CUTOFF,)
    ).fetchone()[0]
    per_idx = []
    for idx in range((max_idx if max_idx is not None else 9) + 1):
        d = c.execute(
            "SELECT COUNT(*), AVG(a.error_pct),"
            " AVG(ABS(a.actual_close_price - a.predicted_close_price)) FROM accuracy_history a"
            " JOIN engine_runs r ON r.id=a.match_id WHERE a.idx=? AND r.run_at >= ?",
            (idx, ACCURACY_CUTOFF),
        ).fetchone()
        per_idx.append({"idx": idx, "n": d[0], "avg_error_pct": d[1],
                        "avg_abs_error_usd": round(d[2], 4) if d[2] is not None else None})

    def direction_stats(extra=""):
        q = ("SELECT COUNT(*), SUM(CASE WHEN "
             " (r.forecast_dir > 0 AND a.actual_close_price > b.c) OR "
             " (r.forecast_dir < 0 AND a.actual_close_price < b.c) "
             " THEN 1 ELSE 0 END) "
             "FROM accuracy_history a JOIN engine_runs r ON r.id=a.match_id "
             "JOIN candles_m5 b ON b.t=r.last_candle_t "
             "WHERE r.run_at >= ? AND r.forecast_dir IS NOT NULL AND r.forecast_dir <> 0" + extra)
        n, ok = c.execute(q, (ACCURACY_CUTOFF,)).fetchone()
        return (n or 0), (ok or 0)

    dl_n, dl_ok = direction_stats()
    dh_n, dh_ok = direction_stats(" AND r.forecast_confidence='high'")
    conn.close()

    validation = None
    vpath = os.path.join(ROOT, "data", "direction_validation.json")
    if os.path.isfile(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                validation = _json.load(f)
        except (OSError, ValueError):
            validation = None

    n_eval = e[0] or 0
    return {
        "ok": True,
        "n_evaluated": n_eval,
        "avg_error_pct": e[1],
        "avg_abs_error_usd": round(e[2], 4) if e[2] is not None else None,
        "hit_within_1usd_pct": round(e[3] / n_eval * 100, 2) if n_eval else None,
        "hit_within_10usd_pct": round(e[4] / n_eval * 100, 2) if n_eval else None,
        "hit_within_0_25pct": round(e[5] / n_eval * 100, 2) if n_eval else None,
        "avg_abs_error_pct": round(e[1], 4) if e[1] is not None else None,
        "direction_live_n": dl_n,
        "direction_live_hit_pct": round(100.0 * dl_ok / dl_n, 2) if dl_n else None,
        "direction_live_coverage_pct": round(100.0 * dl_n / n_eval, 2) if n_eval else None,
        "direction_high_n": dh_n,
        "direction_high_hit_pct": round(100.0 * dh_ok / dh_n, 2) if dh_n else None,
        "direction_validation": validation,
        "per_index": per_idx,
    }

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def end_headers(self):
        # hindari campur aduk cache browser saat file dashboard diperbarui
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def _index_html(self):
        """Sajikan index.html dgn cache-busting otomatis (?v=mtime) utk css/js."""
        from pathlib import Path
        p = Path(STATIC_DIR) / "index.html"
        html = p.read_text(encoding="utf-8")
        try:
            v_css = int((Path(STATIC_DIR) / "style.css").stat().st_mtime)
            v_js = int((Path(STATIC_DIR) / "app.js").stat().st_mtime)
            v_chart = int((Path(STATIC_DIR) / "interactive_chart.js").stat().st_mtime)
            html = html.replace('href="style.css"', f'href="style.css?v={v_css}"')
            html = html.replace('src="app.js"', f'src="app.js?v={v_js}"')
            html = html.replace('src="interactive_chart.js"', f'src="interactive_chart.js?v={v_chart}"')
        except OSError:
            pass
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _strategy_lab_html(self):
        """Sajikan halaman Strategy Lab dengan cache-busting aset lokal."""
        from pathlib import Path
        p = Path(STATIC_DIR) / "strategy-lab.html"
        html = p.read_text(encoding="utf-8")
        try:
            v_css = int((Path(STATIC_DIR) / "style.css").stat().st_mtime)
            v_lab_css = int((Path(STATIC_DIR) / "strategy-lab.css").stat().st_mtime)
            v_lab_js = int((Path(STATIC_DIR) / "strategy-lab.js").stat().st_mtime)
            html = html.replace('href="style.css"', f'href="style.css?v={v_css}"')
            html = html.replace('href="strategy-lab.css"',
                                f'href="strategy-lab.css?v={v_lab_css}"')
            html = html.replace('src="strategy-lab.js"',
                                f'src="strategy-lab.js?v={v_lab_js}"')
        except OSError:
            pass
        # Suntikkan data awal agar halaman langsung terisi tanpa menunggu fetch.
        try:
            data_path = Path(STATIC_DIR) / "strategy-lab.json"
            payload = json.dumps(json.loads(data_path.read_text(encoding="utf-8")),
                                 ensure_ascii=False, separators=(",", ":"))
            payload = payload.replace("</", "<\\/")
            marker = '<script src="strategy-lab.js'
            if marker in html:
                html = html.replace(
                    marker,
                    f'<script>window.__STRATEGY_LAB_DATA__={payload};</script>\n' + marker,
                    1)
        except (OSError, ValueError):
            pass
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _broker_login_html(self):
        """Halaman login kredensial MT5 (bukan login admin dashboard)."""
        from pathlib import Path
        p = Path(STATIC_DIR) / "broker-login.html"
        html = p.read_text(encoding="utf-8")
        try:
            v_css = int((Path(STATIC_DIR) / "style.css").stat().st_mtime)
            v_own = int((Path(STATIC_DIR) / "broker-login.css").stat().st_mtime)
            v_js = int((Path(STATIC_DIR) / "broker-login.js").stat().st_mtime)
            html = html.replace('href="style.css"', f'href="style.css?v={v_css}"')
            html = html.replace('href="broker-login.css"',
                                f'href="broker-login.css?v={v_own}"')
            html = html.replace('src="broker-login.js"',
                                f'src="broker-login.js?v={v_js}"')
        except OSError:
            pass
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _broker_redirect(self):
        self.send_response(302)
        self.send_header("Location", "/broker")
        self.end_headers()

    def _handle_broker_login(self):
        ip = self.client_address[0]
        now = time.time()
        attempts = [t for t in _BROKER_ATTEMPTS.get(ip, []) if now - t < 300]
        if len(attempts) >= 8:
            return self._json(429, {"ok": False,
                                    "error": "Terlalu banyak percobaan. Tunggu 5 menit."})
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 8192:
            return self._json(413, {"ok": False, "error": "Isi permintaan terlalu besar"})
        try:
            data = json.loads(self.rfile.read(length) if length else b"{}")
        except (ValueError, UnicodeDecodeError, RecursionError):
            return self._json(400, {"ok": False, "error": "Format permintaan tidak valid"})
        if not isinstance(data, dict):
            return self._json(400, {"ok": False, "error": "Format permintaan harus objek"})
        attempts.append(now)
        _BROKER_ATTEMPTS[ip] = attempts[-20:]
        try:
            result = broker_login.login(data)
        except ValueError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(502, {"ok": False,
                                    "error": f"{type(e).__name__}: {e}"})
        return self._json(200, result)

    def _handle_broker_logout(self):
        broker_login.logout()
        return self._json(200, {"ok": True})

    def _strategy_monitor_html(self):
        """Sajikan halaman monitor per strategi dengan cache-busting aset."""
        from pathlib import Path
        p = Path(STATIC_DIR) / "strategy-monitor.html"
        html = p.read_text(encoding="utf-8")
        try:
            v_css = int((Path(STATIC_DIR) / "style.css").stat().st_mtime)
            v_mon = int((Path(STATIC_DIR) / "strategy-monitor.css").stat().st_mtime)
            v_js = int((Path(STATIC_DIR) / "strategy-monitor.js").stat().st_mtime)
            html = html.replace('href="style.css"', f'href="style.css?v={v_css}"')
            html = html.replace('href="strategy-monitor.css"',
                                f'href="strategy-monitor.css?v={v_mon}"')
            html = html.replace('src="strategy-monitor.js"',
                                f'src="strategy-monitor.js?v={v_js}"')
        except OSError:
            pass
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_skill_doc(self):
        """Sajikan dokumen skill lokal secara read-only (hanya file teks)."""
        from pathlib import Path
        from urllib.parse import unquote
        rel = unquote(self.path[len("/skills/"):])
        base = (Path(ROOT) / "skills").resolve()
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self._json(404, {"ok": False, "error": "dokumen skill tidak ditemukan"})
        allowed = {".md", ".txt", ".json", ".yaml", ".yml"}
        if not target.is_file() or target.suffix.lower() not in allowed:
            return self._json(404, {"ok": False, "error": "dokumen skill tidak ditemukan"})
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload, headers=None):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or []):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    # ---- sesi admin -------------------------------------------------------
    def _cookie_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = SimpleCookie()
            jar.load(raw)
            morsel = jar.get(AUTH_COOKIE)
            return morsel.value if morsel else None
        except Exception:  # noqa: BLE001
            return None

    def _session_payload(self):
        return parse_session(self._cookie_token())

    def _auth_user(self):
        payload = self._session_payload()
        return payload.get("u") if payload else None

    def _require_auth(self):
        user = self._auth_user()
        if not user:
            self._json(401, {"ok": False, "error": "Masuk diperlukan untuk mengakses parameter"})
            return None
        return user

    def _handle_login(self):
        ip = self.client_address[0]
        if not login_allowed(ip):
            return self._json(429, {"ok": False,
                                    "error": "Terlalu banyak percobaan masuk. Coba lagi nanti."})
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 4096:
            return self._json(413, {"ok": False, "error": "Isi permintaan terlalu besar"})
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, UnicodeDecodeError, RecursionError):
            return self._json(400, {"ok": False, "error": "Format permintaan tidak valid"})
        if not isinstance(data, dict):
            return self._json(400, {"ok": False, "error": "Format permintaan harus berupa objek"})
        username = str(data.get("username") or "")
        password = str(data.get("password") or "")
        if not verify_login(username, password):
            login_failed(ip)
            time.sleep(0.25)                 # memperlambat brute force
            return self._json(401, {"ok": False,
                                    "error": "Nama pengguna atau kata sandi salah"})
        login_succeeded(ip)
        user = auth_username()
        token, expires = create_session(user)
        max_age = max(60, expires - int(time.time()))
        cookie = (f"{AUTH_COOKIE}={token}; Path=/; Max-Age={max_age}; "
                  "HttpOnly; SameSite=Strict")
        return self._json(200, {"ok": True, "user": user, "expires_at": expires},
                          headers=[("Set-Cookie", cookie)])

    def _handle_logout(self):
        cookie = f"{AUTH_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
        return self._json(200, {"ok": True}, headers=[("Set-Cookie", cookie)])

    # ---- Strategy Tester (backtest job) -----------------------------------
    def _handle_backtest_get(self):
        from urllib.parse import urlparse, unquote
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        # parts: ['api','backtest', ...]
        if len(parts) == 3 and parts[2] == "jobs":
            return self._json(200, {"ok": True, "jobs": backtest_api.list_jobs()})
        if len(parts) == 4 and parts[2] == "status":
            job = backtest_api.job_status(unquote(parts[3]))
            if job is None:
                return self._json(404, {"ok": False, "error": "job tidak ditemukan"})
            return self._json(200, {"ok": True, "job": job})
        if len(parts) == 4 and parts[2] == "result":
            summary = backtest_api.job_result(unquote(parts[3]))
            if summary is None:
                return self._json(404, {"ok": False,
                                        "error": "hasil belum ada atau job gagal"})
            verdict = ea_generator.evaluate_summary(summary)
            return self._json(200, {"ok": True, "summary": summary,
                                    "verdict": verdict})
        if len(parts) == 3 and parts[2] == "generated":
            return self._json(200, {"ok": True, "items": ea_generator.list_generated()})
        if len(parts) == 4 and parts[2] == "ea":
            data, ctype = ea_generator.read_ea(unquote(parts[3]))
            if data is None:
                return self._json(404, {"ok": False, "error": ctype})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition",
                             f'inline; filename="{unquote(parts[3])}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if len(parts) == 5 and parts[2] == "file":
            data, ctype = backtest_api.job_file(unquote(parts[3]), unquote(parts[4]))
            if data is None:
                return self._json(404, {"ok": False, "error": ctype})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        return self._json(404, {"ok": False, "error": "endpoint backtest tidak dikenal"})

    def _handle_backtest_run(self):
        user = self._require_auth()
        if not user:
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 8192:
            return self._json(413, {"ok": False, "error": "Isi permintaan terlalu besar"})
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"ok": False, "error": "Format permintaan tidak valid"})
        if not isinstance(data, dict):
            return self._json(400, {"ok": False, "error": "Format permintaan harus objek"})
        job, err = backtest_api.start_job(data)
        if err:
            code = 409 if "berjalan" in err else 400
            return self._json(code, {"ok": False, "error": err})
        return self._json(202, {"ok": True, "job_id": job["id"],
                                "out_dir": job["out_dir"]})

    def _handle_backtest_cancel(self):
        from urllib.parse import unquote
        user = self._require_auth()
        if not user:
            return
        job_id = unquote(self.path[len("/api/backtest/cancel/"):].split("?")[0])
        ok, msg = backtest_api.cancel_job(job_id)
        return self._json(200 if ok else 409, {"ok": ok, "message": msg})

    def _handle_ea_generate(self):
        user = self._require_auth()
        if not user:
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 8192:
            return self._json(413, {"ok": False, "error": "Isi permintaan terlalu besar"})
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"ok": False, "error": "Format permintaan tidak valid"})
        if not isinstance(data, dict):
            return self._json(400, {"ok": False, "error": "Format permintaan harus objek"})
        job_id = str(data.get("job_id") or "").strip()
        name = data.get("name")
        magic = data.get("magic")
        try:
            magic = int(magic) if magic not in (None, "") else None
        except (TypeError, ValueError):
            return self._json(400, {"ok": False, "error": "magic harus angka"})
        meta, err = backtest_api.generate_ea(job_id, name, magic)
        if err:
            return self._json(400, {"ok": False, "error": err})
        return self._json(201, {"ok": True, "ea": meta})

    def do_GET(self):
        if self.path in ("/broker", "/broker-login", "/broker-login.html"):
            return self._broker_login_html()
        if self.path.startswith("/api/broker/status"):
            st = broker_login.status()
            st["required"] = BROKER_LOGIN_REQUIRED
            return self._json(200, {"ok": True, **st})
        if BROKER_LOGIN_REQUIRED and not broker_login.status().get("connected"):
            if self.path in ("/", "/index.html", "/strategy-lab",
                             "/strategy-lab.html", "/strategy-monitor",
                             "/strategy-monitor.html"):
                return self._broker_redirect()
            if self.path.startswith("/api/"):
                return self._json(401, {"ok": False,
                                        "error": "Login broker MT5 diperlukan"})
        if self.path in ("/", "/index.html"):
            if BROKER_LOGIN_REQUIRED and not broker_login.status().get("connected"):
                return self._broker_redirect()
            return self._index_html()
        if self.path in ("/strategy-lab", "/strategy-lab.html"):
            return self._strategy_lab_html()
        if self.path in ("/strategy-monitor", "/strategy-monitor.html"):
            return self._strategy_monitor_html()
        if self.path.startswith("/skills/"):
            return self._serve_skill_doc()
        if self.path.startswith("/api/dashboard"):
            return self._json(200, dashboard_payload())
        if self.path.startswith("/api/mt5/status"):
            hb, _ = mt5_state()
            return self._json(200, hb)
        if self.path.startswith("/api/candles"):
            # /api/candles?count=200&before=<epoch> — chart interaktif ala MT5
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            with_before = None
            try:
                count = int(qs.get("count", ["200"])[0] or 200)
            except (TypeError, ValueError):
                count = 200
            b_raw = qs.get("before", [None])[0]
            if b_raw:
                try:
                    with_before = int(b_raw)
                except (TypeError, ValueError):
                    with_before = None  # "null"/teks dari browser -> abaikan
            return self._json(200, candles_payload(count=count, before=with_before))
        if self.path.startswith("/api/history"):
            return self._json(200, history_payload())
        if self.path.startswith("/api/accuracy"):
            return self._json(200, accuracy_payload())
        if self.path.startswith("/api/strategy-monitor"):
            return self._json(200, strategy_monitor.payload())
        if self.path.startswith("/api/executor"):
            return self._json(200, executor.executor_payload())
        if self.path.startswith("/api/auth/status"):
            payload = self._session_payload()
            return self._json(200, {
                "ok": True,
                "logged_in": bool(payload),
                "user": payload.get("u") if payload else None,
                "expires_at": payload.get("exp") if payload else None,
            })
        if self.path.startswith("/api/backtest/"):
            return self._handle_backtest_get()
        if self.path.startswith("/api/engine/run"):        # manual trigger (riset)
            if not self._require_auth():
                return
            r = ENGINE.run(force=True) if ENGINE else None
            ok = bool(r)
            return self._json(200, {"ok": ok, "n_matches": r["n_matches"] if r else None,
                                    "best_similarity": r["best_similarity"] if r else None,
                                    "error": ENGINE.last_error if not ok else None})
        if self.path.startswith("/api/config"):
            if not self._require_auth():
                return
            return self._json(200, sanitized_config(load_config()))
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/broker/login"):
            return self._handle_broker_login()
        if self.path.startswith("/api/broker/logout"):
            return self._handle_broker_logout()
        if BROKER_LOGIN_REQUIRED and not broker_login.status().get("connected"):
            return self._json(401, {"ok": False,
                                    "error": "Login broker MT5 diperlukan"})
        if self.path.startswith("/api/login"):
            return self._handle_login()
        if self.path.startswith("/api/logout"):
            return self._handle_logout()
        if self.path.startswith("/api/backtest/run"):
            return self._handle_backtest_run()
        if self.path.startswith("/api/backtest/cancel/"):
            return self._handle_backtest_cancel()
        if self.path.startswith("/api/backtest/generate-ea"):
            return self._handle_ea_generate()
        if self.path.startswith("/api/config"):
            if not self._require_auth():
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > 4096:
                return self._json(413, {"ok": False, "error": "Isi permintaan terlalu besar"})
            try:
                incoming = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._json(400, {"ok": False, "error": "Format permintaan tidak valid"})
            if not isinstance(incoming, dict):
                return self._json(400, {"ok": False, "error": "Format permintaan harus berupa objek"})
            cfg = load_config()
            allowed = {"pair", "timeframe", "prioritize_session",
                       "similarity_threshold_pct", "top_patterns",
                       "update_every_n_candles", "candles_per_pattern",
                       "time_display", "predict_mode", "predict_top_k"}
            for k, v in incoming.items():
                if k in allowed:
                    cfg[k] = v
            save_config(cfg)
            return self._json(200, {"ok": True, "config": sanitized_config(cfg)})
        return self._json(404, {"ok": False, "error": "endpoint tidak dikenal"})


def main():
    global ENGINE
    ENGINE = Engine()

    def boot():
        """Import + satu run engine di background — server tetap responsif
        langsung saat start; hasil muncul ±60 dtk kemudian."""
        try:
            import_new(force=True)
            if ENGINE.run(force=True):
                sys.stderr.write(f"[boot] engine OK: {ENGINE.last_result['n_matches']} pola, "
                                 f"best {ENGINE.last_result['best_similarity']}%\n")
            else:
                sys.stderr.write(f"[boot] engine menunggu: {ENGINE.last_error}\n")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[boot] {type(e).__name__}: {e}\n")

    threading.Thread(target=boot, daemon=True).start()

    # Scheduler (Fase 6): cek candle baru tiap 20 dtk, run tiap N candle
    threading.Thread(target=ENGINE.loop, daemon=True).start()

    cfg = load_config()
    port = int(os.environ.get("DASHBOARD_PORT", cfg.get("port", 8090)))
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    tf = cfg.get("timeframe", "M5")
    minutes = TIMEFRAME_MINUTES.get(tf, 5)
    print("XAUUSD Pattern Dashboard (Fase 3..8)", flush=True)
    print(f"  -> http://localhost:{port}/  (pair={cfg['pair']}, TF={tf} = {minutes} menit)", flush=True)
    print("  -> mode: riset saja", flush=True)
    if (load_config().get("auto_trade") or {}).get("enabled", False):
        print("  -> EKSEKUTOR DEMO AKTIF (auto_trade.enabled) — pastikan akun MT5 = DEMO", flush=True)
    else:
        print("  -> tanpa transaksi otomatis (auto_trade.enabled = false)", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ENGINE.stop.set()
        print("\nBerhenti.")

if __name__ == "__main__":
    main()
