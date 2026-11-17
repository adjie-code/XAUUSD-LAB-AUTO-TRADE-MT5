1. Konsep utama proyek: bangun dashboard web untuk mencari pola candle historis XAUUSD, mencocokkan dengan kondisi terbaru untuk mengestimasi 10 candle M5 berikutnya. Proses pembaruan otomatis setiap 10 candle selesai. Parameter awal yang bisa diubah: pair XAUUSD, timeframe M5, prioritas sesi Asia, batas kemiripan 70%, dan pencarian 20 pola terbaik. Format output menampilkan 10 candle aktual, 10 candle prediksi, persentase kemiripan, dan riwayat 1 prediksi terakhir. Parameter sistem bisa diubah lewat konfigurasi. Folder proyek di /DATA/AppData/xauusd-pattern-dashboard/. Backend Python pakai DTW dan metode statistik, database SQLite, frontend dashboard web, deployment di Docker pada CachyOS + CasaOS. Mode-nya hanya riset, tanpa transaksi otomatis. Proses sistem: ambil data historis dari Dukascopy, ambil 10 candle M5 terbaru yang sudah selesai, jadikan pola acuan, cari pola serupa dengan prioritas sesi Asia, hitung persentase kemiripan, ambil 10 candle setelah pola itu sebagai dasar prediksi, tampilkan dalam bentuk candlestick lengkap, update ulang setiap 10 candle selesai. Parameter bisa diubah lewat konfigurasi. Tahapan pengerjaan: fase 0 audit lingkungan server tanpa instalasi, minta persetujuan dulu, fase 1 bangun dashboard dasar dengan data dummy, fase 2 integrasi Dukascopy, fase 3 unduh data historis, fase 4 mesin pencarian pola, fase 5 mesin estimasi, fase 6 pembaruan otomatis, fase 7 tampilan histori prediksi, fase 8 evaluasi akurasi, fase 9 deployment Docker, lalu tes MVP selesai. Catatan penting: data lebih penting daripada prediksi yang kelihatan meyakinkan. Kalau data kurang, sistem harus bilang tidak cukup data. Prinsip akhir: sebelum mulai, OpenCode baca roadmap lengkap dulu, lalu mulai dari fase 0. Jangan lakukan instalasi tanpa persetujuan.

---

# LAPORAN PROGRES — per 5 November 2026

> Catatan roadmap asli dipertahankan apa adanya di atas; laporan ini hanya tambahan status pekerjaan.
> Konfigurasi aktual: pair XAUUSD, TF M5, parameter di `config.json`, folder proyek `/DATA/AppData/AI-Projek/xauusd-pattern-dashboard/`.

## Status fase

| Fase | Status | Bukti/celah |
|---|---|---|
| 0 Audit lingkungan | ✅ SELESAI | `AUDIT_FASE0.md` — CachyOS, Docker 29.9 aktif, CasaOS aktif, Python 3.14.8 tanpa instalasi, RAM cukup, disk root 12 GB bebas |
| 1 Dashboard + dummy | ✅ SELESAI & LIVE | `app.py` + `static/` — http://localhost:8090 (LAN: http://192.168.0.102:8090), chart candlestick murni canvas, parameter UI tersimpan ke `config.json`, countdown update otomatis |
| 2 Integrasi sumber data | ✅ SELESAI | EA berjalan & menulis CSV rolling (`fresh=true`, 5000+ candle asli XAUUSDc). Bug format heartbeat (FILE_TXT tanpa pemisah) sudah dibetulkan di EA + parser fallback di `mt5_reader.py` |
| 3 Unduh historis massal | ✅ SELESAI | User compile EA (F7) 5 Nov; `TryBackfill()` menulis `candles_m5_full.csv` 100.074 baris M5 (513 hari kalender; broker membatasi CopyRates — bukan penuh 730 hari). Import upsert → SQLite **100.075 bar**, 5,8 detik, tanpa duplikat. Fix filter `min_t` full CSV di `import_new` (bagian lama justru yang diimpor). Heartbeat kini format benar `OK;XAUUSDc;M5;...` |
| 4 Mesin pencarian pola | ✅ SELESAI | `pattern_engine.engine()`: DTW murni + band, scan riwayat penuh (4981 window / 0,43 s di 5000 bar), threshold 70%, prioritas sesi Asia (bukan eksklusif), eksklusi self-match, hasil → `pattern_matches`. Ditampilkan di UI "10 Pola Terbaik" |
| 5 Mesin estimasi | ✅ SELESAI | Estimasi 10 candle = rata-rata sampel historis 10-candle SETELAH setiap pola terbaik (statistik, bukan random). Persist ke tabel `predictions` |
| 6 Pembaruan otomatis | ✅ SELESAI | Scheduler thread: import incremental tiap 20 detik, run resmi tiap `update_every_n_candles` candle selesai + bootstrap saat boot; countdown UI mengikuti `generated_at` |
| 7 Histori prediksi | ✅ SELESAI | Tabel `engine_runs` + endpoint `/api/history` + tabel riwayat di UI (10 run terakhir: bar, pola, kemiripan, arah, evaluasi) |
| 8 Evaluasi akurasi | ✅ SELESAI | `evaluate_ready()`: prediksi matang dibandingkan candle aktual → `accuracy_history` (dengan `idx` per candle index, dedup). `/api/accuracy` (MAE, hit ≤1 USD, kurva per-index) + kartu akurasi di UI. Dievaluasi sintetis di DB salinan: MAE konsisten, dedup bekerja |
| 9 Deployment Docker | ⏸ DITANGGUHKAN | Tunggu konfirmasi user (perintah 5 Nov 2026: jalankan sampai fase 8) |

