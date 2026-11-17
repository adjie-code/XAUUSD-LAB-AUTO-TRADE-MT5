#!/usr/bin/env python3
"""Login broker MT5 dari dashboard.

- Menyimpan sesi broker TANPA password.
- Menulis kredensial ke config/common.ini milik terminal MT5, lalu
  meminta service MT5 restart lewat HTTP.
- File kredensial tetap di volume server dan tidak boleh masuk Git.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRETS_DIR = Path(os.environ.get("BROKER_SECRETS_DIR", ROOT / "secrets"))
SESSION_PATH = SECRETS_DIR / "broker_session.json"
CONFIG_PATH = ROOT / "config.json"
MT5_DATA_ROOT = Path(os.environ.get("MT5_DATA_ROOT", "/mt5-data"))
CONTROL_URL = os.environ.get("MT5_CONTROL_URL", "http://mt5:3000").rstrip("/")
EXPERT_NAME = os.environ.get("MT5_EXPERT_NAME", "XAUUSDPattern\\XAUUSDPatternExecutor")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9._#-]{2,32}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_secrets() -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except OSError:
        pass


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _load_session() -> dict:
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _mask(login: str) -> str:
    login = str(login or "")
    if len(login) <= 3:
        return "*" * len(login)
    return login[:2] + "*" * max(3, len(login) - 4) + login[-2:]


def status() -> dict:
    s = _load_session()
    return {
        "connected": bool(s.get("connected")),
        "broker": s.get("broker"),
        "server": s.get("server"),
        "login": _mask(s.get("login")),
        "symbol": s.get("symbol"),
        "connected_at": s.get("connected_at"),
        "mt5_data_root": str(MT5_DATA_ROOT),
        "control_url": CONTROL_URL,
    }


def logout() -> dict:
    try:
        SESSION_PATH.unlink()
    except OSError:
        pass
    return {"ok": True}


def _find_common_ini() -> Path | None:
    if not MT5_DATA_ROOT.exists():
        return None
    candidates = []
    for p in MT5_DATA_ROOT.rglob("common.ini"):
        if p.parent.name.lower() != "config":
            continue
        if "MetaQuotes" not in str(p) or "Terminal" not in str(p):
            continue
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _decode_ini(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16").lstrip("\ufeff"), "utf-16"
    return raw.decode("utf-8-sig", errors="replace").lstrip("\ufeff"), "utf-8-sig"


def _encode_ini(text: str, encoding: str) -> bytes:
    if encoding == "utf-16":
        return text.encode("utf-16")
    return text.encode("utf-8-sig")


def _update_ini(text: str, updates: dict[str, dict[str, str]]) -> str:
    """Update key di section tertentu tanpa menghapus isi lain."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    out: list[str] = []
    current = None
    seen: dict[str, set[str]] = {}
    replaced: dict[str, set[str]] = {}

    def flush(section: str | None) -> None:
        if not section or section not in updates:
            return
        wanted = updates[section]
        got = replaced.setdefault(section, set())
        for key, value in wanted.items():
            if key not in got:
                out.append(f"{key}={value}")
                got.add(key)

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            flush(current)
            current = stripped[1:-1]
            seen.setdefault(current, set())
            out.append(line)
            continue
        if current and current in updates and "=" in line and not stripped.startswith(("#", ";")):
            key = line.split("=", 1)[0].strip()
            if key in updates[current]:
                if key not in replaced.setdefault(current, set()):
                    out.append(f"{key}={updates[current][key]}")
                    replaced[current].add(key)
                continue
        out.append(line)

    flush(current)

    for section, wanted in updates.items():
        if section in seen:
            continue
        out.append("")
        out.append(f"[{section}]")
        out.extend(f"{key}={value}" for key, value in wanted.items())

    return "\n".join(out).rstrip("\n") + "\n"


