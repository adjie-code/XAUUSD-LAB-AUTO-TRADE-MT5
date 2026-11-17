#!/usr/bin/env bash
# Bangun DB baru dari CSV Dukascopy, backup DB lama, swap, lalu health-check.
# MT5/EA tidak disentuh. Dashboard hanya berhenti sebentar saat swap.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RAW="$ROOT/backtest/data/dukascopy/raw"
STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$ROOT/backtest/results/dukascopy_rebuild_$STAMP"
NEW_DB="$ROOT/data/patterns_dukascopy_new.db"
LIVE_DB="$ROOT/data/patterns.db"
OLD_TMP="$ROOT/data/patterns.db.pre-dukascopy-$STAMP"
BACKUP="$ROOT/backups/patterns-db-pre-dukascopy-$STAMP.db"
SERVICE="xauusd-dashboard.service"
mkdir -p "$RUN_DIR" "$ROOT/backups"
exec > >(tee "$RUN_DIR/run.log") 2>&1

echo "[start] $STAMP"
if [[ ! -d "$RAW" ]]; then
  echo "[error] folder CSV belum ada: $RAW" >&2
  exit 1
fi
if ! ls "$RAW"/*.csv >/dev/null 2>&1; then
  echo "[error] tidak ada CSV di $RAW" >&2
  exit 1
fi

if [[ "${SKIP_IMPORT:-0}" == "1" ]]; then
  echo "[import] SKIP_IMPORT=1; memakai DB baru yang sudah ada: $NEW_DB"
  [[ -s "$NEW_DB" ]] || { echo "[error] DB baru tidak ada: $NEW_DB" >&2; exit 1; }
  python3 - "$NEW_DB" <<'PY'
import sqlite3, sys
con=sqlite3.connect(sys.argv[1])
n=con.execute('SELECT COUNT(*) FROM candles_m5').fetchone()[0]
con.close()
print(f'[import] DB baru: {n:,} bar')
if n < 1_200_000:
    raise SystemExit('DB baru terlalu kecil')
PY
else
  echo "[import] membangun DB baru..."
  python3 "$ROOT/backtest/import/import_dukascopy_csv.py" \
    --input-dir "$RAW" \
    --db "$NEW_DB" \
    --min-bars 1200000 \
    --report "$RUN_DIR/import_report.json"
fi

echo "[validate] cek DB baru..."
python3 - "$NEW_DB" <<'PY'
import sqlite3, sys
p=sys.argv[1]
con=sqlite3.connect(p)
n,lo,hi=con.execute('SELECT COUNT(*),MIN(t),MAX(t) FROM candles_m5').fetchone()
bad=con.execute('SELECT COUNT(*) FROM candles_m5 WHERE o<=0 OR h<=0 OR l<=0 OR c<=0 OR h<l OR h<MAX(o,c) OR l>MIN(o,c)').fetchone()[0]
dup=con.execute('SELECT COUNT(*)-COUNT(DISTINCT t) FROM candles_m5').fetchone()[0]
con.close()
print(f'[validate] bars={n:,} range={lo}..{hi} dup={dup} bad_ohlc={bad}')
if n < 1_200_000 or bad or dup:
    raise SystemExit('validasi DB baru gagal')
PY

echo "[stop] dashboard untuk swap..."
systemctl --user stop "$SERVICE" || true

echo "[backup] $BACKUP"
python3 - "$LIVE_DB" "$BACKUP" <<'PY'
import sqlite3, sys
src=sqlite3.connect(sys.argv[1])
dst=sqlite3.connect(sys.argv[2])
try:
    src.backup(dst)
finally:
    dst.close(); src.close()
PY
cp -a "$LIVE_DB" "$OLD_TMP"
cp -a "$NEW_DB" "$LIVE_DB"
rm -f "$LIVE_DB-wal" "$LIVE_DB-shm"

echo "[start] dashboard dengan DB baru..."
systemctl --user start "$SERVICE"

OK=0
for _ in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8090/api/dashboard || true)
  if [[ "$CODE" == "200" ]]; then OK=1; break; fi
  sleep 1
done

if [[ "$OK" -ne 1 ]]; then
  echo "[rollback] health-check dashboard gagal" >&2
  systemctl --user stop "$SERVICE" || true
  cp -a "$OLD_TMP" "$LIVE_DB"
  rm -f "$LIVE_DB-wal" "$LIVE_DB-shm"
  systemctl --user start "$SERVICE" || true
  exit 1
fi

python3 - "$LIVE_DB" <<'PY'
import sqlite3, sys
con=sqlite3.connect(sys.argv[1])
n,lo,hi=con.execute('SELECT COUNT(*),MIN(t),MAX(t) FROM candles_m5').fetchone()
con.close()
print(f'[health] DB aktif: {n:,} bar | {lo}..{hi}')
if n < 1_200_000:
    raise SystemExit('DB aktif terlalu kecil')
PY

# Old active DB dihapus; backup tetap ada untuk rollback manual.
rm -f "$OLD_TMP"
python3 - "$RUN_DIR/manifest.json" "$STAMP" "$BACKUP" <<'PY'
import json, sys, sqlite3
path, stamp, backup = sys.argv[1], sys.argv[2], sys.argv[3]
con=sqlite3.connect('data/patterns.db')
n,lo,hi=con.execute('SELECT COUNT(*),MIN(t),MAX(t) FROM candles_m5').fetchone()
con.close()
json.dump({
  'stamp': stamp,
  'active_db': 'data/patterns.db',
  'bars': n,
  'min_t': lo,
  'max_t': hi,
  'old_db_backup': backup,
  'old_active_db_deleted': True,
  'source': 'dukascopy-node xauusd m5 bid 2006-2026',
}, open(path,'w'), indent=2)
PY

echo "[done] DB baru aktif. Backup lama: $BACKUP"
echo "[done] output: $RUN_DIR"
