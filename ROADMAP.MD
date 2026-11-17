# ROADMAP BARU — XAUUSD Pattern Dashboard

> Dibuat 9 November 2026 menggantikan roadmap fase 0–8 yang lama.
> **Last update 12 Nov 2026 (malam)** — audit menyeluruh: bug fix + penguatan keamanan eksekutor + EA gabungan di chart M5 tersimpan (tahan restart container) + dokumentasi disinkronkan dengan kondisi nyata.
> Roadmap lama (konsep awal + laporan progres 5–7 Nov): `Laporan_TERDAHULU.md`.
> Prinsip tetap: **data lebih penting daripada prediksi yang kelihatan meyakinkan** — jujur tentang cakupan & kekurangan data.

---

## 1. SISTEM SEKARANG (yang sudah jadi & teruji)

### Arsitektur data
```
MT5 (Docker linux-mt5, broker HFM, XAUUSD M5) — akun DEMO 5057878235
  ├─ chart01 profil aktif (MQL5/Profiles/Charts/Default): XAUUSD M5
  │    └─ EA XAUUSDPatternExecutor (GABUNGAN exporter + pattern + pullback, v2.00):
  │         ├─ menulis candles_m5.csv (rolling 5000) + heartbeat.txt (GMT)
  │         └─ membaca signal.txt, eksekusi order DEMO (lot bertingkat)
  ├─ chart02 profil: XAUUSD H1 — tanpa EA (exporter lama dilepas 13 Nov 2026; backfill full opsional dijalankan manual)
  └─ startup config /config TIDAK dipakai (dulu menambah 1 chart baru tiap restart)
       └─ app.py: import_new() tiap tick scheduler 20 dtk (dijaga mtime)
                 └─ SQLite data/patterns.db — 1.501.314 candle M5 (2006-01 → 2026-11; 20,9 thn)
                      └─ pattern_engine.engine(): DTW + band Sakoe-Chiba + reach[] gap-safe
                          + sesi Asia prioritas + threshold + top-N + candles_per_pattern 5–60
                          (engine memakai sampai 2.000.000 candle; data aktif 1,5 juta)
                           ├─ persist: engine_runs / pattern_matches / predictions
                           ├─ evaluate_ready(): % perubahan (bukan level absolut)
                           ├─ executor.publish(): sinyal → signal.txt (EA eksekutor baca)
                           └─ /api/dashboard → UI
```

### Server & persistensi
- **systemd user service** `xauusd-dashboard` (`~/.config/systemd/user/`):
  - `Restart=always` — server bangun sendiri kalau crash
  - Aktif saat boot (Linger=yes) — tanpa sudo, tanpa Docker
  - Server **responsif instan saat start**; engine bootstrap jalan di thread background (±60 dtk) dengan `force=True`
- Scheduler: import incremental tiap 20 dtk; run engine **setiap candle baru** (`update_every_n_candles = 1`, ±5 menit — sebelumnya tiap 10 candle/±50 menit, keputusan user 9 Nov sore: prediksi selalu fresh dianchor harga terakhir)

### Dashboard UI (http://localhost:8090 · LAN http://192.168.0.102:8090)
| Bagian | Status |
|---|---|
| Header: fase, sumber data, countdown update (tidak lagi macet di 00:00) | ✅ |
| Parameter tersimpan (sesi, threshold, top-N, jumlah candle 5–60, waktu tampilan, **mode prediksi**, **K pola serupa**) | ✅ |
| **Chart interaktif ala MT5** (`interactive_chart.js`): zoom scroll, pan drag, crosshair + info O/H/L/C + volume, tombol 30/60/120/300/600, tombol Live, **toggle ⟳ Auto: ON/OFF** (live-follow pintar: polling 20 dtk HANYA saat view di posisi Live — riwayat tidak diganggu), sentuh HP, muat riwayat tak terbatas | ✅ |
| Panel analisa: pola historis (kiri) vs akibat aktual (kanan), pemisah garis emas | ✅ |
| Panel prediksi — **2 mode dibandingkan dari UI**: `topk_median` (baru, default) & `mean` (lama) | ✅ |
| **Tabel prediksi terpisah**: per-index median OHLC + band 80% (p10–p90) + probabilitas arah (%) + jumlah sampel — badge di canvas dihilangkan (band tetap digambar) | ✅ |
| Cakupan data jujur: span tahun, jumlah candle, % target 20 thn, flag gap | ✅ |
| Tabel Pola Terbaik + Riwayat Prediksi + kartu akurasi (3 kartu — kartu "Status data" duplikat dihapus) | ✅ |
| Jam tampilan: **default = waktu server MT5** (DST otomatis: GMT+3 musim panas / GMT+2 saat ini) — opsi WIB / UTC; `fmtTs` tahan string/NaN (error "Invalid time value" sudah off) | ✅ |
| Label sumber data jujur: `MT5 EA (live)` / `PASAR TUTUP (akhir pekan)` / `stale` — dummy hanya bila DB kosong | ✅ |
| Bersih-bersih UI: `IChart.init` dirilis di modul (bug "chart tidak jalan" solv), blok Parameter terduplikasi dihapus, label `(Fase N)` dilepas | ✅ |

### Verifikasi terakhir (9 Nov 2026, sore)
- Engine run: **124.033 pola valid** (best 99,99%) dengan mode `topk_median`, K=10
- Prediksi: 10 candle median terisi + band 80% terisi (contoh idx0: 4113,27–4116,24 sekitar median 4115,3)
- Probabilitas arah terhitung dari sampel (contoh idx0: 30%↑/70%↓ bearish, idx4: 20%↑)
- `/api/candles` (chart interaktif) mendukung `before=` paging 667 rb bar
- DB 667.406+ candle, sumber live EA fresh, semua endpoint 200

---

## 2. KEPUTUSAN DESAIN YANG SUDAH DIKUNCI

