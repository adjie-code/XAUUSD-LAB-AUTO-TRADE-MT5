MT5 Linux Native (Docker)
=========================

Cara pakai singkat:

1) Unduh paket installer MT5 Linux (.deb) dari sumber resmi MetaQuotes, lalu simpan sebagai:

   /DATA/AppData/mt5-dockerized/linux/native-mt5/mt5-linux.deb

2) Bangun image dan jalankan service baru bernama `linux-mt5-native`:

   docker compose -f /DATA/AppData/mt5-dockerized/linux/docker-compose.yml build linux-mt5-native
   docker compose -f /DATA/AppData/mt5-dockerized/linux/docker-compose.yml up -d linux-mt5-native

3) Akses UI noVNC di http://<host>:17081 (VNC di :5901 jika diperlukan).

Data persisten berada di:

   /DATA/AppData/mt5-dockerized/linux/linux-mt5-native-data  (dipetakan ke /home/mt5 di kontainer)

Migrasi data dari kontainer Wine lama (opsional):

- Salin folder Profiles/ dan Bases/.../history/*.hcc dari:
  /DATA/AppData/mt5-dockerized/linux/linux-mt5-data/wine-prefix/.mt5/drive_c/Program Files/HFM Metatrader 5/
  ke direktori data MT5 Linux di /DATA/AppData/mt5-dockerized/linux/linux-mt5-native-data setelah kontainer pertama kali membuat struktur foldernya.

Catatan:

- Service ini membutuhkan file .deb yang valid. Jika build gagal karena dependensi, jalankan build ulang; Dockerfile sudah mengeksekusi `apt-get -f install` untuk memperbaiki dependensi.
- Default layar 1920x1080; ubah di start.sh jika diperlukan.
