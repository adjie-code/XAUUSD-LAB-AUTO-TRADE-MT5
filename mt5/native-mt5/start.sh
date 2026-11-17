#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=${DISPLAY:-:1}

echo "[native-mt5] Starting Xvfb on ${DISPLAY}..."
Xvfb "${DISPLAY}" -screen 0 1920x1080x24 -nolisten tcp &
sleep 1

echo "[native-mt5] Starting fluxbox..."
fluxbox >/dev/null 2>&1 &

echo "[native-mt5] Starting x11vnc on 5901..."
x11vnc -display "${DISPLAY}" -rfbport 5901 -forever -shared -ncache 10 -nopw -xkb >/dev/null 2>&1 &

NOVNC_DIR="/usr/share/novnc"
if [ ! -d "$NOVNC_DIR" ]; then
  echo "[native-mt5] WARNING: noVNC assets not found at $NOVNC_DIR"
fi

echo "[native-mt5] Starting websockify (noVNC) on 17081..."
websockify --web="$NOVNC_DIR" 0.0.0.0:17081 localhost:5901 >/dev/null 2>&1 &

echo "[native-mt5] Locating MetaTrader 5 Linux binary..."
BIN=""
if command -v metatrader5 >/dev/null 2>&1; then
  BIN=$(command -v metatrader5)
fi
if [ -z "$BIN" ]; then
  BIN=$(find /opt /usr -type f -iname "*metatrader*" -executable 2>/dev/null | head -n1 || true)
fi

if [ -z "$BIN" ]; then
  echo "[native-mt5] ERROR: MT5 Linux binary not found. Make sure mt5-linux.deb was installed correctly during build."
  # Keep container alive for troubleshooting
  tail -f /dev/null
else
  echo "[native-mt5] Launching: $BIN"
  exec "$BIN"
fi