1. **Sumber data = MT5 broker HFM (akun demo, server GMT+2/+3)** — candle dinormalisasi ke GMT oleh EA `XAUUSDPatternExecutor` (gabungan). Backfill Dukascopy dibatalkan (S3 Requester Pays & endpoint legacy 429). Data asli broker, tanpa biaya.
2. **EA `XAUUSDPatternExecutor` (gabungan exporter+executor sejak 12 Nov malam, v2.00 multi-strategi sejak 13 Nov 2026) adalah sumber live + eksekutor** — chart XAUUSD **M5** dengan EA ini disimpan permanen di profil aktif `MQL5/Profiles/Charts/Default/chart01.chr`, jadi MT5 memulihkannya otomatis tiap launch. EA `XAUUSDPatternExporter` di chart02 H1 **sudah dilepas 13 Nov 2026** karena exporter M5 kini ada di EA utama; exporter lama tetap tersedia sebagai alat backfill manual. Startup config `/config` (`MT5_STARTUP_*`) sempat dipakai 16:28–23:41, tetapi **menambah 1 chart baru ke profil setiap restart** (chart05, chart06, ...), jadi dinonaktifkan. `backfill_m5.csv` sudah tidak dipakai (file lama dihapus saat pembersihan data Nov 2026).
3. **Semua statistik (% kemiripan, prediksi, evaluasi) memakai PERUBAHAN RELATIF**, bukan harga absolut — pola lintas-era ($1.2xx / $3.3xx / $4.0xx) tidak boleh dicampur level.
4. **Gap-safe engine**: window pola & sampel akibat hanya valid bila benar-benar berurutan 300 detik.
5. **Fallback jujur**: candle DB terakhir dgn label jelas (stale / pasar tutup), dummy sintetis hanya bila DB kosong.
6. **import_backfill**: hanya baris baru (`t >= db_max-300`) — 667 rb baris tidak diulang tiap tick.
7. **Mode prediksi ganda**: `predict_mode` di config — `topk_median` (baru: K pola paling mirip → median per index + band p10–p90 + prob arah) dan `mean` (lama: rata-rata semua pola tercocok). Kedua mode disimpan di DB per-run (`predict_mode`, `band_json`, `direction_json`) — bisa dibandingkan lewat akurasi, bukan klaim.
8. **Statistik probabilitas = tabel sendiri**, bukan badge di canvas (keputusan user 9 Nov sore). Canvas hanya candle median + band translucent.

---

## 3. YANG BELUM SELESAI (sisa kerja)

| Item | Prioritas | Catatan |
|---|---|---|
| **Tabel prediksi → visual candle** (opsi A/B/C sudah diusulkan) | **menunggu pilihan user** | A = kolom mini-candle di tabel; B = tabel jadi strip candle besar; C = merge ke canvas + detail saat hover. Belum dieksekusi sampai user memilih |
| Slot prediksi jarang penuh 20/20 | sedang | Mode K=10: sering hanya ±10 slot terisi — banyak pola Top-K tak punya sampel akibat 20 candle penuh (ujung data/gap). Bisa dikurangi: K lebih besar, atau N lebih kecil, atau tampilkan sampel parsial |
| **Gap kecil 02:00–08:30 UTC 6 Nov** (±78 candle) | rendah | Akibat file backfill di-reset saat EA re-attach. Engine gap-safe — tidak mengganggu. Bisa diisi via run kecil tester/backfill bila perlu |
| **EA belum menulis heartbeat.txt** | ✅ selesai | EA gabungan menulis `heartbeat.txt` tiap candle M5 (`status;symbol;tf;bars;last_close;synced;time`) |
| **Docker container penuh (fase 9 lama)** | sedang | Sudah diwakili systemd user service (auto-restart + boot). Dockeriasi penuh menunggu minat user |
| **Arsip EA & log tester yang basi** | ✅ selesai | `candles_m5.csv` / `candles_m5_full.csv` sekarang justru sumber live EA gabungan (bukan arsip tester). `backfill_dukascopy.py` legacy disimpan sebagai referensi |

---

## 4. IDE LANJUTAN (belum diputuskan — minta konfirmasi user dulu)

1. **Zoom-out timeframe**: view H1/H4 dengan agregasi candle M5 di server — analisa pola di tingkat besar.
2. **Skor akurasi per-sesi**: dashboard saringan best-match hanya dari sesi Asia/Eropa/AS, dengan statistik akurasi per bingkai sesi.
3. **Notifikasi**: dashboard ping (browser notification / webhook telegram) saat kemiripan >90%.
4. **Backfill pasang susun senin reset otomatis**: EA yang lebih tangguh kalau MT5 terminal restart (tulis heartbeat + tidak menghapus file saat OnInit).
5. **Fill gap 6 Nov** via ekspor small data rate MT5.
6. **Asisten level trading** (usulan & disetujui user 10 Nov — ✅ dikerjakan): tabel **"Saran Riset — Entry / SL / TP"** di bawah tabel prediksi, dihitung frontend dari payload (band + median + arah + tren). Logika tervalidasi data live: Entry = anchor (close terakhir; jam anchor di kolom "Waktu entry"); **SL = band 80% candle yang sama** (p10 utk BUY / p90 utk SELL); TP = median close candle ke-N. **Filter = cermin aturan eksekutor**: sinyal lawan tren (EMA13) disembunyikan; searah tren cukup R:R ≥ `rr_min_trend` (1.0); sideways wajib R:R ≥ `rr_min` (1.0); netral 45–55%, band salah sisi, dan reward ≤ 0 selalu disembunyikan. Hanya mode `topk_median` yang menghasilkan saran. Sejak 11–12 Nov 2026 sinyal yang sama dieksekusi otomatis **hanya di akun DEMO** oleh EA eksekutor.

---

## 5. REFERENSI CEPAT

```bash
# service
systemctl --user status xauusd-dashboard
systemctl --user restart xauusd-dashboard
journalctl --user -u xauusd-dashboard -f

# endpoint
GET /                       → UI
GET /api/dashboard          → payload penuh (live, analisa, prediksi, coverage)
GET /api/candles?count=N&before=<epoch>   → paging candle historis utk chart interaktif
GET /api/mt5/status | /api/history | /api/accuracy | /api/config
GET /api/executor           → status eksekutor + log eksekusi EA
GET /api/engine/run         → picu scan engine manual (±60 dtk)

# CSV EA (Common/Files/XAUUSDPattern/)
candles_m5.csv     ← sumber live (EA gabungan, rolling 5000, epoch GMT)
candles_m5_full.csv← arsip full history (EA Exporter lama, opsional, ≤2 thn)
heartbeat.txt      ← status EA (heartbeat tiap candle M5)
signal.txt         → sinyal utk eksekutor (server tulis, EA baca)
exec_log.txt       ← hasil eksekusi (EA tulis, server baca)
exec_state.txt     ← id sinyal terakhir (anti duplikat, tahan restart)
patterns.db        → data/patterns.db (SQLite, semua candle + hasil engine)
```

Parameter aktif: `config.json` — threshold 90%, top 20, candles_per_pattern 10, **update_every 1 candle (tiap candle baru)**, time_display "UTC", **predict_mode "topk_median"**, **predict_top_k 10**, `auto_trade` aktif (lot 0.01 / lot_strong 0.05, prob_min 75, rr_min 1.0, rr_min_trend 1.0, trend_period 13, max_positions 20, maks 5 order per candle).

---

## Eksekutor MT5 (11 Nov 2026) — PERUBAHAN PRINSIP: riset → eksekusi demo otomatis

> Permintaan user 11 Nov 2026: hasil prediksi dieksekusi langsung ke MT5, **akun demo**.
> Prinsip "riset saja" diperluas: eksekusi otomatis hanya demo, default **MATI**.

