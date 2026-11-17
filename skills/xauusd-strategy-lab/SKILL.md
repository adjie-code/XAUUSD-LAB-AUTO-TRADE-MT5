---
name: xauusd-strategy-lab
description: >
  Panduan lokal proyek XAUUSD Pattern Dashboard untuk menambah strategi
  trading baru ke EA XAUUSDPatternExecutor.mq5 secara aman dan bertahap:
  hipotesis, aturan entry/exit, backtest, validasi MT5, demo, lalu promosi.
  Gunakan saat merancang strategi baru, menguji ide strategi, mengevaluasi
  kesiapan strategi, atau menyusun bukti sebelum mengaktifkannya. Wajib
  strategi mandiri dengan magic dan exit sendiri, tidak memblokir strategi
  lain, dan tidak mengubah PULLBACK.
---

# XAUUSD Strategy Lab

Panduan kerja untuk menambah strategi **baru** di proyek ini tanpa merusak
strategi yang sudah berjalan. Ini dokumen referensi, bukan EA dan bukan
perintah untuk mengubah kode.

## Konteks yang harus dibaca lebih dulu (read-only)

1. `ROADMAP.MD` bagian 9 — prinsip EA gabungan, magic, slot, batas risiko.
2. `ea/XAUUSDPatternExecutor.mq5` — perilaku nyata EA saat ini.
3. `config.json` — parameter dashboard dan `auto_trade`.
4. `skills/SOURCES.md` — asal dan lisensi skill vendor.

Fakta yang tidak boleh ditebak:

| Hal | Nilai saat ini |
|---|---|
| EA | `ea/XAUUSDPatternExecutor.mq5`, satu file, DEMO only |
| PATTERN | magic `20261111`, sinyal dari `signal.txt`, slot 3 |
| PULLBACK | magic `20261113`, dihitung mandiri, slot 2, **dibekukan** |
| MEANREV | magic `20261114`, dihitung mandiri, slot 5 |
| BREAKOUT | magic `20261115`, dihitung mandiri, slot 5 |
| CONFLUENCE | magic `20261116`, sinyal PATTERN + forecast, slot 5 |
| Batas global | maksimal 5 posisi, maksimal 2 entry per candle M5 |
| Simbol/timeframe | XAUUSD, M5 (tren PULLBACK memakai H1) |
| Status akun | demo; akun real ditolak EA |

Konsekuensi penting: total slot live sekarang **20** (PATTERN 3 + PULLBACK 2
+ MEANREV 5 + BREAKOUT 5 + CONFLUENCE 5). Aktivasi ini adalah keputusan
eksplisit user 16 Nov 2026. Jangan menambah strategi baru tanpa alokasi slot
eksplisit; jangan mengambil slot PATTERN/PULLBACK. PULLBACK tetap dibekukan.
MEANREV dan BREAKOUT masih **Tolak** di gate backtest tetapi dijalankan DEMO
atas permintaan user, bukan sebagai promosi.

## Alur wajib

### 1. Hipotesis

Tulis satu kalimat yang bisa difalsifikasi:

> "Pada kondisi X, di XAUUSD M5, entry Y setelah Z menghasilkan ekspektasi
> positif setelah biaya, dengan batas rugi W."

Wajib ada:

- sumber edge (perilaku pasar, bukan "indikator terlihat bagus");
- kondisi berlaku (rezim tren/range, sesi, volatilitas);
- **kill criteria**: hasil apa yang menyatakan ide ini salah;
- bedanya dengan PATTERN dan PULLBACK — kalau sama, tidak perlu strategi baru.

Gunakan `vendor/tradermonty-claude-trading-skills/trade-hypothesis-ideator/`
untuk format kartu hipotesis, dan `vendor/agiprolabs-claude-trading-skills/regime-detection/`
bila ide bergantung pada rezim pasar. Jangan menganggap skor atau contoh di
skill vendor sebagai hasil proyek ini.

### 2. Aturan entry dan exit

Turunkan hipotesis menjadi aturan yang bisa dikodekan:

- **Data & timeframe:** candle apa, sudah close atau live, butuh data H1/M5 apa.
- **Entry:** syarat tepat, urutan evaluasi, filter sesi/spread, maksimal 1
  sinyal per setup.
- **Exit:** SL, TP, trailing, time stop, exit kondisi tren. Harus dimiliki
  strategi ini sendiri.
- **Ukuran posisi:** lot tetap untuk demo; jangan menaikkan risiko diam-diam.
- **Parameter:** daftar input, nilai default, dan rentang uji. Parameter yang
  terlalu banyak = risiko overfit.

