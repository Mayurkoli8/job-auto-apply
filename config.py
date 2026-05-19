"""
config.py — Centralised settings loaded from .env
"""
from __future__ import annotations
import json
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # ── AI (Google Gemini — FREE) ────────────────────
    # Get key at: aistudio.google.com/app/apikey
    # Free limits: gemini-1.5-flash → 1500 req/day, 1M tokens/min
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"   # or gemini-1.5-pro / gemini-2.0-flash

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
    RESUME_PATH: str = "uploads/resume.pdf"

    # ── Job search ──────────────────────────────────
    JOB_TITLES: List[str] = ["Software Engineer"]
    JOB_KEYWORDS: List[str] = []
    JOB_LOCATION: str = "Remote"
    EXPERIENCE_LEVEL: str = "mid-level"
    MIN_SALARY: int = 0
    EXCLUDED_COMPANIES: List[str] = []

    # ── Automation ──────────────────────────────────
    DAILY_LIMIT: int = 50
    RUN_HOUR: int = 8
    RUN_MINUTE: int = 0
    TIMEZONE: str = "America/New_York"
    MIN_DELAY_SECONDS: int = 3
    MAX_DELAY_SECONDS: int = 12

    # ── Optional APIs ───────────────────────────────
    HUNTER_API_KEY: Optional[str] = None
    ADZUNA_APP_ID: Optional[str] = None
    ADZUNA_APP_KEY: Optional[str] = None
    THE_MUSE_API_KEY: Optional[str] = None
    TWOCAPTCHA_API_KEY: Optional[str] = None

    @field_validator("JOB_TITLES", "JOB_KEYWORDS", "EXCLUDED_COMPANIES", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [x.strip() for x in v.split(",") if x.strip()]
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