| Komponen | Peran |
|---|---|
| `executor.py` | Hitung sinyal (logika identik Saran Riset: SL band 80% candle sama, TP median, prob ≥55%/≤45%, R:R ≥ `rr_min`) → tulis `signal.txt` (maks `max_orders_per_candle`: R:R terbaik + candle pertama layak). Tulis header `NO` saat mati/idle. Baca `exec_log.txt`. |
| `ea/XAUUSDPatternExecutor.mq5` | EA di MT5 (chart bebas): baca `signal.txt` tiap 1 dtk → **tolak bila akun bukan DEMO (tanpa pengecualian)** → **tolak sinyal basi (umur anchor > 12 menit)** → cek maks posisi → validasi SL/TP vs harga → order market via CTrade (magic 20261111) → tulis `exec_log.txt` + `exec_state.txt` (anti duplikat, tahan restart). 1 order per tick. |
| UI `/api/executor` | Status eksekutor + alasan (tidak aktif, pasar tutup, dsb.) + log eksekusi. |

Aktivasi (berurutan): 1) EA dipasang di chart MT5 (akun **demo**), 2) set
`auto_trade.enabled = true` di `config.json`, 3) restart dashboard.
Lot bertingkat (permintaan user 11 Nov 2026): sinyal prob ≥ `prob_min`
(default 75%) → lot `lot_strong` (0.05); sinyal biasa 55–75% → lot `lot`
(0.01). **Exit kontradiksi**: sinyal kuat (≥ prob_min) arah berlawanan
dari posisi terbuka → posisi lawan ditutup dulu (profit = TP manual,
rugi = cut loss) sebelum order baru (ditangani di EA, tercatat di
exec_log sbg CLOSE_BUY/CLOSE_SELL). Filter tabel saran riset (R:R ≥ 1)
dipakai juga untuk eksekusi. **Filter tren** (permintaan user 12 Nov
2026, `trend_filter`, default aktif): tren dari **EMA `trend_period`
(default 13)** dibanding candle terakhir — candle utuh di bawah EMA
(high < EMA) = TURUN; utuh di atas EMA (low > EMA) = NAIK; EMA di
tengah candle (low ≤ EMA ≤ high) = SIDEWAYS → hanya sinyal dgn
R:R ≥ `rr_min` normal (1.0), bukan blok total.
Sinyal LAWAN tren diblok total walau R:R besar; sinyal SEARAH tren
cukup R:R ≥ `rr_min_trend` (1.0); sideways → `rr_min` normal. Aturan
sama dipakai tabel Saran Riset (badge tren di judul) agar tetap sinkron.

**Guard tren live PATTERN (13 Nov 2026)**: sinyal anchor bisa sudah
berubah arah saat EA mengeksekusi karena harga bergerak setelah candle
anchor tutup. Karena itu EA mengecek ulang candle M5 yang sedang berjalan
dengan EMA13 live: candle utuh di bawah EMA13 → BUY ditolak; candle utuh
di atas EMA13 → SELL ditolak; EMA di dalam candle (sideways) → tetap
boleh. Input `InpPatternLiveTrendGuard` (default true). Guard ini hanya
untuk PATTERN; aturan PULLBACK tidak memakai fungsi ini.

Pengaman tambahan (audit 12 Nov 2026): EA menolak sinyal yang anchor-nya
lebih tua dari **12 menit** (`MAX_SIGNAL_AGE_SEC`). Jadi jika server/engine
mati dan `signal.txt` tidak diperbarui, sinyal lama tidak akan dieksekusi
saat slot posisi kebetulan kosong — alasan `sinyal basi` tercatat di
`exec_log.txt`.

---

## 6. AUDIT & PERBAIKAN 12 NOV 2026

### Bug yang diperbaiki
1. **Proses dashboard ganda** — instance lama `python3 app.py 9090` (sejak 9 Nov) masih hidup dan menjalankan engine paralel ke DB yang sama; dimatikan. Hanya systemd `xauusd-dashboard` (port 8090) yang boleh jalan.
2. **Prediksi dummy menyesatkan** — saat engine belum punya hasil, API dulu mengirim prediksi sintetis (±4002) yang tampil seolah prediksi asli di samping candle broker. Sekarang `predicted_candles = []` dan UI menampilkan "belum ada prediksi".
3. **Dedup evaluasi akurasi hardcode 10** — run dengan N ≠ 10 dievaluasi salah; sekarang memakai jumlah prediksi run sebenarnya.
4. **Akurasi per-index hardcode 0–9** — sekarang mengikuti idx maksimum yang benar-benar dievaluasi.
5. **`update_every_n_candles = 0`** bisa memicu engine tiap 20 detik; sekarang di-clamp ≥ 1. `top_patterns` dibatasi 1–500, threshold 0–100, parsing `candles_per_pattern` aman.
6. **`last_candle` MT5 tidak tampil** bila data live berasal dari file selain `candles_m5.csv`; sekarang diambil dari sumber file yang benar-benar dipakai. Fallback simbol memakai `pair` dari config (bukan "XAUUSDc").
7. **EA bisa mengeksekusi sinyal basi** — jika server/engine mati, `signal.txt` lama tetap ACTIVE. EA sekarang menolak sinyal dengan umur anchor > 12 menit dan mencatat alasan `sinyal basi` di `exec_log.txt`.
8. **UI tidak jujur** — badge "Riset saja · Tanpa transaksi otomatis" tetap tampil padahal eksekutor demo aktif; footer/heading Saran Riset juga usang. Badge sekarang dinamis dari status eksekutor; heading/footer diperbarui.
9. **Saran Riset di mode `mean`** — dulu tetap menampilkan baris padahal eksekutor menolak mode selain `topk_median`; sekarang tabel menampilkan pesan bahwa saran hanya tersedia di mode `topk_median`.
10. **Log eksekutor lambat terlihat** — dulu ikut siklus candle (5 menit). Sekarang log eksekutor di-poll tiap 20 detik.
11. **EA hilang setelah restart container** — profil chart aktif ada di `MQL5/Profiles/Charts/Default` (folder `Profiles/Charts/Default` hanya default installer). EA Exporter + Executor digabung menjadi satu EA `XAUUSDPatternExecutor` v1.10 (kemudian dinaikkan ke v2.00 multi-strategi, lihat bagian 9); EA ditempatkan di chart XAUUSD **M5** yang tersimpan di profil (`chart01.chr`, H1 lama diubah ke M5). Profil dibersihkan menjadi **2 chart**: chart01 M5 Executor + chart02 H1 Exporter. Startup config `/config` sempat dicoba (16:28) tetapi **menambah 1 chart baru tiap restart** (chart05, chart06, ...), sehingga dinonaktifkan 23:41. Uji restart 16:46 UTC: hanya 2 EA load (Executor M5 + Exporter H1), profil tetap 2 chart, tanpa apply manual.
12. **Risiko EA ganda** — pengaman tetap ada: EA menulis heartbeat `inst_<chart>.txt`; hanya instance ChartID terkecil (**PRIMER**) yang trading + ekspor. Pada layout final hanya ada 1 instance Executor (PRIMER chart=97283309285477), tidak ada SEKUNDER. Guard berguna kalau EA tanpa sengaja dipasang di chart lain.

