"""
orchestrator.py — Daily job application pipeline.
"""
from __future__ import annotations
import asyncio
import random
import logging
from datetime import datetime
from typing import List

from config import settings
from database import (
    mark_applied, get_stats, AsyncSessionLocal, DailyStats, Job, get_pending_jobs,
    get_apply_skip_reason,
)
from resume_parser import load_profile, parse_and_save_resume
from job_scraper import scrape_all_jobs
from email_finder import find_contact_for_job
from email_generator import generate_cold_email, generate_cover_letter
from email_sender import send_email
from form_filler import fill_application_form
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

logger = logging.getLogger("job-bot")
console = Console()
_PIPELINE_LOCK = asyncio.Lock()


async def process_job_email(job: dict, profile: dict) -> bool:
    """Try to cold-email an HR contact for this job."""
    contact = await find_contact_for_job(
        company=job["company"],
        job_url=job.get("url", ""),
        job_title=job.get("title", ""),
    )

    if not contact or not contact.email:
        logger.warning(f"No email found for {job['company']}")
        return False

    email_content = await generate_cold_email(
        job=job,
        profile=profile,
        contact_name=contact.name,
        contact_title=contact.title,
    )

    success = await send_email(
        to_address=contact.email,
        subject=email_content["subject"],
        body=email_content["body"],
        job_id=job["id"],
        to_name=contact.name,
        attach_resume=True,
    )

    if success:
        await mark_applied(
            job_id=job["id"],
            method="cold_email",
            contact_email=contact.email,
            email_subject=email_content["subject"],
            email_body=email_content["body"],
        )
    return success


async def process_job_form(job: dict, profile: dict) -> bool:
    """Fill out the job application form."""
    cover_letter = await generate_cover_letter(job=job, profile=profile)
    success = await fill_application_form(
        job=job,
        profile=profile,
        cover_letter=cover_letter,
        headless=True,
    )
    if success:
        await mark_applied(job_id=job["id"], method="form_fill")
    return success


APPLY_URL_PATTERNS = [
    "greenhouse.io", "lever.co", "workday.com", "ashbyhq.com",
    "bamboohr.com", "smartrecruiters.com", "jobvite.com",
    "icims.com", "taleo.net", "successfactors.com",
]


def has_direct_apply_url(job: dict) -> bool:
    url = job.get("url", "").lower()
    return any(p in url for p in APPLY_URL_PATTERNS)


def _job_row_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "description": job.description,
        "salary": job.salary,
        "source": job.source,
        "posted_at": job.posted_at,
        "match_score": job.match_score or 0.0,
    }


async def _apply_skip_reason(job: dict) -> str:
    return await get_apply_skip_reason(job, settings.MIN_MATCH_SCORE)


async def run_daily_pipeline(limit: int = None) -> dict:
    if _PIPELINE_LOCK.locked():
        logger.warning("Pipeline is already running. Skipping trigger.")
        return {"message": "already running"}
    async with _PIPELINE_LOCK:
        return await _run_daily_pipeline(limit)


