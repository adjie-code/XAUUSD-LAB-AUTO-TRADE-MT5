# Backtest Runner — XAUUSD

Tool backtest **terpisah** dari runtime MT5/EA. Tidak mengirim order, tidak
mengubah `signal.txt`, `exec_log.txt`, `exec_state.txt`, atau file strategi.

## Alur yang diterapkan

1. **Copy DB** — snapshot konsisten dibuat lewat SQLite backup API, bukan `cp`
   saat DB sedang ditulis. Source dibuka read-only.
2. **Batasi CPU** — wrapper memakai `nice -n 19` dan `taskset -c 2,3`.
   Script juga mengecek/menerapkan affinity dan nice.
3. **Backtest read-only** — hanya membaca snapshot di `/tmp/opencode`.
4. **Output terpisah** — hasil masuk ke `backtest/results/run_<timestamp>/`.
5. **Tidak menyentuh strategi aktif** — tidak mengimpor `app.py`, `executor.py`,
   Docker, MT5, atau file runtime.
6. **Hapus DB copy otomatis** — workdir snapshot dihapus di `finally` dan
   `atexit`, termasuk jika terjadi error.

## Cara pakai

```bash
# Full data Dukascopy 2006–2026
./backtest/run_backtest.sh

# Rentang pendek untuk uji cepat
./backtest/run_backtest.sh --start 2024-01-01 --end 2025-01-01
```

Default:
- data: `data/patterns.db` (Dukascopy 2006–2026)
- start: `2006-01-01`
- output: `backtest/results/`
- CPU: core `2,3` (bisa diubah: `CPUS=2,3 ./backtest/run_backtest.sh ...`)
- nice: `19` (di environment ini efektif 15)
- spread: `30` poin; slippage `0`; commission `0`
- lot: `0.01`; contract size `100`
- strategi: `ema_cross` baseline (EMA20/50 + ATR SL/TP)

## Output

Setiap run membuat folder baru:

```text
backtest/results/run_YYYYmmdd-HHMMSS/
├── summary.json   # parameter, metrik, kualitas data
├── trades.csv     # daftar trade
├── equity.csv     # kurva equity per trade
└── report.md      # ringkasan manusiawi
```

## Data yang dipakai

- Sumber: tabel `candles_m5` di `data/patterns.db`.
- Filter: `t >= --start`; bucket 5 menit; dedup `ROW_NUMBER`.
- Dataset aktif: Dukascopy XAUUSD M5 bid, **2006-01-01 23:00 → 2026-11-13 21:55 UTC**.
- **1.501.314 bar unik** (≈20,87 tahun), tanpa duplikat dan tanpa OHLC invalid.
- Start <2018 hanya diizinkan jika DB memiliki metadata `source=dukascopy`; ini mencegah data daily lama ikut terpakai.

## Hasil uji awal

Uji pada mesin ini (Celeron J3455, 4 core, data 1.501.314 bar):

- runtime script: **≈26 detik**
- wall time wrapper: **≈28,8 detik**
- output: `summary.json`, `trades.csv`, `equity.csv`, `report.md`
- DB copy: dihapus otomatis setelah output selesai
- hasil baseline full 2006–2026: 26.760 trade, net negatif, PF 0,794,
  max DD 84,81% — **bukan strategi produksi**

Baseline EMA cross **bukan strategi produksi** dan hasilnya bisa negatif. Tool
ini dipakai untuk menguji pipeline, bukan merekomendasikan strategi.

## Dataset Dukascopy 20 tahun

Dataset 20 tahun (2006–2026) sudah diunduh dan diimpor terpisah:

- CSV mentah: `backtest/data/dukascopy/raw/` (4 chunk, ±80 MB)
- Script download: `backtest/import/download_dukascopy_20y.sh`
- Script import: `backtest/import/import_dukascopy_csv.py`
- Script swap DB: `backtest/import/rebuild_db_from_dukascopy.sh`
- Aktif di `data/patterns.db`: **1.501.314 bar M5**, 20,87 tahun
- Backup DB lama: `backups/patterns-db-pre-dukascopy-20261114-121222.db`

Sumber Dukascopy berbeda dari MT5; jangan menganggapnya sebagai data broker.
Backtest tetap memakai asumsi spread/slippage sendiri.

## Strategy Tester dari dashboard

Buka `/strategy-lab`, bagian **Strategy Tester**:

- Pilih range dan parameter, lalu klik **Run backtest**.
- Run/cancel membutuhkan login admin dashboard.
- Satu job dalam satu waktu; status dan log tampil di halaman.
- Hasil menampilkan metrik, per-tahun, dan link `summary.json`,
  `trades.csv`, `equity.csv`, `report.md`, `run.log`.
- Riwayat run dibaca dari `backtest/results/run_*`.

API: `POST /api/backtest/run`, `GET /api/backtest/status/<id>`,
`GET /api/backtest/result/<id>`, `GET /api/backtest/jobs`,
`GET /api/backtest/file/<id>/<name>`, `POST /api/backtest/cancel/<id>`.

## Generate EA draft

Dari hasil backtest di Strategy Tester:

- Klik **Generate EA** pada panel hasil.
- Isi nama EA dan magic (kosong = otomatis).
- File `.mq5` ditulis ke `ea/generated/`, tidak menimpa EA aktif.
- EA memakai magic sendiri, DEMO-only, dan hanya mengontrol posisinya sendiri.
- Verdict dan gate ditampilkan; draft tetap bisa dibuat meski belum lolos,
  dengan konfirmasi.
- Compile 0 error/0 warning adalah syarat sebelum uji MT5/demo.
- Untuk revisi: ubah parameter, jalankan backtest baru, generate file baru.

## Catatan

- Spread di kolom `candles_m5.spread` tidak konsisten; backtest memakai asumsi
  `--spread-points`, bukan kolom tersebut.
- Untuk strategi baru, tambahkan modul strategi di `backtest/` dan tetap
  gunakan snapshot + output terpisah.
- Jangan menjalankan MT5 Strategy Tester di terminal yang sama dengan EA aktif.
- Jangan menaikkan `--cpus` ke semua core saat market aktif jika EA sedang
  mengelola posisi.
- Database 20 tahun membuat scan engine lebih berat (±2 menit di mesin ini).
  Pertimbangkan menaikkan `update_every_n_candles` jika market sedang aktif.
