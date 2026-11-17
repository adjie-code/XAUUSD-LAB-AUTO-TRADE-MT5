#!/usr/bin/env bash
# Wrapper backtest aman: CPU dibatasi, DB dibaca dari snapshot, output terpisah.
# Contoh:
#   ./backtest/run_backtest.sh --start 2018-01-01
#   CPUS=2,3 ./backtest/run_backtest.sh --start 2024-01-01 --end 2025-01-01
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPUS="${CPUS:-2,3}"
NICE="${NICE:-19}"
SCRIPT="$ROOT/backtest/backtest_runner.py"

if [[ ! -f "$SCRIPT" ]]; then
  echo "backtest_runner.py tidak ditemukan: $SCRIPT" >&2
  exit 1
fi

cd "$ROOT"
export PYTHONUNBUFFERED=1

if command -v taskset >/dev/null 2>&1; then
  exec nice -n "$NICE" taskset -c "$CPUS" python3 "$SCRIPT" "$@"
fi

echo "[limit] taskset tidak tersedia; hanya memakai nice" >&2
exec nice -n "$NICE" python3 "$SCRIPT" "$@"