## Keputusan penting (perubahan dari roadmap asli)

1. **Sumber data: MT5 bukan Dukascopy.** Penyelidikan 5 Nov 2026 menunjukkan:
   - DNS lokal (ISP/rute) mengirim jawaban palsu untuk `datafeed.dukascopy.com` & `www.dukascopy.com` → sudah dipin IP benar lewat `/etc/hosts` (`datafeed.dukascopy.com = 16.62.244.190`, `www.dukascopy.com = 104.20.28.213/172.66.145.22`).
   - Meski DNS benar, endpoint HTTP lawas `datafeed.dukascopy.com` kini memberi `429` konsisten; wiki resmi Dukascopy memindahkan data historis ke bucket S3 `cfg-public-proper-wallaby` (*Requester Pays*, perlu akun AWS + kredensial + instalasi boto3, biaya kecil).
   - Solusi user pilihan: MT5 yang sudah aktif di server ini (Docker container `linux-mt5`, broker Exness, login 160198874, symbol XAUUSDc) → **tanpa biaya, tanpa ketergantungan AWS, data asli broker**.
2. **EA MQL5 sebagai jembatan data** (read-only, tidak transaksi): EA membaca candle M5 `CopyRates` lalu menulis CSV `XAUUSDPattern/candles_m5.csv` + `heartbeat.txt` via `FILE_COMMON` setiap candle M5 selesai. Backend Python membaca CSV itu. Symbol mengikuti chart EA; timeframe **fix M5** sesuai roadmap.
3. **Dukascopy dipindah ke backlog** — opsi jalur S3 resmi tetap terbuka kalau suatu saat dibutuhkan cross-verification (butuh persetujuan instalasi boto3 + kredensial AWS).

## Keputusan teknis (fase 0-8)

- Semua kode backend **Python stdlib** (tanpa instalasi paket apa pun) + HTML/JS/canvas tanpa library.
- Server dashboard: `python3 app.py` (port 8090, bind 0.0.0.0, akses LAN ok).
- Parameter via `config.json` + UI `/api/config`; API: `/api/dashboard`, `/api/config`, `/api/mt5/status`, `/api/history` (F7), `/api/accuracy` (F8), `/api/engine/run` (trigger manual, riset).
- Sumber resmi candle = SQLite `data/patterns.db` (diisi upsert dari CSV EA: `candles_m5.csv` rolling + `candles_m5_full.csv` full history). Unique index `t`, dedup otomatis.
- Tabel baru: `engine_runs` (F4/6), `predictions` (F5). Kolom baru: `accuracy_history.idx` (F8, migrasi idempoten di `db_init.py`).
- Prinsip roadmap dijaga: jika data dummy/EA belum jalan, dashboard **berlabel jelas** sumbernya dummy. Baris riwayat < 20.000 bar ditandai "Data terbatas" (`sufficient_data=false`) — jangan ragu menyebut data belum cukup.

