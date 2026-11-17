# Laporan Audit Fase 0 — XAUUSD Pattern Dashboard

Tanggal audit: 5 November 2026
Sifat: read-only, tanpa instalasi apa pun.

## Hasil Audit

| Komponen | Status | Detail |
|---|---|---|
| OS | ✅ | CachyOS (Arch, rolling), kernel 7.2.7-1-cachyos |
| Docker | ✅ | Docker 29.9.2 + Compose 5.6.1, service **active** |
| CasaOS | ✅ | Service `casaos` **active** |
| Python | ✅ | Python 3.14.8 + pip 26.2.2 (sudah terpasang, tidak perlu instalasi) |
| Internet umum | ✅ | pypi.org = HTTP 200 |
| Akses Dukascopy | ⚠️ | Bermasalah — lihat di bawah |
| Disk | ⚠️ | Root `/` cuma sisa **12 GB (90% terpakai)**. Data historis XAUUSD M5 10+ tahun cukup kecil (< 2 GB), aman, tapi perlu dipantau |
| RAM | ✅ | 9.6 GiB total, ~6.4 GiB tersedia (cukup untuk DTW 20 pola) |
| Port | ✅ | 80, 8080 dipakai; banyak port >5000 bebas (kandidat: **8090** untuk dashboard) |

## Temuan Penting: Akses Dukascopy

1. **DNS lokal salah jawab.** `datafeed.dukascopy.com` dijawab DNS lokal/router sebagai `202.169.44.80` (IP Indonesia → koneksi ditolak saat connect). DNS publik (1.1.1.1) memberi IP asli: `16.62.187.25` / `16.62.244.190`.
2. **Dengan DNS yang benar, koneksi HTTPS berhasil** — server merespons, tapi `429 Too Many Requests` / `503` → Dukascopy menolak request ini karena format/limit. Solusi di Fase 2: user-agent + header yang sesuai, retry + backoff, dan mengikuti aturan di https://www.dukascopy.com/wiki/en/development/data-export/
3. **Perbaikan DNS:** opsi paling bersih adalah mengubah resolver di host/router ke `1.1.1.1` + `8.8.8.8` (persetujuan user), atau opsi darurat: pin IP via konfigurasi aplikasi.

## Folder proyek

Roadmap menyebut `/DATA/AppData/xauusd-pattern-dashboard/`, folder aktual:
`/DATA/AppData/AI-Projek/xauusd-pattern-dashboard/` (berisi ROADMAP.MD + AUDIT_FASE0.md).

## Kesimpulan & Rekomendasi

- Lingkungan SUDAH SIAP untuk Fase 1 (dashboard + data dummy) — tidak perlu instalasi apa pun.
- Fase 2 (integrasi Dukascopy) harus menyelesaikan: DNS resolver + aturan header/limit Dukascopy.
- Folder proyek memakai jalur aktual di atas (bukan yang tertulis di roadmap).

## Backlog Fase 2 (bukan penghalang Fase 1)

- **DNS teracuni ISP:** DNS lokal menyisipkan IP palsu `202.169.44.80` untuk `datafeed.dukascopy.com`; IP asli `194.8.15.180` terbukti bisa diakses (unduh data .bi5 sukses, HTTP 200).
- Solusi tanpa instalasi: pin IP di `/etc/hosts` (butuh sudo, dikerjakan saat Fase 2) — `echo '194.8.15.180 datafeed.dukascopy.com' | sudo tee -a /etc/hosts`
- Fase 1 (dashboard + data dummy) **tidak terpengaruh** dan langsung dikerjakan.

## Langkah berikutnya (memerlukan persetujuan)

1. **Fase 1** — bangun dashboard dasar + data dummy (Python stdlib/HTML, tanpa instalasi).