### Verifikasi setelah perbaikan (12 Nov 2026)
- `/api/dashboard`: 10/10 prediksi, similarity 99,12%, trend SIDE (EMA13), aturan eksekutor tersinkron.
- `/api/accuracy`: 7.105 baris evaluasi; per-index 10 (sesuai N=10).
- EA stale-guard ter-compile **0 error / 0 warning**; BOOT akun DEMO tercatat.
- Uji restart final (12 Nov 16:46 UTC): `docker restart linux-mt5` → hanya `XAUUSDPatternExecutor (XAUUSD,M5)` + `XAUUSDPatternExporter (XAUUSD,H1)` yang load; profil tetap 2 chart; heartbeat 16:50:00; **tidak ada chart baru**.
- EA gabungan v1.10 ter-compile **0 error / 0 warning**; hanya 1 instance Executor (PRIMER chart=97283309285477); guard PRIMER/SEKUNDER tetap aktif sebagai pengaman.
- Data live awal: heartbeat 16:10 UTC, candle terakhir 16:05 UTC, `signal.txt` NO (belum ada kandidat R:R ≥ 1.0 saat SIDEWAYS).

### Catatan operasional
- Restart container `linux-mt5` di Celeron lambat: wine butuh ±3 menit sebelum EA selesai `loaded successfully`. Jangan panik bila heartbeat belum berubah — cek log terminal `.../HFM Metatrader 5/logs/YYYYMMDD.log` untuk "expert XAUUSDPatternExecutor (XAUUSD,M5) loaded successfully". Profil final hanya 2 chart (M5 Executor + H1 Exporter); tidak ada chart startup baru.
- Perubahan `executor.py`/EA butuh restart service/container; perubahan `config.json` berlaku pada run engine berikutnya.
- EA Executor adalah **EA gabungan** (exporter + executor) dan menjadi jalur utama; EA Exporter lama hanya untuk backfill penuh. Setelah mengubah source EA: compile di `MQL5/Experts/XAUUSDPattern/` (path yang dipakai chart01 M5). Salinan `.ex5` di `MQL5/Experts/` (root) hanya untuk fallback bila startup config diaktifkan lagi.
- **Jangan apply EA manual lagi.** Kalau tanpa sengaja terpasang di dua chart, hanya instance ChartID terkecil yang trading — lihat baris `instance PRIMER/SEKUNDER` di `exec_log.txt`. Jika EA benar-benar hilang dari profil, restore backup profil atau pasang ulang di chart01 M5 — jangan buat chart baru.
- Saat audit profil chart: profil aktif = `MQL5/Profiles/Charts/Default` (berisi EA); `Profiles/Charts/Default` hanya default installer dan tidak dipakai.
- `signal.txt` memakai `prob` = peluang NAIK; SELL valid bila ≤45%, BUY valid bila ≥55%. `prob_min` (75) hanya ambang lot kuat & exit kontradiksi, bukan ambang eksekusi.
- **14 Nov 2026 — database 20 tahun:** `data/patterns.db` diganti dengan 1.501.314 candle M5 Dukascopy (2006-01-01 23:00 → 2026-11-13 21:55 UTC; 20,87 tahun). Sumber: `dukascopy-node` XAUUSD M5 bid. Old DB dibackup ke `backups/patterns-db-pre-dukascopy-20261114-121222.db`; DB lama aktif dihapus setelah health-check. Engine sekarang memakai sampai 2.000.000 candle (bukan 250.000), dan target coverage UI menjadi 20 tahun. Scan 1,5 juta candle di Celeron memakan ±2 menit; pantau beban saat market buka.

---

## 7. REDESAIN UI 13 NOV 2026 — "AURUM TERMINAL"