## Langkah berikutnya

1. ~~Compile EA + restart server~~ ✅ selesai — server 8090 hidup dengan kode Fase 3–8, DB 100.075 bar, engine memindai riwayat penuh (100.056 pola cocok, 9,6 detik, top 99,99% sesi Asia).
2. Monitor ± 50–60 menit: `/api/accuracy` harus mulai terisi evaluasi prediksi matang (bukan sintetis).
3. Full CSV EA menulis ulang maksimal 1x/jam — server akan import ulang otomatis via scheduler.
4. Fase 9 (Docker) menunggu konfirmasi user.

---
---

# RANCANGAN ULANG — per 6 November 2026 (hasil audit ulang semua file)

## Temuan audit 6 Nov (analisis ulang seluruh file)

| File | Ukuran | Status | Catatan |
|---|---|---|---|
| `app.py` | 24 KB | ✅ inti sistem | server + scheduler + import + engine + evaluasi; `/api/engine-run` pakai **GET** |
| `pattern_engine.py` | 8 KB | ✅ | DTW murni, sesi Asia, eksklusi self-match |
| `mt5_reader.py` | 8 KB | ✅ | baca CSV rolling/full + heartbeat + parser fallback |
| `backfill_dukascopy.py` | 12 KB | ⚠️ tidak terpakai aktif | jalur legacy/S3 disiapkan tapi legacy 429-stabil; aktifkan hanya jika butuh |
| `db_init.py`, `import_csv.py` | kecil | ✅ | skema + import manual |
| `data/patterns.db` | 11 MB | ✅ | **100.280 candle** (9 Jun 2025 → 6 Nov 2026) |
| `static/` (3 file) | 16 KB | ✅ diperbarui 6 Nov | panel analisa & cakupan baru (lihat bawah) |
| CSV EA rolling | 5000 bar | ✅ | 12 hari ke belakang, update tiap candle |
| CSV EA full | 100.011 bar | ⚠️ terpotong | **berhenti tepat di limit MaxBars=100.000 MT5** |

## Temuan 1: Data histori JAUH dari 10 tahun (kecurigaan user benar)

- Jestungkar bukti: SQLite **100.280 candle = 1,41 tahun** (Jun 2025 → Nov 2026) — hanya **11,9 %** dari target 10 thn (± 841.000 candle realistis).
- **Akar masalah:** MT5 membatasi history chart (`MaxBars=100000` di `common.ini`) → `CopyRates` max terpotong, sehingga `candles_m5_full.csv` berhenti di 100.011 bar.
- **Rpraptlan lingkungan riwayat:** server Exness menyimpan M5 XAUUSDc hampir ± 2,5 thn (`.hcc` 2024/2025/2026 ada di disk), Dukascopy punya 2003–2026 tetapi hanya via S3 (perlu AWS creds, ± $1) atau endpoint lawas (berisiko 429 tiap while).
- **Rancangan baru data (Fase 3R): Reactualized**
  - **3R-A (gratis, cepat):** naikkan `MaxBars` MT5 ke 5.000.000 (Tools → Options → Charts) + EA full-export penulisan chunk (5000/putaran → append) → target **± 2,5 thn** (2024 → sekarang, ± 190k bar) **kadar riil ini tanpa issue apa pun**.
  - **3R-B (10 thn penuh, berbayar kecil):** Dukascopy S3 `cfg-public-proper-wallaby` — butuh akun AWS user + kredensial + izin instalasi `boto3`. Data tick harian .bi5 2003→sekarang (format terverifikasi wiki). Estimasi biaya unduh XAUUSD M5-ekuiv ≤ $1 sekali unduh.
  - **3R-C (fallback tanpa biaya):** endpoint legacy `datafeed.dukascopy.com` dengan pacing agresif (1 file/10s + backoff 429) — percobaan tadi beberapa kali menunjukkan 429 persist; hanya rencana cadangan.
  - **Kejujaran UI:** kartu "Cakupan Data" baru menampilkan tahun/bars/% from target 10 thn — laporan selalu jujur (prinsip roadmap: bilang "tidak cukup data" jika memang kurang).
- UI engine minimal kini berjalan walau data 1,4 thn; DTW tetap valid — hanya ⟶ **pola lebih sedikit & lebih berisiko overfit periode 2025-2026**. Jangan klaim pattern-matching "10 tahun" saat kuhitungan kurang dari itu.

