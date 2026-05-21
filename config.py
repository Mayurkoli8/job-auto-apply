"""
config.py — Centralised settings loaded from .env / Render environment variables
"""
from __future__ import annotations
import json
import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # ── AI (Google Gemini — 100% FREE) ──────────────
    # Get key in 30s: aistudio.google.com/app/apikey
    # Free: gemini-1.5-flash → 1,500 req/day | 1M tokens/min
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # ── Email (Gmail SMTP) ───────────────────────────
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # ── User profile ────────────────────────────────
    USER_FULL_NAME: str = "Your Name"
    USER_EMAIL: str = ""
    USER_PHONE: str = ""
    USER_LOCATION: str = "Remote"
    USER_LINKEDIN: Optional[str] = None
    USER_GITHUB: Optional[str] = None
    USER_PORTFOLIO: Optional[str] = None

    # ── Resume ──────────────────────────────────────
    # Priority order: RESUME_URL → RESUME_BASE64 → RESUME_PATH (local file)
    # On Render free tier use RESUME_URL — your PDF is already hosted at:
    #   https://mayurkoli.mentesa.live/Mayur%20Koli%20Resume%202026%20AI%20Engineer.pdf
    RESUME_URL: Optional[str] = "https://mayurkoli.mentesa.live/Mayur%20Koli%20Resume%202026%20AI%20Engineer.pdf"
    RESUME_BASE64: Optional[str] = None
    RESUME_PATH: str = "/tmp/resume.pdf"   # downloaded here on startup

    # ── Database ─────────────────────────────────────
    # /tmp is free, survives Render sleep/wake, resets only on redeploy
    # Set DATABASE_PATH=data/jobs.db if you have a persistent disk
    DATABASE_PATH: str = "/tmp/jobs.db"

    # ── Job search ──────────────────────────────────
    JOB_TITLES: List[str] = ["AI Engineer", "ML Engineer", "Software Engineer"]
    JOB_KEYWORDS: List[str] = ["Python", "Machine Learning", "LLM", "FastAPI"]
    JOB_LOCATION: str = "Remote"
    EXPERIENCE_LEVEL: str = "mid-level"
    MIN_SALARY: int = 0
    EXCLUDED_COMPANIES: List[str] = []

    # ── Automation ──────────────────────────────────
    DAILY_LIMIT: int = 50
    RUN_HOUR: int = 8
    RUN_MINUTE: int = 0
    TIMEZONE: str = "Asia/Kolkata"
    MIN_DELAY_SECONDS: int = 3
    MAX_DELAY_SECONDS: int = 12

    # ── Optional free API keys ───────────────────────
    HUNTER_API_KEY: Optional[str] = None
    ADZUNA_APP_ID: Optional[str] = None
    ADZUNA_APP_KEY: Optional[str] = None
    THE_MUSE_API_KEY: Optional[str] = None
    TWOCAPTCHA_API_KEY: Optional[str] = None
    MIN_MATCH_SCORE: float = 0.1

    @field_validator("JOB_TITLES", "JOB_KEYWORDS", "EXCLUDED_COMPANIES", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RESUME_URL", "JOB_LOCATION", "USER_LINKEDIN", "USER_GITHUB", "USER_PORTFOLIO", mode="before")
    @classmethod
    def strip_quotes(cls, v):
        if isinstance(v, str):
            return v.strip().strip('"').strip("'")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
