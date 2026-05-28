"""
database.py — SQLite models via SQLAlchemy async.
DB path comes from config.DATABASE_PATH:
  • Default  : /tmp/jobs.db   (free on Render — survives sleep, resets on redeploy)
  • Override : data/jobs.db   if you mount a persistent disk
"""
from __future__ import annotations
from datetime import datetime
import re
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Boolean, JSON, Float, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession


def _urls():
    from config import settings
    path = settings.DATABASE_PATH
    return f"sqlite+aiosqlite:///{path}", f"sqlite:///{path}"


Base = declarative_base()

# Engines are created lazily so config is loaded first
_async_engine = None
_sync_engine  = None
_AsyncSession  = None


def _get_async_engine():
    global _async_engine
    if _async_engine is None:
        async_url, _ = _urls()
        _async_engine = create_async_engine(async_url, echo=False)
    return _async_engine


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _, sync_url = _urls()
        _sync_engine = create_engine(sync_url, echo=False)
    return _sync_engine


def AsyncSessionLocal():
    global _AsyncSession
    if _AsyncSession is None:
        _AsyncSession = sessionmaker(
            _get_async_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _AsyncSession()


# ── Models ───────────────────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"
    id           = Column(String, primary_key=True)
    title        = Column(String, nullable=False)
    company      = Column(String, nullable=False)
    location     = Column(String)
    url          = Column(String)
    description  = Column(Text)
    salary       = Column(String)
    source       = Column(String)
    posted_at    = Column(DateTime)
    scraped_at   = Column(DateTime, default=datetime.utcnow)
    applied      = Column(Boolean, default=False)
    apply_method = Column(String)
    applied_at   = Column(DateTime)
    status       = Column(String, default="pending")
    contact_email= Column(String)
    contact_name = Column(String)
    email_subject= Column(String)
    email_body   = Column(Text)
    cover_letter = Column(Text)
    notes        = Column(Text)
    match_score  = Column(Float, default=0.0)


class ResumeProfile(Base):
    __tablename__ = "resume_profile"
    id                    = Column(Integer, primary_key=True, autoincrement=True)
    raw_text              = Column(Text)
    name                  = Column(String)
    email                 = Column(String)
    phone                 = Column(String)
    location              = Column(String)
    summary               = Column(Text)
    skills                = Column(JSON)
    experience            = Column(JSON)
    education             = Column(JSON)
    certifications        = Column(JSON)
    languages             = Column(JSON)
    total_experience_years= Column(Float)
    parsed_at             = Column(DateTime, default=datetime.utcnow)


class EmailLog(Base):
    __tablename__ = "email_log"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    job_id     = Column(String)
    to_address = Column(String)
    to_name    = Column(String)
    subject    = Column(String)
    body       = Column(Text)
    sent_at    = Column(DateTime, default=datetime.utcnow)
    success    = Column(Boolean)
    error      = Column(String)


class DailyStats(Base):
    __tablename__ = "daily_stats"
    date         = Column(String, primary_key=True)
    jobs_scraped = Column(Integer, default=0)
    emails_sent  = Column(Integer, default=0)
    forms_filled = Column(Integer, default=0)
    errors       = Column(Integer, default=0)


# ── Helpers ──────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables (sync, called on startup)."""
    import os
    from config import settings
    db_path = settings.DATABASE_PATH
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    Base.metadata.create_all(_get_sync_engine())
    print(f"[DB] SQLite ready → {db_path}")


async def get_all_job_ids() -> set:
    from sqlalchemy import select
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(Job.id))
        return {row[0] for row in r.fetchall()}


def _normalize_job_text(value: str | None) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def job_identity_key(company: str | None, title: str | None) -> tuple[str, str] | None:
    company_key = _normalize_job_text(company)
    title_key = _normalize_job_text(title)
    if not company_key or not title_key:
        return None
    return company_key, title_key


async def get_all_job_keys() -> set[tuple[str, str]]:
    from sqlalchemy import select
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(Job.company, Job.title))
        return {
            key for company, title in r.fetchall()
            if (key := job_identity_key(company, title))
        }


async def upsert_job(job_data: dict) -> bool:
    from sqlalchemy import select
    async with AsyncSessionLocal() as s:
        if await s.get(Job, job_data["id"]):
            return False
        incoming_key = job_identity_key(job_data.get("company"), job_data.get("title"))
        if incoming_key:
            existing = await s.execute(select(Job.company, Job.title))
            for company, title in existing.fetchall():
                if job_identity_key(company, title) == incoming_key:
                    return False
        s.add(Job(**job_data))
        await s.commit()
        return True


async def get_pending_jobs(limit: int = 50, min_match_score: float | None = None) -> list[Job]:
    from sqlalchemy import select
    from config import settings
    threshold = settings.MIN_MATCH_SCORE if min_match_score is None else min_match_score
    async with AsyncSessionLocal() as s:
        query = (
            select(Job)
            .where(Job.applied == False)
            .where(Job.match_score >= threshold)
            .order_by(Job.match_score.desc())
            .limit(limit)
        )
        result = await s.execute(query)
        return result.scalars().all()


async def get_apply_skip_reason(job_data: dict, min_match_score: float | None = None) -> str:
    from sqlalchemy import select
    from config import settings
    threshold = settings.MIN_MATCH_SCORE if min_match_score is None else min_match_score
    job_id = job_data.get("id")
    incoming_key = job_identity_key(job_data.get("company"), job_data.get("title"))
    score = float(job_data.get("match_score") or 0.0)

    async with AsyncSessionLocal() as s:
        if job_id:
            existing = await s.get(Job, job_id)
            if existing:
                if existing.applied:
                    return "already applied to this job id"
                score = float(existing.match_score or score)

        if score < threshold:
            return f"match score {score:.3f} below threshold {threshold:.3f}"

        if incoming_key:
            result = await s.execute(
                select(Job.id, Job.company, Job.title)
                .where(Job.applied == True)
            )
            for existing_id, company, title in result.fetchall():
                if existing_id != job_id and job_identity_key(company, title) == incoming_key:
                    return "same company/title already applied"

    return ""


async def mark_applied(job_id: str, method: str, contact_email: str = None,
                       email_subject: str = None, email_body: str = None, status: str = "applied"):
    async with AsyncSessionLocal() as s:
        job = await s.get(Job, job_id)
        if job:
            job.applied       = True
            job.apply_method  = method
            job.applied_at    = datetime.utcnow()
            job.status        = status
            if contact_email:  job.contact_email  = contact_email
            if email_subject:  job.email_subject  = email_subject
            if email_body:     job.email_body     = email_body
            await s.commit()


async def update_job_status(job_id: str, status: str, notes: str = None):
    async with AsyncSessionLocal() as s:
        job = await s.get(Job, job_id)
        if job:
            job.status = status
            if notes:
                job.notes = notes
            await s.commit()


async def get_stats() -> dict:
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as s:
        total   = (await s.execute(select(func.count(Job.id)))).scalar()
        applied = (await s.execute(
            select(func.count(Job.id)).where(Job.applied == True))).scalar()
        rows    = (await s.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status))).fetchall()
        return {
            "total_scraped": total,
            "total_applied": applied,
            "by_status": {st: cnt for st, cnt in rows},
        }