### Tampilan baru
- Tema dark premium dengan aksen emas, grid halus, panel glass, dan tipografi angka monospace.
- Hero 4 kartu: **harga terakhir + sparkline 60 candle**, **tren EMA13 + gauge**, **ring akurasi (hit ≤ $1) + rata-rata error**, dan **status eksekutor + lot/aturan**.
- Strip ringkasan pola (kemiripan, arah candle #1, update terakhir/engine), panel parameter collapsible yang tetap menampilkan nilai aktif.
- Chart utama lebih lega, toolbar candle/Live/Auto, garis waktu adaptif (label tidak tumpang tindih), plus panel replay pola vs aktual dan proyeksi median + band 80%.
- Chip sinyal aktif (BUY/SELL · lot · R:R) di panel Saran Riset; tabel lebih terbaca, coverage data punya progress bar.
- Responsif: kartu turun jadi 1 kolom, grid tabel `min-width: 0` agar tidak menimbulkan scroll horizontal, topbar solid agar teks chart tidak tembus.

### Perbaikan teknis yang ikut dilakukan
1. **`/api/dashboard` error setelah restart** — `history` tidak diinisialisasi saat engine belum selesai boot. Sekarang `history = []` di cabang fallback; API tetap 200 walau `ENGINE.last_result` masih `None`.
2. **Toolbar chart tidak berfungsi** — `IChart`/`ichart` diekspos dengan benar (global lexical binding + `window.IChart`), jadi tombol 30/60/120/300/600, Auto, dan Live benar-benar memanggil chart. Chart awal memakai 120 candle, bukan panjang pola (N).
3. **Canvas meninggi setiap render** — tinggi canvas sekarang eksplisit di CSS (`#chart-interactive` 400px, chart kecil 230px) dan pembacaan memakai `clientHeight`, bukan atribut bitmap yang berubah. Tidak ada lagi canvas 1.700px.
4. **Resize jendela** — `ResizeObserver` di chart + debounce 180 ms di `app.js`; setelah layout stabil chart digambar ulang. Label waktu memakai jarak minimum dan di-clamp agar tidak terpotong di tepi.
5. **Cache-busting** — `_index_html` sekarang juga menambahkan `?v=mtime` untuk `interactive_chart.js` (sebelumnya hanya CSS/app.js).
6. **Label waktu adaptif** — label sumbu-x chart utama dan chart perbandingan/prediksi mengurangi jumlah label sesuai lebar; label pertama/terakhir tidak terpotong.
7. **Overflow mobile** — `.panel`, `.grid-2 > .panel`, dan `.table-wrap` diberi `min-width: 0`/`max-width: 100%`; `docSW` sama dengan viewport pada uji 500px.

### Verifikasi (13 Nov 2026)
- Firefox headless + Selenium (bukan hanya screenshot): 1440px dan 500px.
- Semua data terisi: harga, EMA13, akurasi, 2 chip sinyal aktif, 10 baris prediksi, 5 baris Saran, 30 baris log eksekutor, 20 pola terbaik, 10 riwayat.
- Interaksi: tombol 60 mengubah chart ke 60 candle (tinggi tetap 398/400px), Auto ON/OFF berubah, panel parameter bisa dibuka.
- `document.documentElement.scrollWidth` = viewport (tidak ada scroll horizontal) di desktop maupun mobile 500px.
- Tidak ada error JavaScript halaman; `/api/dashboard`, `/api/executor`, `/api/accuracy`, `/api/history` semuanya HTTP 200.
- Backup file lama: `backups/ui-redesign-20261113-000233/` (index.html, style.css, app.js, interactive_chart.js, app.py).

### Catatan yang belum disentuh (bukan UI)
- Log eksekutor saat verifikasi masih memuat beberapa `refuse` dengan alasan **SL/TP salah sisi** pada sinyal BUY tertentu (SL band berada di atas bid saat eksekusi). Ini isu aturan SL/entry, bukan tampilan. Kandidat perbaikan yang masih menunggu keputusan: `SL minimum = max(band, spread × 2–3)`.

---

## 8. LOGIN ADMIN UNTUK PARAMETER 13 NOV 2026

### Perilaku UI
- Tombol **Masuk** ada di topbar (ikon gembok). Saat belum masuk, panel **Parameter riset** menampilkan kartu terkunci dan form parameter disembunyikan.
- Setelah masuk berhasil, form parameter ditampilkan, panel otomatis terbuka, dan badge ringkasan menampilkan `ambang …% · top … · N …`.
- Tombol admin di topbar berubah menjadi **Admin**; klik lagi untuk membuka dialog sesi dan **Keluar**.
- Modal masuk punya pesan error yang jelas, validasi field kosong, dan bisa ditutup dengan `Esc`/klik latar.
- Panel tetap terkunci setelah keluar; nilai form dibersihkan dari tampilan.

### Pengamanan backend
- Username: `admin` (bisa dioverride env `XAUUSD_DASH_USER`).
- Password: hanya disimpan sebagai **hash PBKDF2-SHA256 260.000 iterasi** di `config.json` bagian `auth`; tidak ada plaintext. Env `XAUUSD_DASH_PASS` bisa dipakai sebagai override sementara.
- Sesi memakai cookie `xau_admin` yang ditandatangani **HMAC-SHA256**, `HttpOnly`, `SameSite=Strict`, berlaku 12 jam. Secret sesi disimpan di `data/.session_secret` (mode 0600) agar sesi tetap valid setelah service restart.
- Endpoint yang dilindungi:
  - `GET /api/config` dan `POST /api/config` → **401** tanpa login.
  - `GET /api/engine/run` → **401** tanpa login.
- Endpoint publik tetap: `/api/dashboard`, `/api/executor`, `/api/accuracy`, `/api/history`, `/api/candles`, `/api/mt5/status`, serta `GET /api/auth/status`, `POST /api/login`, `POST /api/logout`.
- Respons config (GET maupun POST) **menghapus bagian `auth`** agar hash password tidak bocor ke browser.
- Pembatas brute force: maksimal **8 percobaan gagal / 15 menit per IP**, lalu HTTP 429.
- Ganti password kapan saja dengan:
  ```bash
  python3 set_admin_password.py
  ```
  Script meminta kata sandi baru + konfirmasi; service tidak perlu di-restart.

### Verifikasi (13 Nov 2026)
- Tanpa masuk: `GET/POST /api/config` → 401; tombol/form parameter terkunci.
- Masuk salah → 401 + pesan “Nama pengguna atau kata sandi salah”; masuk benar → 200 + cookie HttpOnly.
- Setelah masuk: form terisi `UTC / Asia / 90 / 20 / 10 / topk_median / 10`, `GET /api/config` → 200 tanpa field `auth`.
- Reload halaman saat sesi aktif → tetap masuk (cookie bertahan).
- Keluar → cookie dihapus, `GET /api/config` kembali 401, panel parameter terkunci lagi.
- Diuji dengan Firefox headless + Selenium desktop 1440px dan mobile 500px; modal tidak menimbulkan overflow horizontal.
- Tidak ada error JavaScript halaman.
- Backup pasca-fitur: `backups/auth-20261113-092314/` (kode, config hash, helper kata sandi, ROADMAP, dan file static).

---

## 9. RIWAYAT EA DUA STRATEGI — 13 NOV 2026

> Bagian ini adalah riwayat konfigurasi 13 Nov 2026 (PATTERN + PULLBACK, global 5). Konfigurasi aktif 16 Nov 2026 adalah **lima strategi, total 20 slot**, dijelaskan di bagian 10.

### Prinsip
- Tetap **satu file EA**: `ea/XAUUSDPatternExecutor.mq5` (versi 2.00). File ini menggabungkan exporter M5 + eksekutor PATTERN + strategi PULLBACK TREN.
- Tidak ada file `.mqh` tambahan; hanya include standar `<Trade\Trade.mqh>`.
- Nama file dan path chart tidak diubah agar chart01 M5 tetap auto-load setelah Docker restart. Isi EA-nya yang diganti, bukan nama file.
- Strategi berjalan berdiri sendiri: sinyal, magic, aturan entry, dan exit terpisah.

### Identitas posisi
| Strategi | Magic | Komentar order | Sumber sinyal |
|---|---:|---|---|
| PATTERN | `20261111` | `PAT-<id>` | `signal.txt` dari dashboard |
| PULLBACK TREN | `20261113` | `PB-<timestamp>-<B/S>` | dihitung mandiri di EA |

Magic adalah sumber kebenaran untuk mengelola/menutup posisi. Komentar hanya untuk tampilan. Log `exec_log.txt` diberi prefiks `[PATTERN]` atau `[PULLBACK]`.

### Batas risiko
- Slot PATTERN default **3**, PULLBACK default **2**, total global default **5**.
- Maksimal **2 entry per candle M5** untuk gabungan kedua strategi.
- Exit kontradiksi PATTERN hanya menutup posisi magic PATTERN; posisi PULLBACK tidak disentuh.
- Tidak ada filter lawan arah antar strategi. Entry PULLBACK tidak melihat posisi PATTERN, dan sebaliknya; masing-masing hanya dibatasi slot sendiri (3+2) dan batas global 5 posisi / 2 entry per candle.

### Aturan PULLBACK TREN
- Tren H1: EMA50 vs EMA200 + close H1 terakhir.
- Entry M5 hanya setelah candle selesai: pullback menyentuh EMA20 M5, lalu close kembali searah tren dan candle konfirmasi.
- SL di balik swing 3 candle + buffer ATR; SL maksimal 2,5 ATR; TP 1,5R.
- Exit: SL/TP, trailing setelah 1R, time stop 240 menit, atau tren H1 berbalik.
- Filter: sesi 07:00–21:00 UTC, spread maksimal 120 poin, maksimal 2 entry/hari, lot tetap 0.01.
- Mode bayangan tersedia lewat input `InpPullbackShadowOnly`.

### Pengaman yang dipertahankan
- Akun wajib DEMO; akun real ditolak.
- Anti EA ganda: hanya instance ChartID terkecil (PRIMER) yang trading/ekspor.
- Sinyal PATTERN lebih tua dari 12 menit ditolak.
- Satu id sinyal hanya diproses sekali; state disimpan di `exec_state.txt`.
- Peringatan otomatis bila akun bertipe NETTING, karena posisi XAUUSD bisa digabung broker.

### Status implementasi
- Kompilasi MetaEditor: **0 error, 0 warning**.
- Sumber proyek dan sumber MT5 sudah disamakan di `MQL5/Experts/XAUUSDPattern/XAUUSDPatternExecutor.mq5`.
- **Aktivasi 13 Nov 2026 07:05 UTC; restart final 07:13 UTC** setelah perbaikan format tiket log: terminal log mencatat `expert XAUUSDPatternExecutor (XAUUSD,M5) loaded successfully`; boot log `akun=DEMO ... pattern=ON pullback=ON ... pattern_magic=20261111 pullback_magic=20261113`.
- Hanya **satu EA** yang dimuat. Blok `<expert>` exporter lama sudah dihapus dari `chart02.chr`; chart tetap 2 (M5 executor + H1 tanpa EA).
- Tidak ada warning NETTING saat boot, jadi akun demo ini tidak terdeteksi sebagai netting; identitas magic PATTERN/PULLBACK dapat dipisahkan.
- **Revisi 13 Nov 2026 07:24–07:31 UTC**: filter lawan arah antar strategi dihapus total. Entry PULLBACK kini murni mengikuti aturan H1 trend + pullback M5 + ATR/RR, tanpa melihat posisi PATTERN. PULLBACK juga dievaluasi lebih dulu di timer agar order PATTERN tidak menghabiskan jatah 2 entry/candle. Slot tetap 3 PATTERN + 2 PULLBACK, total maksimal 5 posisi dan 2 entry per candle. Restart final 07:31 UTC, compile 0 error / 0 warning, EA loaded.
- **Bukti independensi 13 Nov 2026**: PULLBACK membuka 2 SELL (tiket `59323422976` pukul 08:00:01 UTC dan `59323507419` pukul 08:05:01 UTC) saat PATTERN masih memiliki posisi BUY. PATTERN tetap membuka BUY baru setelahnya. Trailing PULLBACK pada 11:27 UTC mengunci profit di SL 3891.22/3891.27; keduanya ditutup oleh trailing SL tersebut pada 11:46:43 UTC dengan hasil kira-kira +5,94 dan +5,85 USD per 0,01 lot (sebelum biaya), sebelum time stop 240 menit tercapai.
- **Revisi guard tren live PATTERN 13 Nov 2026 13:21 UTC**: kasus BUY `PAT-c25ffc9e71ee` pukul 13:10:22 UTC terjadi saat candle M5 live sudah utuh di bawah EMA13 (high 3887.89 < EMA 3890.07). Sinyal anchor 13:05 memang masih SIDEWAYS, tetapi harga bergerak turun sebelum fill. Ditambahkan guard khusus PATTERN (`InpPatternLiveTrendGuard`, default true) yang menolak BUY saat candle live di bawah EMA13 dan SELL saat candle live di atas EMA13. Compile 0 error / 0 warning, restart 13:21 UTC. PULLBACK tidak diubah.
- **Halaman Strategy Lab 14 Nov 2026**: route `/strategy-lab` ditambahkan ke dashboard sebagai papan riset strategi baru. Berisi 5 skill referensi (4 vendor + 1 lokal), pipeline 6 tahap, batas proyek, template brief, dan tracker kandidat lokal browser (`localStorage`). Tidak mengirim order, tidak mengubah EA/PULLBACK. Dokumen skill dapat dibuka read-only lewat route `/skills/...`.
- **Backtest runner 14 Nov 2026**: `backtest/backtest_runner.py` + `backtest/run_backtest.sh` dibuat terpisah dari runtime. Alur: snapshot SQLite read-only via backup API, CPU affinity 2,3 + nice (efektif 15 di environment ini), backtest Python read-only, output ke `backtest/results/run_*`, snapshot DB dihapus otomatis di `finally`/`atexit`. Dataset aktif 20 tahun = 1.501.314 bar unik; uji baseline EMA cross selesai ≈26 detik (wall ≈28,8 detik). Tidak menyentuh MT5, EA, signal/exec files, atau PULLBACK.
- **Strategy Tester UI 14 Nov 2026**: tab Strategy Tester di `/strategy-lab` + API `POST /api/backtest/run`, `GET /api/backtest/status|result|jobs|file`, `POST /api/backtest/cancel`. Job berjalan sebagai subprocess terpisah, satu job sekaligus, login admin untuk run/cancel, output + log per run, dan DB copy dibersihkan juga saat job dibatalkan. UI menampilkan metrik, per-tahun, file hasil, dan riwayat run.
- **EA generator draft 14 Nov 2026**: hasil backtest bisa langsung dijadikan draft `.mq5` dari tab Strategy Tester. File masuk `ea/generated/` (tidak menimpa EA aktif), magic sendiri, DEMO-only, hanya mengelola posisinya sendiri. Gate verdict `Layak diuji/Perlu revisi/Tolak` ditampilkan; draft tetap bisa dibuat meski belum lolos, dengan peringatan. Template pertama `ema_cross`; compile diuji 0 error/0 warning. Parameter/versi baru menghasilkan file baru, sehingga alur revisi tidak menimpa output lama.
- Backup source sebelum perubahan: `backups/ea-multistrategy-20261113-134036/`.
- Backup profil MT5 sebelum pelepasan exporter: `backups/mt5-profile-20261113-140453/`.
- **Model arah + kartu akurasi 8090 — 16 Nov 2026**: model arah selektif (RSI/Bollinger + filter tren H1 EMA50/200 + sesi) ditambahkan ke `pattern_engine.py`; `engine_runs` menyimpan `forecast_dir/confidence/rule`. Uji historis 2024-01-01 → 2026-11-16 (horizon 10 candle) di data 20 tahun: **53,44% arah benar** dari 17.703 sinyal (coverage 9,01%), high-confidence **55,95%** (613 sinyal). Sebelum filter H1, live sempat 36,36% pada 22 sinyal; karena sampel kecil dan mean-reversion melawan tren, model tidak dipromosikan. Kartu dashboard menampilkan **akurasi arah** (bukan hit ≤$1 yang hanya 7%) dan error terpisah; live ditampilkan di sub dan baru menggantikan validasi setelah ≥200 evaluasi arah. Akurasi/engine history direset setelah backup `backups/8090-pre-direction-20261116-113327/`; candle 20 tahun tidak diubah. Service 9090 DeepSeek dimatikan/disable, fokus 8090.
- **Strategy Monitor — 16 Nov 2026**: halaman `/strategy-monitor` dan API `/api/strategy-monitor` menampilkan lima strategi live DEMO: PATTERN, PULLBACK, Mean Reversion H1, Session Breakout, dan PATTERN+Forecast. Halaman read-only; order dieksekusi EA, bukan halaman. Sumber: `strategy_monitor.py`, `strategy_engine.py`, `backtest/run_strategy_backtests.py`, `static/strategy-monitor.*`.
- **Hasil backtest kandidat 16 Nov 2026**: mean reversion 20,87 tahun = 64.192 trade, win rate 38,44%, net -25.785,55, PF 0,68, max DD 258,28% → **Tolak**; OOS 2024–2026 = 8.638 trade, win rate 42,71%, net -3.283,46, PF 0,872, DD 33,25%. Session breakout = 4.317 trade, win rate 36,48%, net -1.932,06, PF 0,63, max DD 19,85% → **Tolak**; OOS 2024–2026 = 512 trade, win rate 42,97%, net -173,61, PF 0,869, DD 2,27%. Keduanya memakai spread 0,30 dan satu posisi; keduanya tetap **Tolak** di gate. Pada 16 Nov 2026 keduanya diaktifkan sebagai order DEMO atas permintaan eksplisit user, bukan promosi. Backtest memakai salinan DB read-only di `/tmp/opencode` yang dihapus otomatis, CPU affinity 2,3 + nice 10, dan output terpisah. Hasil tersimpan di `backtest/results/strategy_meanrev/` dan `strategy_breakout/`; monitor membaca ringkasan terbaru, menampilkan OOS, dan memakai verdict gate yang sama dengan EA generator.
- **Aktivasi order 5 strategi — 16 Nov 2026**: atas permintaan user, Mean Reversion, Session Breakout, dan PATTERN+Forecast diaktifkan sebagai order DEMO dengan magic sendiri. Alokasi slot: PATTERN **3**, PULLBACK **2** (tidak diubah), MEANREV **5** (magic 20261114), BREAKOUT **5** (20261115), CONFLUENCE **5** (20261116), total **20** posisi. `InpGlobalMaxPositions20=20`; `InpMaxOrdersPerCandle20` diset 5 (input lama tidak dipakai agar nilai tersimpan chart 5 tidak mengalahkan konfigurasi baru). Total posisi 20, tetapi maksimal 5 entry per candle M5. Compile MetaEditor **0 error, 0 warning**; boot log EA menunjukkan `slots=3+2+5+5+5 / global=20`. Catatan margin: saldo demo saat aktivasi ±$394 dan 5 posisi 0,01 XAUUSD sudah memakai margin ±$193; 20 posisi penuh kemungkinan ditolak margin sampai saldo dinaikkan.
- **Aturan order baru**: MEANREV entry RSI/Bollinger M5 + filter H1, SL 1,5 ATR, TP 2 ATR, time stop 10 bar. BREAKOUT range Asia 00–07 UTC, entry 07–12 UTC, SL 1,5 ATR, TP 2 ATR, time stop 12 bar, maksimal 1 entry/hari. CONFLUENCE hanya membuka order tambahan bila sinyal PATTERN searah forecast arah; lot 0,01; time stop 240 menit; PATTERN tetap maksimal 3. Semua strategi hanya menutup posisi dengan magic masing-masing.
- **Status kualitas**: MEANREV dan BREAKOUT masih **Tolak** di gate backtest/OOS; aktivasi live adalah keputusan eksplisit user untuk DEMO, bukan promosi. Monitor menampilkan peringatan tersebut. Bukti order live pertama: `MR-1794828000-S` SELL tiket `59347242809`, retcode `10009`.
- **Pemantauan posisi + audit otomatis — 16 Nov 2026**: EA menulis `positions.txt` setiap timer (magic, ticket, sisi, lot, entry, SL/TP, harga, floating P/L, waktu buka UTC). Dashboard membaca snapshot ini dan menampilkan tabel **Posisi terbuka** di `/strategy-monitor`, termasuk jumlah posisi dan floating P/L per strategi. Audit strategi baru berjalan tiap timer: MEANREV keluar bila tren H1 berbalik melawan posisi; BREAKOUT keluar bila harga kembali masuk range Asia (false breakout); CONFLUENCE keluar bila forecast tidak lagi searah; PATTERN/PULLBACK tetap memakai exit masing-masing. Pengaman margin `InpMarginBufferPct=20` mencegah order baru bila free margin tidak cukup; entry per candle dibatasi 5. Compile final **0 error, 0 warning**.
- **Perbaikan RR PATTERN — 17 Nov 2026**: penyebab SL lebih besar dari TP adalah `auto_trade.rr_min_trend=0.3`, yang membolehkan sinyal searah tren dengan reward/risk 0,3. Nilai diubah menjadi **1.0**. EA juga memakai `InpPatternMinRR=1.0`: order PATTERN ditolak bila RR aktual di harga eksekusi <1,0, dan posisi lama dengan RR awal <1,0 ditutup otomatis (`InpPatternExitOnBadRR=true`). Bukti: dua posisi SELL `59374792827` dan `59374792344` ditutup dengan alasan `exit audit: RR awal < 1 (TP lebih kecil dari SL)`; order berikutnya baru diterima setelah RR aktual ≥1,0. Compile **0 error, 0 warning**, boot log `pattern_min_rr=1.00`.
- **Auto exit PATTERN — 17 Nov 2026**: `InpPatternAutoExit=true`, `InpPatternMaxHoldMinutes=240`, `InpPatternExitOnTrendReversal=true`. EA menutup posisi PATTERN pada time stop atau bila H1 dan candle M5 live berbalik melawan posisi. Aturan entry PATTERN tidak diubah. PULLBACK sudah memiliki exit otomatis (SL/TP, trailing 1R, time stop 240 menit, H1 berbalik). Compile **0 error, 0 warning**; boot log `pattern_auto_exit=ON`.
- **Backup EA 20 slot**: `backups/ea-20slots-20261116-154954/` (sebelum aktivasi) dan `backups/ea-live-5strategies-20261116-162745/` dan `backups/ea-live-5strategies-20261116-162915/`, `backups/ea-live-5strategies-20261116-163508/`, dan `backups/ea-monitor-auto-20261116-182122/` dan `backups/ea-pattern-autoexit-20261117-084004/` dan `backups/ea-pnl-monitor-20261117-190912/` dan `backups/ea-pattern-rr-20261117-205558/` dan `backups/ea-pnl-rr-final-20261117-205810/` (sumber, `.ex5`, monitor P/L, dan dokumen final).
- **Catatan monitor**: endpoint memakai cache 10 detik agar refresh halaman tidak memicu scan berulang. Tren PATTERN dihitung fallback EMA13 bila state in-memory belum tersedia setelah restart. `update_every_n_candles` tetap 1 agar aturan PATTERN tidak berubah; beban scan penuh saat startup masih menjadi catatan operasional.
- Backup pekerjaan monitor: `backups/8090-monitor-final-20261116-144336/` (kode + halaman + dokumen final). Backup sebelum perubahan besar tetap tersedia di folder backup bertanggal sebelumnya.


---

## 10. EA LIMA STRATEGI, 20 SLOT, DAN MONITOR OTOMATIS — 16 NOV 2026

### Status aktif
- EA aktif: `XAUUSDPatternExecutor.mq5`, kompilasi MetaEditor **0 error, 0 warning**.
- Lima strategi berjalan di satu EA, semua **DEMO only**.
- Total slot posisi: **20**. Maksimal **5 entry per candle M5**.
- PATTERN tetap **3 slot**; PULLBACK tetap **2 slot** dan aturannya tidak diubah.

| Strategi | Magic | Slot | Sumber entry | Exit utama |
|---|---:|---:|---|---|
| PATTERN | `20261111` | 3 | `signal.txt` dari dashboard | SL/TP, exit kontradiksi, RR min 1.0, time stop 240 mnt, tren H1+M5 berbalik |
| PULLBACK | `20261113` | 2 | dihitung di EA | SL/TP, trailing 1R, time stop 240 mnt, tren H1 berbalik |
| MEANREV | `20261114` | 5 | RSI/Bollinger M5 + filter H1 | SL 1,5 ATR, TP 2 ATR, time stop 10 bar, audit H1 |
| BREAKOUT | `20261115` | 5 | breakout range Asia 00–07 UTC, entry 07–12 UTC | SL 1,5 ATR, TP 2 ATR, time stop 12 bar, audit false breakout |
| CONFLUENCE | `20261116` | 5 | sinyal PATTERN searah forecast arah | SL/TP sinyal, time stop 240 mnt, audit forecast berbalik |

### Audit otomatis posisi baru
EA memeriksa posisi setiap timer:
- **MEANREV**: keluar bila tren H1 berbalik melawan posisi.
- **BREAKOUT**: keluar bila harga kembali masuk range Asia setelah breakout (false breakout).
- **CONFLUENCE**: keluar bila forecast menjadi netral atau berbalik melawan posisi.
- **PATTERN**: time stop 240 menit, exit bila H1 + candle M5 live berbalik melawan, dan exit bila RR aktual <1.0; entry tidak diubah. Exit kontradiksi lama tetap aktif.
- **PULLBACK**: tetap memakai exit yang sudah ada (SL/TP, trailing 1R, time stop 240 menit, H1 berbalik); tidak diubah.
- **Margin guard**: order baru ditolak bila free margin setelah entry berada di bawah buffer `InpMarginBufferPct=20%`.
- **Max entry/candle**: 5, meskipun total slot 20.

### P/L per strategi dan riwayat harian
- EA menulis `pnl.txt` setiap 60 detik dari history deal MT5 (maksimal 180 hari): `META;<tanggal_server>` dan `PNL;<tanggal>;<magic>;<strategi>;<jumlah_trade_tutup>;<realized>`.
- Realized = profit + swap + komisi pada deal keluar, dalam mata uang akun (USD). Floating diambil dari `positions.txt`.
- API mengirim `pnl.realized_total`, `pnl.floating_total`, `pnl.total`, `pnl.per_strategy`, `pnl.daily`, `pnl.today`, dan `pnl.updated`.
- Halaman `/strategy-monitor` menampilkan **Total P/L**, tabel **P/L per strategi** (trade tutup, realized, floating, total, posisi), serta **riwayat P/L harian** per strategi dan total.
- Tanggal mengikuti hari server broker. Data historis bergantung pada deal yang tersedia di history MT5; bukan rekonstruksi dari `exec_log`.

### Monitor posisi
- EA menulis `positions.txt` di folder Common/Files setiap timer.
- Format: `POS;magic;strategi;ticket;sisi;lot;entry;sl;tp;harga;profit;waktu_buka_utc`.
- API `/api/strategy-monitor` membaca snapshot dan mengirim `open_positions`, `floating_pnl`, `position_count`, `positions_updated`.
- Halaman `/strategy-monitor` menampilkan tabel **Posisi terbuka**, floating P/L, dan aturan audit.
- Cache API 10 detik; halaman refresh 20 detik; EA audit berjalan tiap timer (1 detik).
- Halaman hanya baca; order tetap dieksekusi EA.

### Bukti live
- Boot log EA: `slots=3+2+5+5+5 / global=20`.
- Order MEANREV pertama sukses: `MR-1794828000-S`, SELL tiket `59347242809`, retcode `10009`.
- PATTERN dan CONFLUENCE juga sudah membuka order live DEMO.
- Snapshot posisi aktif sudah terbaca dashboard (contoh 7 posisi: 2 PATTERN + 5 MEANREV) dan floating P/L tampil.

### Batas dan catatan
- MEANREV dan BREAKOUT masih **Tolak** di backtest/OOS. Aktivasi live adalah keputusan user untuk DEMO, bukan promosi atau jaminan profit.
- CONFLUENCE dapat membuka order tambahan pada sinyal PATTERN yang sama bila forecast searah; ini disengaja dan tetap dibatasi slot 5.
- Saldo demo saat aktivasi ±$346–$402. Margin tidak cukup untuk 20 posisi 0,01 XAUUSD sekaligus; margin guard akan menghentikan penambahan sebelum margin kritis. Untuk memakai 20 slot penuh, saldo demo perlu ditambah.
- AutoTrading MT5 harus tetap aktif. Jika dimatikan, order gagal dengan retcode `10027`.
- PATTERN/PULLBACK tidak diberi audit diskresioner baru; perubahan aturan keduanya memerlukan persetujuan eksplisit.
- Source separation Dukascopy/HFM dan `update_every_n_candles` masih pending; engine tetap memakai interval 1 candle agar aturan PATTERN tidak berubah.
- File terkait: `ea/XAUUSDPatternExecutor.mq5`, `strategy_monitor.py`, `strategy_engine.py`, `backtest/run_strategy_backtests.py`, `static/strategy-monitor.html`, `static/strategy-monitor.css`, `static/strategy-monitor.js`, `app.py`, `ea_generator.py`.
- Backup: `backups/ea-20slots-20261116-154954/`, `backups/ea-live-5strategies-20261116-162745/`, `backups/ea-live-5strategies-20261116-162915/`, `backups/ea-live-5strategies-20261116-163508/`, `backups/ea-monitor-auto-20261116-182122/`.
