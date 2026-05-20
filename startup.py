"""
startup.py — Runs once at boot. Handles resume download, DB init, preflight checks.

Resume priority:
  1. RESUME_URL  — direct URL to a hosted PDF (Mayur's resume already set as default)
  2. RESUME_BASE64 — base64-encoded PDF pasted as env var
  3. RESUME_PATH — local file (works locally / Docker)
"""
from __future__ import annotations
import base64
import os
from pathlib import Path


def hydrate_resume() -> str:
    from config import settings

    dest = Path(settings.RESUME_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Direct URL (default — Mayur's hosted resume) ──────────────────
    if settings.RESUME_URL:
        try:
            import httpx
            print(f"[Startup] Downloading resume from URL...")
            with httpx.Client(follow_redirects=True, timeout=30) as client:
                resp = client.get(settings.RESUME_URL)
                resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"[Startup] ✓ Resume downloaded → {dest} ({len(resp.content):,} bytes)")
            return str(dest)
        except Exception as e:
            print(f"[Startup] ⚠ URL download failed: {e}")

    # ── 2. Base64 env var ─────────────────────────────────────────────────
    if settings.RESUME_BASE64:
        try:
            data = base64.b64decode(settings.RESUME_BASE64)
            dest.write_bytes(data)
            print(f"[Startup] ✓ Resume decoded from RESUME_BASE64 → {dest}")
            return str(dest)
        except Exception as e:
            print(f"[Startup] ⚠ RESUME_BASE64 decode failed: {e}")

    # ── 3. Local file ─────────────────────────────────────────────────────
    if dest.exists():
        print(f"[Startup] ✓ Resume found at {dest}")
        return str(dest)

    print("[Startup] ⚠ No resume available — upload via /api/parse-resume")
    return str(dest)


def preflight_check() -> list[str]:
    from config import settings
    missing = []
    if not settings.GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY  →  aistudio.google.com/app/apikey  (free)")
    if not settings.GMAIL_ADDRESS:
        missing.append("GMAIL_ADDRESS")
    if not settings.GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD  →  myaccount.google.com/apppasswords")
    if not settings.USER_EMAIL:
        missing.append("USER_EMAIL")
    if not settings.JOB_TITLES:
        missing.append("JOB_TITLES  e.g.  [\"AI Engineer\", \"ML Engineer\"]")
    return missing


def run_all():
    # Create dirs
    for d in ["uploads", "logs"]:
        Path(d).mkdir(exist_ok=True)

    # Resume
    hydrate_resume()

    # DB
    from database import init_db
    init_db()

    # Preflight
    warnings = preflight_check()
    if warnings:
        print("\n[Startup] ⚠  Missing config — set these in Render → Environment:")
        for w in warnings:
            print(f"  •  {w}")
        print()
    else:
        print("[Startup] ✅ All config present — ready to apply to jobs\n")