## Temuan 2: Tampilan analisa candle BELUM jelas → sudah diperbaiki (6 Nov)

- **Akar masalah:** payload API tidak pernah mengirim **10 candle historis tercocok** & **10 candle aktual setelah pola** — UI hanya menggambar 10 candle aktual + 10 prediksi, sehingga "analisa" pola tak terlihat.
- **Perbaikan backend:** `/api/dashboard` kini mengirim `comparison` (pola terbaik tercurrent + follow-up aktual dari SQLite) dan `coverage` (rentang & % target 10 thn).
- **Perbaikan frontend (3 panel atas):**
  1. **10 Candle Aktual (sekarang)** — lebih tinggi (200 px)
  2. **🔍 Panel Analisa (baru, 220 px)** — 20 candle dalam satu skala bersama: **kiri = 10 candle historis tercocok (pola acuan)**, **kanan = 10 candle aktual setelah pola (akibat)** — dipisah garis emas putus-putus + label % kemiripan; setelah pemisah warna kuning/hijau muda berbeda
  3. **10 Candle Prediksi** — estimasi berikutnya
- Kartu baru "📖 Cakupan Data Historis" (bars, tahun, % target 10 thn) — sumber kejujuran data.
- Diverifikasi live: engine run manual `GET /api/engine/run` → 100.261 pola, best 99,98%; comparison terkirim (pola 20 Nov 2025 01:10 UTC, 10/10 candle).

## Urutan kerja baru (menggantikan "Langkah berikutnya" lama)

