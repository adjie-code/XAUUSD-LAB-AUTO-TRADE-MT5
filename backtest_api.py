#!/usr/bin/env python3
"""
API job manager untuk Strategy Tester di dashboard.

- Menjalankan `backtest/backtest_runner.py` sebagai subprocess terpisah.
- Satu job pada satu waktu (lock global).
- Snapshot DB, batas CPU, dan pembersihan tetap ditangani runner.
- Tidak pernah mengirim order, tidak menyentuh MT5/EA/PULLBACK.
- Job disimpan in-memory; riwayat juga dibaca dari folder
  `backtest/results/run_*` supaya tetap terlihat setelah restart server.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import ea_generator

ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "backtest" / "backtest_runner.py"
RESULTS = ROOT / "backtest" / "results"
JOB_TIMEOUT_SEC = 3600          # 1 jam hard limit per job
ALLOWED_FILES = {
    "summary.json": "application/json; charset=utf-8",
    "trades.csv": "text/csv; charset=utf-8",
    "equity.csv": "text/csv; charset=utf-8",
    "report.md": "text/markdown; charset=utf-8",
    "run.log": "text/plain; charset=utf-8",
}
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_current: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _validate_params(params: dict) -> tuple[dict | None, str]:
    """Return (clean_params, error_message)."""
    try:
        strategy = str(params.get("strategy", "ema_cross"))
        if strategy != "ema_cross":
            return None, "strategi belum didukung: hanya ema_cross"

        def date_val(key: str, default: str) -> str:
            raw = str(params.get(key) or default)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError(key)
            datetime.strptime(raw, "%Y-%m-%d")
            return raw

        start = date_val("start", "2006-01-01")
        end = date_val("end", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if start < "2006-01-01":
            return None, "start minimal 2006-01-01 (dataset Dukascopy)"
        if end <= start:
            return None, "end harus setelah start"

        def int_val(key: str, lo: int, hi: int, default: int) -> int:
            v = int(params.get(key, default))
            if not lo <= v <= hi:
                raise ValueError(key)
            return v

        def float_val(key: str, lo: float, hi: float, default: float) -> float:
            v = float(params.get(key, default))
            if not lo <= v <= hi:
                raise ValueError(key)
            return v

        fast = int_val("fast", 2, 200, 20)
        slow = int_val("slow", 3, 400, 50)
        if fast >= slow:
            return None, "fast harus lebih kecil dari slow"
        clean = {
            "strategy": strategy,
            "start": start,
            "end": end,
            "fast": fast,
            "slow": slow,
            "atr": int_val("atr", 2, 200, 14),
            "sl_atr": float_val("sl_atr", 0.2, 10.0, 1.5),
            "tp_atr": float_val("tp_atr", 0.2, 20.0, 2.5),
            "spread_points": float_val("spread_points", 0.0, 500.0, 30.0),
            "slippage_points": float_val("slippage_points", 0.0, 200.0, 0.0),
            "commission_per_lot": float_val("commission_per_lot", 0.0, 100.0, 0.0),
            "lot": float_val("lot", 0.01, 10.0, 0.01),
        }
        return clean, ""
    except (TypeError, ValueError) as exc:
        return None, f"parameter tidak valid: {exc}"


def _build_args(job_id: str, p: dict) -> list[str]:
    return [
        sys.executable, str(RUNNER),
        "--run-id", job_id,
        "--strategy", p["strategy"],
        "--start", p["start"],
        "--end", p["end"],
        "--fast", str(p["fast"]),
        "--slow", str(p["slow"]),
        "--atr", str(p["atr"]),
        "--sl-atr", str(p["sl_atr"]),
        "--tp-atr", str(p["tp_atr"]),
        "--spread-points", str(p["spread_points"]),
        "--slippage-points", str(p["slippage_points"]),
        "--commission-per-lot", str(p["commission_per_lot"]),
        "--lot", str(p["lot"]),
    ]


def _worker(job: dict) -> None:
    global _current
    out_dir = RESULTS / f"run_{job['id']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    args = _build_args(job["id"], job["params"])
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                args, cwd=str(ROOT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
            job["proc"] = proc
            for line in proc.stdout:
                log.write(line)
                job["log_tail"] = (job["log_tail"] + [line.rstrip()])[-40:]
            try:
                proc.wait(timeout=JOB_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
                job["status"] = "failed"
                job["message"] = f"timeout > {JOB_TIMEOUT_SEC} detik"
                return
        rc = proc.returncode
        job["returncode"] = rc
        job["runtime_sec"] = round(time.monotonic() - started, 1)
        summary = out_dir / "summary.json"
        if job.get("status") == "canceled":
            job["message"] = "dibatalkan oleh user"
        elif rc == 0 and summary.is_file():
            job["status"] = "done"
            job["message"] = "selesai"
            try:
                job["summary"] = json.loads(summary.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                job["summary"] = None
        else:
            job["status"] = "failed"
            job["message"] = (job["log_tail"][-1] if job["log_tail"]
                              else f"runner exit {rc}")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "failed"
        job["message"] = f"{type(exc).__name__}: {exc}"
    finally:
        job["finished_at"] = _now()
        job["proc"] = None
        with _lock:
            if _current == job["id"]:
                _current = None


def start_job(params: dict) -> tuple[dict | None, str]:
    global _current
    clean, err = _validate_params(params)
    if err:
        return None, err
    with _lock:
        if _current is not None:
            active = _jobs.get(_current)
            if active and active["status"] == "running":
                return None, "sudah ada job backtest berjalan"
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + \
            f"{int(time.monotonic() * 1000) % 1000:03d}"
        job = {
            "id": job_id,
            "params": clean,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "message": "menjalankan backtest",
            "log_tail": [],
            "summary": None,
            "proc": None,
            "returncode": None,
            "runtime_sec": None,
            "out_dir": str(RESULTS / f"run_{job_id}"),
        }
        _jobs[job_id] = job
        _current = job_id
    thread = threading.Thread(target=_worker, args=(job,), daemon=True)
    thread.start()
    return job, ""


def cancel_job(job_id: str) -> tuple[bool, str]:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return False, "job tidak ditemukan"
    if job["status"] != "running":
        return False, "job tidak sedang berjalan"
    proc = job.get("proc")
    if proc is None:
        return False, "proses tidak tersedia"
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    job["status"] = "canceled"
    job["message"] = "dibatalkan oleh user"
    job["finished_at"] = _now()
    return True, "job dibatalkan"


def job_status(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return None
    return {
        "id": job["id"],
        "status": job["status"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "message": job["message"],
        "runtime_sec": job["runtime_sec"],
        "params": job["params"],
        "out_dir": job["out_dir"],
        "log_tail": job["log_tail"][-15:],
    }


def list_jobs(limit: int = 20) -> list[dict]:
    """Job in-memory + riwayat folder run_* yang punya summary.json."""
    out: dict[str, dict] = {}
    if RESULTS.is_dir():
        for folder in sorted(RESULTS.glob("run_*"), reverse=True):
            summary = folder / "summary.json"
            if not summary.is_file():
                continue
            job_id = folder.name[len("run_"):]
            try:
                data = json.loads(summary.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out[job_id] = {
                "id": job_id,
                "status": "done",
                "started_at": None,
                "finished_at": None,
                "message": "riwayat",
                "runtime_sec": data.get("runtime_sec"),
                "params": data.get("params"),
                "out_dir": str(folder),
                "metrics": {
                    "trades": data.get("trades"),
                    "net_pnl": data.get("net_pnl"),
                    "profit_factor": data.get("profit_factor"),
                    "win_rate_pct": data.get("win_rate_pct"),
                    "max_drawdown_pct": data.get("max_drawdown_pct"),
                    "years": data.get("years"),
                    "bars": (data.get("data") or {}).get("bars"),
                },
            }
    with _lock:
        for job_id, job in _jobs.items():
            metrics = None
            if job.get("summary"):
                s = job["summary"]
                metrics = {
                    "trades": s.get("trades"),
                    "net_pnl": s.get("net_pnl"),
                    "profit_factor": s.get("profit_factor"),
                    "win_rate_pct": s.get("win_rate_pct"),
                    "max_drawdown_pct": s.get("max_drawdown_pct"),
                    "years": s.get("years"),
                    "bars": (s.get("data") or {}).get("bars"),
                }
            out[job_id] = {
                "id": job_id,
                "status": job["status"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
                "message": job["message"],
                "runtime_sec": job["runtime_sec"],
                "params": job["params"],
                "out_dir": job["out_dir"],
                "metrics": metrics,
            }
    items = sorted(out.values(), key=lambda x: x["id"], reverse=True)
    return items[:limit]


def job_result(job_id: str) -> dict | None:
    if not RUN_ID_RE.match(job_id):
        return None
    with _lock:
        job = _jobs.get(job_id)
    if job and job.get("summary"):
        return job["summary"]
    summary = RESULTS / f"run_{job_id}" / "summary.json"
    if summary.is_file():
        try:
            return json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def job_file(job_id: str, name: str) -> tuple[bytes | None, str]:
    if not RUN_ID_RE.match(job_id):
        return None, "id job tidak valid"
    if name not in ALLOWED_FILES:
        return None, "file tidak diizinkan"
    path = (RESULTS / f"run_{job_id}" / name).resolve()
    base = RESULTS.resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None, "path tidak valid"
    if not path.is_file():
        return None, "file belum ada"
    return path.read_bytes(), ALLOWED_FILES[name]


def job_verdict(job_id: str) -> dict | None:
    summary = job_result(job_id)
    if not summary:
        return None
    return ea_generator.evaluate_summary(summary)


def generate_ea(job_id: str, name: str | None = None,
                magic: int | None = None) -> tuple[dict | None, str]:
    return ea_generator.generate_from_job(job_id, name, magic)


def list_generated() -> list[dict]:
    return ea_generator.list_generated()


def read_ea(filename: str) -> tuple[bytes | None, str]:
    return ea_generator.read_ea(filename)