Gunakan `vendor/tradermonty-claude-trading-skills/edge-strategy-designer/`
untuk membuat draf varian (core/konservatif/probe). Terjemahkan hasilnya ke
istilah proyek ini; jangan membawa skema YAML upstream mentah-mentah ke EA.

**Aturan identitas (wajib):**

- Magic baru yang belum dipakai, berbeda dari `20261111` dan `20261113`.
  Catat nomornya di dokumen rencana sebelum implementasi.
- Exit hanya menutup posisi dengan magic sendiri. Jangan menyapu semua posisi
  XAUUSD, jangan menutup posisi PATTERN/PULLBACK.
- Log diberi prefiks strategi baru agar bisa dipisahkan di `exec_log.txt`.
- Tidak memblokir strategi lain: entry baru tidak boleh bergantung pada ada/
  tidaknya posisi strategi lain, dan tidak boleh menghabiskan jatah 2 entry
  per candle untuk dirinya sendiri secara sepihak.

### 3. Backtest

Gunakan data proyek (`data/`, alat `backfill_dukascopy.py` / `import_csv.py`)
atau data MT5. Periksa dulu cakupan tanggal, kualitas tick, dan simbolnya.

Minimal yang harus dilaporkan:

- periode in-sample dan out-of-sample yang terpisah;
- biaya realistis: spread (filter PULLBACK memakai batas 120 poin; uji juga
  kondisi lebih buruk), komisi, slippage;
- jumlah trade yang cukup; jangan menyimpulkan dari belasan trade;
- profit factor, expectancy per trade (R), max drawdown, win rate, rata-rata
  durasi, distribusi hasil per bulan;
- uji parameter di sekitar nilai default (robustness), bukan hanya satu
  setting terbaik;
- uji rezim berbeda: tren naik, tren turun, range, volatilitas tinggi.

Ikuti metodologi `vendor/tradermonty-claude-trading-skills/backtest-expert/`.
Prinsipnya: cari strategi yang paling sedikit rusak, bukan yang paling
menjanjikan di satu backtest.

**Kejujuran hasil:** selama belum diukur, statusnya "belum diuji". Jangan
menulis "profitable", "akurat", atau angka hasil tanpa menyebut sumber data,
periode, biaya, dan jumlah trade. Jangan menyalin hasil contoh dari skill
vendor.

### 3b. Monitor per strategi

Halaman `/strategy-monitor` menampilkan lima strategi live DEMO: PATTERN,
PULLBACK, MEANREV, BREAKOUT, dan CONFLUENCE/PATTERN+Forecast. Gunakan halaman
ini untuk memeriksa status, sinyal terbaru, verdict gate, dan OOS. Halaman
read-only; order tetap dieksekusi EA.

- Backtest kandidat shadow dijalankan dengan
  `python3 backtest/run_strategy_backtests.py`. Skrip membuat snapshot SQLite
  read-only di `/tmp/opencode`, memakai CPU affinity 2,3 + nice, menulis hasil
  ke `backtest/results/strategy_*`, dan menghapus snapshot otomatis.
- Ringkasan memuat hasil penuh dan pemisahan OOS 2024-2026. Jangan menganggap
  hasil penuh sebagai bukti OOS; gate tetap memakai verdict yang sama.
- Kandidat dengan verdict **Tolak** tidak boleh dipromosikan. Pengecualian
  DEMO 16 Nov 2026 dicatat sebagai keputusan user, bukan promosi.
- Halaman monitor tidak mengirim order; order dieksekusi EA dengan magic
  masing-masing. Monitor tidak mengubah aturan, exit, magic, atau perilaku
  PATTERN/PULLBACK.
- EA menulis `positions.txt`; dashboard menampilkan posisi terbuka dan floating
  P/L. Audit otomatis strategi baru: MEANREV keluar bila H1 berbalik melawan,
  BREAKOUT keluar bila harga kembali ke range Asia, CONFLUENCE keluar bila
  forecast tidak searah. PATTERN/PULLBACK memakai exit yang sudah ada.
- Pengaman margin `InpMarginBufferPct` dan batas 5 entry per candle wajib
  dipertahankan.
- EA menulis `pnl.txt` (realized dari deal keluar per hari per magic) selain
  `positions.txt`. Dashboard menampilkan total P/L, P/L per strategi, dan
  riwayat P/L harian. Realized memakai mata uang akun dan tanggal server broker.

### 4. Validasi MT5

- Kompilasi di MetaEditor: target **0 error, 0 warning**.
- Uji di Strategy Tester dengan simbol, timeframe, dan set file yang sama
  dengan rencana demo.
- Utamakan tick nyata; bandingkan hasil tick vs bar untuk melihat
  sensitivitas.
