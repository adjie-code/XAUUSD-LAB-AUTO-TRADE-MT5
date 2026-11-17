# XAUUSD Pattern Dashboard — GitHub / Docker

Salinan proyek untuk deployment mandiri:

- Dashboard Python di container.
- MT5 Linux/Wine di container terpisah.
- Login broker MT5 dari halaman `/broker`.
- Fleksibel untuk simbol broker: `XAUUSD`, `XAUUSDc`, `XAUUSDb`, `XAUUSDm`, `GOLD`, dll.
- Satu EA berisi lima strategi (PATTERN, PULLBACK, MEANREV, BREAKOUT, CONFLUENCE).

> **DEMO ONLY.** EA menolak akun real. Jangan gunakan kredensial real.

## Isi folder

```text
app.py, executor.py, pattern_engine.py, ...   dashboard
static/                                        UI dashboard + /broker
ea/XAUUSDPatternExecutor.mq5                   sumber EA
mt5/                                           source container MT5/Wine
mt5-ea/XAUUSDPattern/XAUUSDPatternExecutor.ex5 EA siap mount ke MT5
docker-compose.yml
Dockerfile
```

## Yang TIDAK disertakan (sengaja)

- `mt5-data/` (wine prefix, instalasi terminal, akun, history broker)
- `data/patterns.db` (database candle besar)
- `secrets/` (sesi broker)
- `.env` (password admin/konfigurasi lokal)
- `backups/`, hasil backtest, log

Semua itu dibuat/diisi saat runtime dan sudah masuk `.gitignore`.

## Menjalankan

1. Salin env:

```bash
cp .env.example .env
nano .env
```

Isi minimal:

```env
XAUUSD_DASH_PASS=password-admin-yang-kuat
# Simbol chart awal; sesuaikan broker bila perlu
MT5_SYMBOL=XAUUSDc
```

2. Build dan jalankan:

```bash
docker compose up -d --build
```

Build pertama MT5 cukup lama karena mengunduh Wine/MT5 dan dependencies.

3. Buka:

```text
http://IP-SERVER:8090/broker
```

Isi **nama broker, server MT5, username, password**, dan opsional simbol
XAUUSD broker. Dashboard akan:

- mencari `common.ini` MT5;
- menulis login/server ke config terminal;
- mengatur `[StartUp] Expert = XAUUSDPattern\XAUUSDPatternExecutor`, simbol, M5;
- mengaktifkan `[Experts] AllowLiveTrading=1`;
- meminta container MT5 restart.

Tunggu terminal MT5 selesai restart, lalu buka dashboard:

```text
http://IP-SERVER:8090/
```

Jika build MT5 tertentu tidak otomatis memakai `common.ini`, buka noVNC
`http://IP-SERVER:17080`, login akun di terminal, lalu attach EA
`XAUUSDPattern/XAUUSDPatternExecutor` ke chart M5. Setelah itu buka dashboard.

Terminal MT5 dapat dilihat lewat noVNC:

```text
http://IP-SERVER:17080
```

## Login admin dashboard

Login broker **bukan** login admin. Login admin memakai:

- `XAUUSD_DASH_USER`
- `XAUUSD_DASH_PASS`

dari `.env`. Jika password kosong, login admin tidak dapat dipakai.

## Fleksibilitas simbol XAUUSD

Ada dua lapis:

1. **Login page** menyimpan simbol aktual ke `config.json`
   (`auto_trade.symbol`) dan menambahkan kandidat.
2. **EA** memiliki `InpAutoSymbol=true`: jika `SYMBOL_TRADE` tidak tersedia,
   EA mencari simbol yang mengandung `XAUUSD` atau `GOLD` dan memilih yang
   tersedia di Market Watch.

Jika broker memakai nama yang tidak mengandung XAUUSD/GOLD, isi simbol
eksplisit di halaman login atau `MT5_SYMBOL` di `.env`.

## Database candle

Repo tidak membawa `patterns.db` agar ringan. Dashboard tetap bisa dibuka,
tetapi prediksi/backtest membutuhkan database candle. Letakkan database yang
sudah ada di:

```text
data/patterns.db
```

atau jalankan import/backfill dari MT5 setelah terminal tersambung. Jangan
commit database ke GitHub.

## Keamanan

- Jangan buka port MT5/VNC ke internet tanpa autentikasi.
- Ganti password admin.
- Jangan commit `.env`, `secrets/`, `mt5-data/`, atau `data/*.db`.
- `common.ini` berisi kredensial MT5 di volume server; batasi akses host.
- Gunakan akun **DEMO** sampai strategi tervalidasi.

## Upload ke GitHub

Repo lokal sudah diinisialisasi di folder ini. Tambahkan remote dan push:

```bash
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

Jangan pernah commit `.env`, `secrets/`, `mt5-data/`, atau `data/*.db`.

## Perintah operasional

```bash
docker compose logs -f dashboard
docker compose logs -f mt5
docker compose restart mt5
docker compose down
```

## Struktur strategi

| Strategi | Magic | Slot |
|---|---:|---:|
| PATTERN | 20261111 | 3 |
| PULLBACK | 20261113 | 2 |
| MEANREV | 20261114 | 5 |
| BREAKOUT | 20261115 | 5 |
| CONFLUENCE | 20261116 | 5 |

Total slot 20, maksimal 5 entry per candle. Audit otomatis dan P/L ada di
`/strategy-monitor`.
