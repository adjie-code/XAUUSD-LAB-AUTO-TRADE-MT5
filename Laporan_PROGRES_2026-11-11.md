# Laporan Progres — 11 November 2026

**Proyek:** XAUUSD Pattern Dashboard (`/DATA/AppData/AI-Projek/xauusd-pattern-dashboard`)
**Status akhir hari ini:** 🟢 Semua komponen sinkron — eksekusi otomatis demo AKTIF & terbukti mengirim order.

---

## 1. Perbaikan Sinkron Tabel Prediksi vs Saran Riset

**Masalah:** pada waktu candle yang sama, saran Entry/SL/TP tidak cocok dengan isi Tabel Prediksi.

**Akar:** logika `renderSuggestions()` di frontend berbeda dari tampilan tabel (SL memakai amplop global 10 candle, baris netral dibuang diam-diam, waktu entry tidak ditampilkan).

**Perbaikan (`static/app.js`, `static/index.html`):**
- SL kini memakai **band 80% candle yang sama** (p10 utk BUY / p90 utk SELL) — identik dengan kolom Band di Tabel Prediksi
- Kolom baru: **Waktu entry (anchor)** dan **Status**
- Filter akhir (permintaan user): **hanya sinyal R:R ≥ 1 yang ditampilkan**; sisanya disembunyikan

## 2. Eksekusi Otomatis ke MT5 — Akun Demo (fitur baru besar)

**Permintaan user:** hasil prediksi dieksekusi langsung ke MT5 (demo), full otomatis.
**Prinsip lama "riset saja" diperluas** — dengan pengaman berlapis.

**Arsitektur (jembatan file, pola yang sama dgn EA exporter):**
```
Engine → executor.py → signal.txt (Common/Files) → EA Executor (MT5) → OrderSend
                                   ↑ exec_log.txt (hasil) ←──────────┘
```

**Komponen baru:**
| File | Peran |
|---|---|
| `executor.py` | Hitung sinyal (logika = Saran Riset), tulis `signal.txt` (maks 2 order/candle: R:R terbaik + candle pertama layak), baca `exec_log.txt` |
| `ea/XAUUSDPatternExecutor.mq5` | EA: baca sinyal → order market CTrade; **tolak keras jika akun bukan DEMO**; batas 5 posisi; 1 sinyal = 1 eksekusi (tahan restart); maks 1 order per detik |
| `app.py` | Hook scheduler setiap engine run; endpoint `GET /api/executor` |
| `static/` | Seksi UI "Eksekutor MT5" — status, alasan idle, log eksekusi |
| `config.json` | Blok `auto_trade` (enabled, symbol, lot 0.01, max_positions 5, max_orders 2, rr_min 1.0) |

**Pengaman aktif (tidak bisa dimatikan):** akun wajib DEMO (terbukti: menolak saat akun masih REAL) · validasi SL/TP vs harga live · batas posisi · dedup sinyal.

## 3. Krisis Data Akibat Pindah Broker (akun cent → demo HFM) — DISELESAIKAN

**Gejala:** prediksi "tidak pasti", similarity 99,99%, 100 ribu pola "cocok".

**Akar berlapis:**
1. Server HFM ber-zona **GMT+2** (sebelumnya Exness GMT+0) → candle baru bertimestamp +2 jam → 22 candle "masa depan" di DB
2. Full history 99.999 candle terimpor dobel (versi +2 jam di samping versi UTC lama) → engine cocok pola dengan kembarannya sendiri
3. `XAUUSDPatternBackfillTester` (EA untuk Strategy Tester) dipakai di chart live — setiap init **mengosongkan** `backfill_m5.csv`
4. Input `SYMBOL_TRADE` executor masih `XAUUSDc` (tidak ada di akun HFM) → semua order ditolak

**Perbaikan (sisi MT5 saja, kode web tak disentuh — sesuai permintaan):**
- EA Exporter di-patch: normalisasi waktu candle server → **GMT** (`GmtTime()`); heartbeat ikut GMT
- EA Executor: default input `SYMBOL_TRADE = XAUUSD` + anti-spam log penolakan + peringatan simbol tidak dikenal
- BackfillTester dikeluarkan dari chart live (fungsinya tergantikan exporter)
- Compile EA dilakukan otomatis via `wine metaeditor64.exe /compile` di container `linux-mt5` (0 errors)
- Container di-restart agar versi baru aktif
- **DB dibersihkan:** 159.210 baris tercemar dihapus → re-import dari CSV ternormalisasi → 570.943 candle konsisten GMT

## 4. Hasil Akhir (diverifikasi live)

| Indikator | Nilai |
|---|---|
| `running / fresh` | ✅ true / true (umur data ±46 dtk) |
| Simbol | ✅ XAUUSD (M5, 5000 candle rolling) |
| Zona waktu | ✅ GMT konsisten, 0 candle masa depan |
| Engine | ✅ jalan tiap candle; prediksi & anchor sinkron |
| Eksekusi | ✅ **2 BUY tereksekusi di demo** (retcode 10009/DONE): entry 4040.39, lot 0.01 |

## 5. Catatan Riset & Rencana Berikutnya

1. **SL lebih sempit dari spread** — order pertama SL-nya 0.13 USD, spread 0.17 → SL di dalam spread, hampir pasti kena noise. **Usulan:** SL minimum = max(band, spread × 2–3) — menunggu persetujuan user.
2. Riwayat beberapa run engine hari ini (era data rusak) masih tampil di Riwayat Prediksi — akan tergantikan sendiri oleh run baru.
3. Sesi riset (Asia/Eropa) kini berbasis jam GMT yang konsisten — sudah aman sejak normalisasi.
4. Sisa proses lama `python3 app.py 9090` (manual, 9 Nov) sebaiknya dimatikan.

---

*Semua perubahan dokumentasi: `ROADMAP.MD` (bagian Eksekutor MT5, 11 Nov 2026).*
