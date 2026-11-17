# Data runtime

Folder ini sengaja tidak menyertakan `patterns.db` dari mesin asal karena
ukurannya besar dan tidak cocok untuk GitHub.

Letakkan database candle di:

```text
data/patterns.db
```

Database dibuat otomatis oleh `db_init.py` saat container dashboard mulai.
Untuk mengisi candle:

- impor CSV dari EA MT5, atau
- gunakan backfill Dukascopy, atau
- salin database yang sudah ada ke folder ini (jangan commit ke Git).

`direction_validation.json` boleh ikut karena hanya metadata validasi kecil.
