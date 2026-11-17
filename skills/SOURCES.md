# Sumber Skill Vendor

Tanggal fetch: **2026-11-14**. Metode: `git clone --depth 1` ke
`/tmp/opencode/skill-src/`, lalu salin folder skill dengan `cp -a`.
Salinan diverifikasi dengan `diff -r` terhadap clone upstream (identik).

## Ringkasan

| Skill | URL upstream | Commit upstream | Tanggal commit | Lisensi |
|---|---|---|---|---|
| `trade-hypothesis-ideator` | https://github.com/tradermonty/claude-trading-skills/tree/main/skills/trade-hypothesis-ideator | `3bd4b7a2c7329ffb5efef95db2e53d1125b3dc40` | 2026-11-13 | MIT — © 2026 TraderMonty |
| `edge-strategy-designer` | https://github.com/tradermonty/claude-trading-skills/tree/main/skills/edge-strategy-designer | `3bd4b7a2c7329ffb5efef95db2e53d1125b3dc40` | 2026-11-13 | MIT — © 2026 TraderMonty |
| `backtest-expert` | https://github.com/tradermonty/claude-trading-skills/tree/main/skills/backtest-expert | `3bd4b7a2c7329ffb5efef95db2e53d1125b3dc40` | 2026-11-13 | MIT — © 2026 TraderMonty |
| `mt5-robot-tester` | https://github.com/tradermonty/claude-trading-skills/tree/main/skills/mt5-robot-tester | `3bd4b7a2c7329ffb5efef95db2e53d1125b3dc40` | 2026-11-13 | MIT — © 2026 TraderMonty |
| `regime-detection` | https://github.com/agiprolabs/claude-trading-skills/tree/main/skills/regime-detection | `981e1d736cdc02bdc1c55c74ec9224e956414706` | 2026-09-02 | MIT — © 2026 AGIPro |

Repo upstream:

- https://github.com/tradermonty/claude-trading-skills
- https://github.com/agiprolabs/claude-trading-skills

## File lisensi yang disimpan

| Repo | File di repo ini |
|---|---|
| tradermonty/claude-trading-skills | `skills/vendor/tradermonty-claude-trading-skills/LICENSE` |
| agiprolabs/claude-trading-skills | `skills/vendor/agiprolabs-claude-trading-skills/LICENSE.md` |

Keduanya lisensi MIT lengkap dengan teks izin dan disclaimer. Tidak ada skill
vendor di folder ini yang **tanpa lisensi**. Jika kelak menambahkan skill yang
tidak punya lisensi, tulis jelas di tabel: **"tanpa lisensi — referensi saja,
jangan redistribusi"**.

## Catatan adaptasi

- Isi kelima folder skill disalin **utuh**: `SKILL.md`, `references/`,
  `scripts/`, `assets/`, `schemas/`, `prompts/`, `examples/`, dan
  `requirements.txt` bila ada. Tidak ada file upstream yang diubah, dihapus,
  atau diterjemahkan.
- Struktur internal skill dipertahankan; path relatif di dalam `SKILL.md`
  tetap berlaku selama folder skill tidak dipindah-pisah.
- Tidak ada skrip skill yang dijalankan dan tidak ada dependensi yang
  diinstal pada sesi ini.
- Tambahan lokal hanya: `skills/README.md`, `skills/SOURCES.md`, dan
  `skills/xauusd-strategy-lab/SKILL.md`. Ketiganya bukan bagian upstream.
- `trade-hypothesis-ideator`, `edge-strategy-designer`, dan `backtest-expert`
  memakai skrip Python dengan dependensi di `requirements.txt` masing-masing.
  `regime-detection` memakai `numpy`/`pandas`; dependensinya tidak disertakan
  sebagai file dan tidak diinstal.
- `mt5-robot-tester` menjalankan `terminal64.exe` secara headless. Skill ini
  **hanya berguna di Windows dengan MetaTrader 5 terpasang**; tidak dapat
  dijalankan di lingkungan Linux proyek ini apa adanya. Folder upstream tetap
  disimpan sebagai referensi, tetapi tidak dipakai oleh Strategy Lab.
- Skill vendor berbahasa Inggris dan memakai konvensi repo asal. Skill lokal
  `xauusd-strategy-lab` berbahasa Indonesia dan mengikat alurnya ke aturan
  proyek (DEMO only, magic terpisah, PULLBACK tidak diubah).

## Reproduksi

```bash
mkdir -p /tmp/opencode/skill-src
git clone --depth 1 https://github.com/tradermonty/claude-trading-skills.git \
  /tmp/opencode/skill-src/claude-trading-skills
git clone --depth 1 https://github.com/agiprolabs/claude-trading-skills.git \
  /tmp/opencode/skill-src/agiprolabs-claude-trading-skills
```

Commit di atas adalah snapshot saat fetch. `main` dapat berubah setelah tanggal
ini; gunakan commit tersebut bila butuh pembandingan yang setara.