async def _run_daily_pipeline(limit: int = None) -> dict:
    limit = limit or settings.DAILY_LIMIT
    today = datetime.utcnow().strftime("%Y-%m-%d")
    logger.info(f"Starting daily pipeline run (limit={limit})")
    
    try:
        # 1. Load profile
        profile = await load_profile()
        if not profile:
            logger.error("No resume profile found. Please upload a resume first.")
            return {"error": "no_profile"}
        logger.info(f"Loaded profile: {profile.get('name')}")

        # 2. Scrape jobs
        logger.info("Scraping for new jobs...")
        new_jobs = await scrape_all_jobs(profile)
        pending_jobs = await get_pending_jobs(limit)
        logger.info(f"Discovery complete. New: {len(new_jobs)} | Pending Retry: {len(pending_jobs)}")

        # 3. Apply
        applied_email = 0
        applied_form = 0
        skipped = 0
        errors = 0

        seen_ids = {job["id"] for job in new_jobs}
        all_candidates = list(new_jobs)
        for job in pending_jobs:
            if job.id not in seen_ids:
                all_candidates.append(_job_row_to_dict(job))
        
        all_candidates.sort(key=lambda j: j["match_score"], reverse=True)
        jobs_to_apply = all_candidates[:limit]
        
        if not jobs_to_apply:
            logger.info("No relevant jobs found to apply to.")
            return {"applied": 0}

        logger.info(f"Beginning application process for {len(jobs_to_apply)} jobs.")

        for i, job in enumerate(jobs_to_apply, start=1):
            logger.info(f"Processing #{i}: {job['company']} - {job['title']} (Score: {job['match_score']:.2f})")
            
            try:
                skip_reason = await _apply_skip_reason(job)
                if skip_reason:
                    logger.info(f"Skipping {job['company']}: {skip_reason}")
                    skipped += 1
                    continue

                # PRIMARY: cold email
                if await process_job_email(job, profile):
                    logger.info(f"SUCCESS: Email sent to {job['company']}")
                    applied_email += 1
                    await asyncio.sleep(random.uniform(settings.MIN_DELAY_SECONDS, settings.MAX_DELAY_SECONDS))
                    continue

                # SECONDARY: form fill
                if has_direct_apply_url(job):
                    if await process_job_form(job, profile):
                        logger.info(f"SUCCESS: Form filled for {job['company']}")
                        applied_form += 1
                        await asyncio.sleep(random.uniform(settings.MIN_DELAY_SECONDS, settings.MAX_DELAY_SECONDS))
                        continue

                logger.warning(f"SKIPPED: No outreach method found for {job['company']}")
                await mark_applied(job['id'], 'skipped', status='skipped')
                skipped += 1

            except Exception as e:
                logger.error(f"ERROR: Failed {job['company']}: {str(e)}")
                errors += 1
                await mark_applied(job['id'], 'failed', status='failed')

        # 4. Update daily stats
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            existing = await session.get(DailyStats, today)
            if existing:
                existing.emails_sent += applied_email
                existing.forms_filled += applied_form
                existing.jobs_scraped += len(new_jobs)
                existing.errors += errors
            else:
                session.add(DailyStats(date=today, jobs_scraped=len(new_jobs), emails_sent=applied_email, forms_filled=applied_form, errors=errors))
            await session.commit()

        logger.info(f"Pipeline finished. Total Applied: {applied_email + applied_form}")
        return {"applied": applied_email + applied_form}

    except Exception as e:
        logger.error(f"FATAL: Pipeline crash: {str(e)}")
        return {"error": str(e)}

async def run_email_only_pipeline(limit: int = None) -> dict:
    if _PIPELINE_LOCK.locked(): return {"message": "already running"}
    async with _PIPELINE_LOCK:
        return await _run_email_only_pipeline(limit)

async def _run_email_only_pipeline(limit: int = None) -> dict:
    limit = limit or settings.DAILY_LIMIT
    profile = await load_profile()
    if not profile: return {"error": "no_profile"}
    logger.info("Starting Email-Only Run...")
    new_jobs = await scrape_all_jobs(profile)
    pending_jobs = await get_pending_jobs(limit)
    all_jobs = list(new_jobs)
    seen_ids = {job['id'] for job in new_jobs}
    for job in pending_jobs:
        if job.id not in seen_ids: all_jobs.append(_job_row_to_dict(job))
    all_jobs.sort(key=lambda j: j['match_score'], reverse=True)
    
    applied = 0
    for job in all_jobs[:limit]:
        if await _apply_skip_reason(job): continue
        try:
            if await process_job_email(job, profile):
                applied += 1
                logger.info(f"Email sent: {job['company']}")
            else:
                await mark_applied(job['id'], 'skipped', status='skipped')
        except Exception as e:
            logger.error(f"Email failed for {job['company']}: {e}")
            await mark_applied(job['id'], 'failed', status='failed')
        await asyncio.sleep(random.uniform(30, 60))
    return {"applied": applied}
