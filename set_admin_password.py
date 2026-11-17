#!/usr/bin/env python3
"""Ganti kata sandi admin dashboard XAUUSD Pattern Lab.

Jalankan dari folder proyek:
    python3 set_admin_password.py

Kata sandi tidak ditulis ke layar, tidak masuk riwayat shell, dan hanya
disimpan sebagai hash PBKDF2-SHA256 di config.json.
"""
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
MIN_LENGTH = 10
ITERATIONS = 260_000


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def main():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Gagal membaca config.json: {e}", file=sys.stderr)
        return 1

    auth = cfg.setdefault("auth", {})
    username = auth.get("username") or "admin"
    print(f"Admin dashboard: {username}")
    print(f"Kata sandi minimal {MIN_LENGTH} karakter. Ketik Ctrl+C untuk batal.")

    try:
        password = getpass.getpass("Kata sandi baru : ")
        if len(password) < MIN_LENGTH:
            print(f"Kata sandi terlalu pendek (minimal {MIN_LENGTH} karakter).", file=sys.stderr)
            return 1
        confirm = getpass.getpass("Ulangi kata sandi: ")
    except (KeyboardInterrupt, EOFError):
        print("\nDibatalkan.", file=sys.stderr)
        return 1

    if password != confirm:
        print("Kata sandi tidak sama. Tidak ada yang diubah.", file=sys.stderr)
        return 1

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    auth["enabled"] = True
    auth["username"] = username
    auth["password_hash"] = f"pbkdf2_sha256${ITERATIONS}${b64(salt)}${b64(digest)}"
    auth.setdefault("session_hours", 12)

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        print(f"Gagal menulis config.json: {e}", file=sys.stderr)
        return 1

    print("Kata sandi admin diperbarui. Service tidak perlu di-restart.")
    print("Masuk berikutnya memakai kata sandi baru; sesi lama tetap berlaku sampai kedaluwarsa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
