# Skills — Referensi Strategi XAUUSD Pattern Dashboard

Folder ini berisi **dokumen referensi dan skill pihak ketiga** untuk membantu
merancang strategi trading baru. Isinya **bukan bagian dari runtime**: tidak
dibaca oleh `app.py`, tidak dijalankan oleh EA, dan tidak memengaruhi trading.

> **Aturan utama:** folder `skills/` adalah bahan belajar dan panduan kerja.
> EA aktif tetap `ea/XAUUSDPatternExecutor.mq5` (DEMO only). Jangan
> menganggap contoh, skrip, atau angka di folder ini sebagai hasil uji proyek
> ini sampai benar-benar diukur ulang di data dan akun demo proyek.

## Isi folder

```text
skills/
├── README.md                     # file ini
├── SOURCES.md                    # URL upstream, commit, tanggal, lisensi
├── xauusd-strategy-lab/
│   └── SKILL.md                  # skill lokal: alur menambah strategi baru
└── vendor/
    ├── tradermonty-claude-trading-skills/
    │   ├── LICENSE               # MIT
    │   ├── trade-hypothesis-ideator/
    │   ├── edge-strategy-designer/
    │   ├── backtest-expert/
    │   └── mt5-robot-tester/
    └── agiprolabs-claude-trading-skills/
        ├── LICENSE.md            # MIT
        └── regime-detection/
```

Setiap folder vendor berisi `SKILL.md` dan aset pendukung (`references/`,
`scripts/`, `assets/`, `schemas/`, `prompts/`, `examples/`) sesuai upstream.
Salinan vendor **utuh, tanpa diterjemahkan dan tanpa diubah**.

## Daftar skill dan kegunaannya

| Skill | Asal | Kegunaan | Dipakai di tahap |
|---|---|---|---|
| `xauusd-strategy-lab` | Lokal proyek ini | Alur kerja menambah strategi baru: hipotesis → aturan entry/exit → backtest → validasi MT5 → demo → promosi, dengan batas proyek (magic sendiri, exit sendiri, tidak mengubah PULLBACK) | Semua tahap |
| `trade-hypothesis-ideator` | tradermonty | Mengubah observasi pasar/log trading menjadi hipotesis yang bisa difalsifikasi, lengkap dengan kill criteria | 1 — Hipotesis |
| `edge-strategy-designer` | tradermonty | Menurunkan konsep edge menjadi draf aturan strategi dan varian (core/conservative/probe) | 2 — Aturan entry/exit |
| `backtest-expert` | tradermonty | Metodologi backtest yang konservatif: biaya, slippage, robustness, hindari overfitting | 3 — Backtest |
| `mt5-robot-tester` | tradermonty | Pipeline uji EA di MT5 Strategy Tester lewat CLI (3 ronde, batch) | **Dilewati** — butuh Windows + MT5 |
| `regime-detection` | agiprolabs | Deteksi rezim pasar (tren/range, volatilitas) untuk filter atau pemilihan strategi | 1–2 — Hipotesis & filter rezim |

`mt5-robot-tester` tetap disimpan sebagai referensi, tetapi **tidak dipakai** di
environment Linux ini karena menjalankan `terminal64.exe` headless. Validasi MT5
dilakukan manual lewat MetaEditor/Strategy Tester di mesin yang sesuai.

## Cara pakai

1. **Mulai dari skill lokal.** Baca `xauusd-strategy-lab/SKILL.md` lebih dulu.
   Skill itu mengikat alur kerja ke aturan proyek ini dan menunjukkan kapan
   skill vendor dipakai.
2. **Buka skill vendor sesuai tahap.** Skill vendor ditulis dalam bahasa
   Inggris dan mengikuti konvensi repo asalnya. Gunakan sebagai metode, bukan
   sebagai kebenaran tentang proyek ini.
3. **Jangan menjalankan skrip vendor begitu saja.** Skrip di `scripts/`
   membutuhkan Python dan dependensi dari `requirements.txt` masing-masing
   skill. Instalasi dependensi dan eksekusi harus dilakukan sadar, terpisah
   dari runtime dashboard, dan tidak boleh menyentuh akun real.
4. **Catat bukti.** Setiap klaim hasil (backtest, demo) harus disertai
   periode data, simbol, timeframe, biaya, jumlah trade, dan metrik yang
   diukur. Jangan menyalin angka contoh dari dokumentasi upstream.
5. **Minta persetujuan sebelum mengubah EA.** Perubahan kode EA, `config.json`,
   atau dokumen proyek lain adalah pekerjaan terpisah dan butuh instruksi
   eksplisit dari user.

## Batasan yang wajib dipegang

- **DEMO only.** EA menolak akun real. Jangan menguji strategi baru di akun real.
- **PULLBACK tidak boleh diubah.** Aturan, magic `20261113`, slot, dan exit-nya
  dibekukan. Penambahan strategi tidak boleh "membuat ruang" dengan mengubah
  PULLBACK.
- **PATTERN tidak boleh diubah tanpa persetujuan.** Magic `20261111` dan
  aturan lamanya dipertahankan.
- **Satu file EA.** `ea/XAUUSDPatternExecutor.mq5` adalah satu-satunya file
  EA; tidak ada file `.mqh` tambahan.
- **Batas global tetap dihormati.** Slot PATTERN 3 + PULLBACK 2, total maksimal
  5 posisi, maksimal 2 entry per candle M5. Strategi baru harus punya alokasi
  slot yang disetujui, bukan mengambil slot strategi lain secara diam-diam.
- **Strategi baru harus mandiri.** Magic sendiri, aturan entry sendiri, exit
  sendiri; tidak menutup atau memblokir posisi strategi lain.

## Lisensi dan redistribusi

Semua skill vendor berlisensi **MIT** (lihat `SOURCES.md` dan file `LICENSE`
di tiap folder vendor). Jika folder ini dibagikan ke luar proyek, sertakan
file lisensi upstream. Untuk skill yang kelak ditambahkan tanpa lisensi,
tandai jelas: **"tanpa lisensi — referensi saja, jangan redistribusi"**.

## Kalau ada konflik

Jika nama folder skill bertabrakan dengan skill lain di masa depan, pertahankan
nama upstream dan pisahkan berdasarkan repo asal di dalam `vendor/`. Jangan
mengganti nama isi skill upstream; cukup tambahkan catatan di `SOURCES.md`.