- Pastikan perilaku exit benar: hanya magic baru yang ditutup, PULLBACK dan
  PATTERN tidak tersentuh.
- Cek akun demo, bukan real.

`vendor/tradermonty-claude-trading-skills/mt5-robot-tester/` bisa menjadi
referensi batch test, tetapi skripnya menjalankan `terminal64.exe` dan
**butuh Windows + MT5**. Jangan mencoba menjalankannya di Linux ini, dan
jangan menginstal dependensi tanpa izin.

### 5. Demo

- Aktifkan dulu dalam mode bayangan/signal-only bila memungkinkan, lalu lot
  tetap kecil (mis. 0.01) setelah disetujui.
- Tetapkan ambang observasi sejak awal (contoh heuristik: 30 trade atau 4
  minggu, mana yang lebih dulu) dan jangan mengubahnya setelah melihat hasil.
- Bandingkan demo vs backtest: slippage, spread nyata, jumlah sinyal, exit.
- Siapkan stop criteria: jika drawdown atau deviasi melewati batas, matikan
  strategi lewat input-nya. Jangan mematikan atau mengubah PULLBACK.

### 5b. Generator draft EA

Setelah backtest selesai di Strategy Tester, draft EA bisa dibuat dari hasil
tersebut:

- Buka hasil run di `/strategy-lab` → **Generate EA**.
- Generator hanya mendukung strategi yang sudah punya template; versi pertama
  `ema_cross`.
- Output `.mq5` masuk ke `ea/generated/`, bukan menimpa EA aktif.
- EA memakai magic sendiri dan hanya mengelola posisinya sendiri.
- Verdict backtest ditampilkan. Jika belum lolos gate, draft masih boleh dibuat
  untuk eksperimen, tetapi **jangan** dipromosikan sebelum direvisi.
- Compile wajib 0 error/0 warning. Generated EA tetap harus diuji ulang di MT5
  dan demo; backtest Python bukan jaminan hasil live.
- Jika tidak cocok: ubah parameter, jalankan backtest lagi, lalu generate versi
  baru. Jangan menimpa file lama.

### 6. Promosi

Promosi bukan otomatis. Butuh:

1. bukti backtest + validasi MT5 + demo yang konsisten;
2. rekomendasi tertulis: magic, slot, batas risiko, cara mematikan;
3. **persetujuan eksplisit user**;
4. backup sebelum menyentuh EA (ikuti pola folder `backups/`);
5. compile 0 error/0 warning, restart, dan log boot yang menunjukkan magic
   serta status strategi;
6. pembaruan dokumentasi proyek (mis. `ROADMAP.MD`) sebagai pekerjaan
   terpisah setelah disetujui.

Jika salah satu gate gagal, hentikan atau kembalikan ke tahap sebelumnya.
Jangan memaksa promosi dengan melonggarkan aturan PULLBACK/PATTERN.

## Checklist ringkas

**Sebelum coding**

- [ ] Hipotesis falsifiable dan kill criteria tertulis.
- [ ] Magic baru sudah dipilih dan tidak bentrok.
- [ ] Alokasi slot disetujui; tidak mengambil slot strategi lain.
- [ ] Aturan entry/exit lengkap, termasuk filter dan batas harian.
- [ ] Rencana backtest (data, periode, biaya, metrik) tertulis.

**Sebelum demo**

- [ ] Backtest in-sample/out-of-sample dan uji parameter selesai.
- [ ] Hasil dilaporkan apa adanya, termasuk hal yang gagal.
- [ ] Kompilasi 0 error/0 warning.
- [ ] Exit hanya menyentuh magic sendiri.
- [ ] Tidak ada perubahan pada PULLBACK (dan PATTERN tanpa persetujuan).

**Sebelum promosi**

- [ ] Hasil demo dibandingkan dengan backtest.
- [ ] Stop criteria dan cara disable jelas.
- [ ] Backup dibuat.
- [ ] Persetujuan user diperoleh.
- [ ] Log boot dan `exec_log.txt` menunjukkan identitas strategi yang benar.

## Anti-pola yang dilarang

- Mengubah PULLBACK (magic, aturan, slot, exit) untuk memberi tempat strategi baru.
- Memakai magic yang sama atau menutup posisi berdasarkan simbol saja.
- Menghapus/menonaktifkan guard akun demo.
- Menaikkan lot, batas posisi, atau batas entry per candle tanpa persetujuan.
- Melaporkan hasil backtest tanpa periode, biaya, dan jumlah trade.
- Menjalankan skrip vendor, menginstal dependensi, atau menyentuh MT5/Windows
  dari sesi yang tidak diminta.
- Menganggap dokumen di `skills/` sebagai EA aktif atau sebagai bukti hasil.
