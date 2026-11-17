#!/usr/bin/env bash
# Download XAUUSD M5 Dukascopy 2006-01-01 -> 2026-11-14.
# Tidak menyentuh DB, MT5, EA, atau strategi yang berjalan.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RAW="$ROOT/backtest/data/dukascopy/raw"
CACHE="$ROOT/backtest/data/dukascopy/cache"
mkdir -p "$RAW" "$CACHE"

VERSION="1.51.1"
COMMON=(
  -i xauusd -t m5 -f csv -v
  --cache --cache-path "$CACHE"
  --waf-mode off
  --retries 3 --rate-limit-retries 5
  -bs 5 -bp 1000
  -dir "$RAW"
)

download_chunk() {
  local from="$1" to="$2" name="$3"
  local out="$RAW/$name.csv"
  if [[ -s "$out" ]] && [[ $(wc -l < "$out") -gt 10 ]]; then
    echo "[skip] $name sudah ada ($(wc -l < "$out") baris)"
    return 0
  fi
  rm -f "$out"
  echo "[download] $name ($from -> $to)"
  npx -y "dukascopy-node@$VERSION" \
    -from "$from" -to "$to" -fn "$name" "${COMMON[@]}"
  if [[ ! -s "$out" ]] || [[ $(wc -l < "$out") -le 10 ]]; then
    echo "[error] $name kosong/tidak valid" >&2
    return 1
  fi
  echo "[ok] $name: $(wc -l < "$out") baris, $(du -h "$out" | cut -f1)"
}

download_chunk 2006-01-01 2011-01-01 xauusd_m5_2006_2011
download_chunk 2011-01-01 2016-01-01 xauusd_m5_2011_2016
download_chunk 2016-01-01 2021-01-01 xauusd_m5_2016_2021
download_chunk 2021-01-01 2026-11-14 xauusd_m5_2021_2026

echo "[done] semua chunk tersedia di $RAW"
ls -lh "$RAW"