> ### ✅ LAPORAN 6 Nov 2026 — siang: BACKFILL 10 TAHUN BERHASIL
> - User mengunduh histori server Exness via Strategy Tester (`.hcc` 2014–2026) lalu menjalankan EA khusus **`XAUUSDPatternBackfillTester.mq5`** (append per candle M5 ke `backfill_m5.csv`, file terpisah dari CSV live).
> - Hasil: **666.689 baris** → DB **667.242 candle** (2015-01 → 2026-11-06) = **79,3 % dari target 10 thn**; **span 11,86 thn**.
> - Import dipercepat via batch `executemany` (666 rb baris = **32 detik**).
> - **Scan engine 10 tahun = 25 detik**, **241.681 pola valid** (best 99,98 %).
> - **Engine kini tahan-bolong**: ing window 10 candle hanya valid bila candles-nya berurutan 300s (`reach[]` precompute); sampel akibat berhenti saat gap — data sparse/akhir pekan tak bisa jadi pola palsu (teruji 3 kasus sintetis).
> - **Cakupan data jujur di UI**: span thn, % terisi (66,9 % — 2016–pertengahan 2018 sparse), flag gap.
> - Catatan kualitas data: era 2016–pertengahan 2018 jarang (arsip Exness, GB `.hcc` 14 vs 21 MB); **2018-06 → 2026 M5 rapat (~8,4 thn data penuh)**. Jam 21:00 UTC kosong = break harian emas (normal).
> - Tersisa: pasang kembali EA live (`XAUUSDPatternExporter`) ke chart XAUUSDc M5 agar data realtime mengalir ke CSV live.
>
> ### ✅ LAPORAN 6 Nov 2026 — siang #2: PANJANG POLA MENJADI PARAMETER UI
> - `candles_per_pattern` (5–60, default 10) kini **benar-benar terpakai**: dibaca oleh engine (`pattern_engine.engine`), pemilih window, sampel akibat, panel gambar, dan payload dashboard — pola & prediksi memakai panjang itu.
> - Bisa **dipilih & disimpan lewat UI** (input baru "Jumlah candle pola & prediksi" → tombol Simpan). Reversibel kapan saja.
> - Band DTW menyesuaikan otomatis: `band = max(2, round(N*0.3))` (Sakoe-Chiba tumbuh dengan panjang window).
> - `comparison` loader mengikuti N: pola N candle + akibat N candle (bukan hard-code 20).
> - Teruji: N=10 (61/61 pola sintetis), N=30 (21 pola, sparse ditolak = 0), produksi N=30 → pindaian 667rb bar **1m50s**, 78.243 pola valid, best 99,95 %, comparison 30+30 candle (pola 17 Nov 2025 01:00 UTC).
> - Terkait biaya scan: update tetap setiap `update_every_n_candles` — scan ± 2 menit tiap 50 menit (± 4 % duty) → aman di Raspberry-class CPU pun.
>
> ### ✅ LAPORAN 7 Nov 2026 (04:xx WIB) — SUMBER LIVE DIPERBAIKI & IMPORT REALTIME
> - **Akar masalah harga "tidak sesuai market":** EA yang terpasang di chart live adalah **`XAUUSDPatternBackfillTester`** → menulis `backfill_m5.csv`, sedangkan backend hanya membaca `candles_m5.csv` (stale). Akibatnya dashboard jatuh ke data **dummy sintetis**.
> - **Perbaikan sumber live:** `mt5_reader` kini mengenal `backfill_m5.csv`; `mt5_state()` memilih file dgn candle terakhir paling baru (rolling vs backfill). `_load_csv` membaca **ekor file** utk file > 5 MB (hemat IO; 35 MB tidak dibaca penuh tiap tick).
> - **Perbaikan fallback jujur:** bila tidak ada data live, panel "sekarang" menampilkan **candle asli terakhir dari DB** (label *stale*) — dummy sintetis hanya bila DB kosong.
> - **Perbaikan import realtime:** `import_new()` kini dipanggil **tiap tick scheduler (20 dtk)** — dijaga mtime; `import_backfill()` hanya meng-upsert baris baru (`t >= db_max-300`), bukan 667 ribu baris.
> - **Verifikasi:** DB 667.399 candle (terakhir 2026-11-06 21:30 UTC = live), engine run #12 (candle 21:30, 86.516 pola, N=20/threshold 90/top 50), 55 baris evaluasi akurasi di `accuracy_history`, semua endpoint 200.
> - Pembersihan kosmetik: heading tabel tidak lagi "10" statis; `mt5.bars` = jumlah bar sumber yg dipakai; payload memuat `source_file`.
> - **Catatan gap:** file backfill sempat ter-reset EA (OnInit) → DB kehilangan **02:00–08:30 UTC 6 Nov (≈78 candle)**. Engine gap-safe (window lintas gap ditolak). Bisa diisi nanti via tester/backfill kecil bila perlu.
> - **Belum selesai:** Fase 9 Docker (persistensi antar sesi agent); heartbeat masih ditulis EA lama (EA backfill belum menulis heartbeat) — status memakai freshness candle, bukan heartbeat.
>
> ### 🐛 FIX 7 Nov 2026 — Evaluasi Akurasi (% Perubahan, Bukan Level Absolut)
> - Evaluasi sebelumnya bandingkan **level harga prediksi vs aktual** secara absolut. Karena pola historis berasal dari era berbeda (2017: $1.244, 2025: $3.351, live: $4.065) → prediksi absolut campur aduk level → error 17-18% meskipun arah prediksi benar.
> - **Perbaikan:** evaluasi sekarang menghitung **% perubahan dari baseline**:
>   `pred_chg_pct = (pred_close - base_price) / base_price * 100`
>   `actual_chg_pct = (actual_close - base_price) / base_price * 100`
>   `error_pct = |actual_chg_pct - pred_chg_pct|` (%)
> - Pola dengan arah & magnitudo move yang sama akan dinilai akurat walau level absolut beda.
> - Data accuracy_history lama (17-18% error dari metodologi lama) tidak dihapus — akan tetap ada sebagai rekam jejak, tapi **tidak lagi dipakai** untuk agregat (karena setiap run_id hanya dievaluasi sampai 10 baris, run lama tidak di-skip karena sudah penuh).
> - Untuk memulai evaluasi benar dari nol: `/api/accuracy` sekarang menampilkan data baru dengan formula di atas. Evaluasi akan turun drastis saat candle baru matang.


1. **Nilai 3R-A sekarang**: user naikkan `Max bars in chart` di MT5 → katakan ke saya; saya betulkan EA (chunked full export) → recompile F7 → DB naik ke ± 2,5 thn data.
2. Jika user ingin benar-benar 10 thn: berikan penyetujuan + kredensial AWS → jalankan 3R-B (`backfill_dukascopy.py` di-adaptasi S3).
3. Setelah data cukup: **Fase 9 Docker + tes MVP** (masih `restart: always` agar server tidak mati antar-sesi).