def _post(path: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        CONTROL_URL + path,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000).decode("utf-8", errors="replace")
            try:
                return {"ok": True, "status": resp.status, "body": json.loads(body)}
            except ValueError:
                return {"ok": True, "status": resp.status, "body": body}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _restart_mt5() -> dict:
    result = {"stop": None, "launch": None, "warnings": []}
    stop = _post("/api/mt5/stop")
    result["stop"] = stop
    if not stop.get("ok"):
        result["warnings"].append("MT5 stop API tidak merespons; mencoba launch.")
    launch = _post("/api/mt5/launch")
    result["launch"] = launch
    if not launch.get("ok"):
        result["warnings"].append("MT5 launch API gagal; buka/restart container MT5 manual.")
    return result


def _update_symbol_config(symbol: str) -> None:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    at = cfg.setdefault("auto_trade", {})
    at["symbol"] = symbol
    at["auto_symbol"] = True
    cands = at.get("symbol_candidates")
    if not isinstance(cands, list):
        cands = []
    if symbol and symbol not in cands:
        cands.insert(0, symbol)
    at["symbol_candidates"] = cands[:12]
    _atomic_write(CONFIG_PATH, (json.dumps(cfg, indent=2) + "\n").encode("utf-8"), 0o660)


def login(payload: dict) -> dict:
    broker = str(payload.get("broker") or "").strip()
    server = str(payload.get("server") or "").strip()
    account = str(payload.get("username") or payload.get("login") or "").strip()
    password = str(payload.get("password") or "")
    symbol = str(payload.get("symbol") or os.environ.get("MT5_DEFAULT_SYMBOL", "XAUUSD")).strip().upper()

    if not (2 <= len(broker) <= 64):
        raise ValueError("Nama broker wajib diisi (2-64 karakter).")
    if not (2 <= len(server) <= 96) or any(c in server for c in "\r\n;"):
        raise ValueError("Server broker wajib diisi (contoh: NamaBroker-Live).")
    if not (1 <= len(account) <= 64) or any(c in account for c in "\r\n;"):
        raise ValueError("Username/login MT5 wajib diisi.")
    if not (1 <= len(password) <= 256) or any(c in password for c in "\r\n"):
        raise ValueError("Password MT5 wajib diisi.")
    if symbol and not SYMBOL_RE.match(symbol):
        raise ValueError("Format simbol tidak valid (contoh: XAUUSDc).")

    common = _find_common_ini()
    if common is None:
        raise RuntimeError(
            "config/common.ini MT5 belum ditemukan. Tunggu container MT5 selesai "
            "instalasi/launch pertama, lalu coba login lagi."
        )

    try:
        raw = common.read_bytes()
    except OSError as e:
        raise RuntimeError(f"Tidak bisa membaca common.ini: {e}") from e
    text, encoding = _decode_ini(raw)
    updated = _update_ini(text, {
        "Common": {"Login": account, "Password": password, "Server": server},
        "StartUp": {
            "Expert": EXPERT_NAME,
            "Symbol": symbol or "XAUUSD",
            "Period": "M5",
        },
        "Experts": {
            "AllowLiveTrading": "1",
            "Enabled": "1",
            "WebRequest": "1",
        },
    })
    _atomic_write(common, _encode_ini(updated, encoding), 0o600)

    if symbol:
        _update_symbol_config(symbol)
    control = _restart_mt5()

    _ensure_secrets()
    session = {
        "connected": True,
        "broker": broker,
        "server": server,
        "login": account,
        "symbol": symbol or None,
        "connected_at": _now(),
        "common_ini": str(common),
        "control": control,
    }
    _atomic_write(SESSION_PATH, (json.dumps(session, indent=2) + "\n").encode("utf-8"))
    return {
        "ok": True,
        "connected": True,
        "broker": broker,
        "server": server,
        "login": _mask(account),
        "symbol": symbol or None,
        "connected_at": session["connected_at"],
        "control": control,
        "warning": "; ".join(control.get("warnings") or []) or None,
    }
