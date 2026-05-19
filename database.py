"""
database.py — SQLite models via SQLAlchemy (async)
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Boolean, JSON, Float, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

DATABASE_URL = "sqlite+aiosqlite:///data/jobs.db"
SYNC_DATABASE_URL = "sqlite:///data/jobs.db"

engine = create_async_engine(DATABASE_URL, echo=False)
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)           # source:job_id
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String)
    url = Column(String)
    description = Column(Text)
    salary = Column(String)
    source = Column(String)                          # remoteok / remotive / indeed / etc.
    posted_at = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    applied = Column(Boolean, default=False)
    apply_method = Column(String)                    # email / form / easy_apply
    applied_at = Column(DateTime)
    status = Column(String, default="pending")       # pending / applied / replied / rejected / interview
    contact_email = Column(String)
    contact_name = Column(String)
    email_subject = Column(String)
    email_body = Column(Text)
    cover_letter = Column(Text)
    notes = Column(Text)
    match_score = Column(Float, default=0.0)


class ResumeProfile(Base):
    __tablename__ = "resume_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_text = Column(Text)
    name = Column(String)
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    summary = Column(Text)
    skills = Column(JSON)          # list of strings
    experience = Column(JSON)      # list of {company, title, duration, bullets}
    education = Column(JSON)       # list of {school, degree, year}
    certifications = Column(JSON)
    languages = Column(JSON)
    total_experience_years = Column(Float)
    parsed_at = Column(DateTime, default=datetime.utcnow)


class EmailLog(Base):
    __tablename__ = "email_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String)
    to_address = Column(String)
    to_name = Column(String)
    subject = Column(String)
    body = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean)
    error = Column(String)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    date = Column(String, primary_key=True)   # YYYY-MM-DD
    jobs_scraped = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    forms_filled = Column(Integer, default=0)
    errors = Column(Integer, default=0)


# ── helpers ─────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables synchronously (called on startup)."""
    import os; os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(sync_engine)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def get_applied_job_ids() -> set:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job.id).where(Job.applied == True))
        return {row[0] for row in result.fetchall()}


async def get_all_job_ids() -> set:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job.id))
        return {row[0] for row in result.fetchall()}


async def upsert_job(job_data: dict) -> bool:
    """Insert job if not already tracked. Returns True if new."""
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        existing = await session.get(Job, job_data["id"])
        if existing:
            return False
        session.add(Job(**job_data))
        await session.commit()
        return True


async def mark_applied(job_id: str, method: str, contact_email: str = None,
                        email_subject: str = None, email_body: str = None):
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job:
            job.applied = True
            job.apply_method = method
            job.applied_at = datetime.utcnow()
            job.status = "applied"
            if contact_email:  job.contact_email = contact_email
            if email_subject:  job.email_subject = email_subject
            if email_body:     job.email_body = email_body
            await session.commit()


async def update_job_status(job_id: str, status: str, notes: str = None):
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job:
            job.status = status
            if notes: job.notes = notes
            await session.commit()


async def get_stats() -> dict:
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(Job.id)))).scalar()
        applied = (await session.execute(
            select(func.count(Job.id)).where(Job.applied == True))).scalar()
        by_status = {}
        rows = (await session.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status))).fetchall()
        for status, count in rows:
            by_status[status] = count
        return {"total_scraped": total, "total_applied": applied, "by_status": by_status}
