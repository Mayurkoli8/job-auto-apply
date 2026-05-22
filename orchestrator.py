"""
orchestrator.py — Daily job application pipeline.

Flow:
  1. Load resume profile
  2. Scrape new jobs
  3. For each job (up to DAILY_LIMIT):
     a. Try to find HR email → cold email outreach  (PRIMARY)
     b. If job has direct apply URL → form fill     (SECONDARY)
  4. Log everything
"""
from __future__ import annotations
import asyncio
import random
from datetime import datetime
from typing import List

from config import settings
from database import (
    mark_applied, get_stats, AsyncSessionLocal, DailyStats, Job, get_pending_jobs
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

console = Console()


async def process_job_email(job: dict, profile: dict) -> bool:
    """
    Try to cold-email an HR contact for this job.
    Returns True on success.
    """
    contact = await find_contact_for_job(
        company=job["company"],
        job_url=job.get("url", ""),
        job_title=job.get("title", ""),
    )

    if not contact or not contact.email:
        console.print(f"  [yellow]No email found for {job['company']}[/yellow]")
        return False

    # Generate personalized email
    email_content = await generate_cold_email(
        job=job,
        profile=profile,
        contact_name=contact.name,
        contact_title=contact.title,
    )

    subject = email_content["subject"]
    body = email_content["body"]

    # Send it
    success = await send_email(
        to_address=contact.email,
        subject=subject,
        body=body,
        job_id=job["id"],
        to_name=contact.name,
        attach_resume=True,
    )

    if success:
        await mark_applied(
            job_id=job["id"],
            method="cold_email",
            contact_email=contact.email,
            email_subject=subject,
            email_body=body,
        )

    return success


async def process_job_form(job: dict, profile: dict) -> bool:
    """
    Fill out the job application form on the job site.
    Returns True on success.
    """
    # Generate cover letter for form applications
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


# ── ATS / apply page detection ────────────────────────────────────────────────

APPLY_URL_PATTERNS = [
    "greenhouse.io", "lever.co", "workday.com", "ashbyhq.com",
    "bamboohr.com", "smartrecruiters.com", "jobvite.com",
    "icims.com", "taleo.net", "successfactors.com",
]


def has_direct_apply_url(job: dict) -> bool:
    url = job.get("url", "").lower()
    return any(p in url for p in APPLY_URL_PATTERNS)


# ── Main daily pipeline ───────────────────────────────────────────────────────

async def run_daily_pipeline(limit: int = None) -> dict:
    limit = limit or settings.DAILY_LIMIT
    today = datetime.utcnow().strftime("%Y-%m-%d")

    console.rule(f"[bold cyan]Job Auto-Apply — {today}[/bold cyan]")

    # 1. Load profile
    profile = await load_profile()
    if not profile:
        console.print("[red]No resume profile found. Parse your resume first.[/red]")
        return {}

    console.print(f"[green]Profile:[/green] {profile.get('name')} | "
                  f"{profile.get('total_experience_years', '?')} yrs | "
                  f"{len(profile.get('skills', []))} skills")

    # 2. Scrape jobs
    console.print("\n[bold]Scraping jobs...[/bold]")
    new_jobs = await scrape_all_jobs(profile)
    console.print(f"[cyan]{len(new_jobs)} new jobs found[/cyan]")

    # Also retry pending jobs that were scraped in earlier runs
    pending_jobs = await get_pending_jobs(limit)
    if pending_jobs:
        console.print(f"[cyan]{len(pending_jobs)} pending jobs available for retry[/cyan]")

    if not new_jobs and not pending_jobs:
        console.print("[yellow]No jobs available to apply to.[/yellow]")
        return {"applied": 0, "scraped": len(new_jobs)}

    # 3. Apply
    applied_email = 0
    applied_form = 0
    skipped = 0
    errors = 0

    # Prioritise by match score; avoid duplicate work for the same job
    seen_ids = {job["id"] for job in new_jobs}
    all_candidates = list(new_jobs)
    for job in pending_jobs:
        if job.id not in seen_ids:
            all_candidates.append({
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
            })
    all_candidates.sort(key=lambda j: j["match_score"], reverse=True)
    jobs_to_apply = all_candidates[:limit]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Applying...", total=len(jobs_to_apply))

        for job in jobs_to_apply:
            progress.update(
                task,
                description=f"[cyan]{job['company'][:30]}[/cyan] — {job['title'][:40]}"
            )

            # Rate limiting
            delay = random.uniform(
                settings.MIN_DELAY_SECONDS * 2,
                settings.MAX_DELAY_SECONDS * 3
            )

            try:
                # PRIMARY: cold email
                email_success = await process_job_email(job, profile)
                if email_success:
                    applied_email += 1
                    progress.advance(task)
                    await asyncio.sleep(delay)
                    continue

                # SECONDARY: form fill (only if it has a known ATS URL)
                if has_direct_apply_url(job):
                    form_success = await process_job_form(job, profile)
                    if form_success:
                        applied_form += 1
                        progress.advance(task)
                        await asyncio.sleep(delay)
                        continue

                skipped += 1

            except Exception as e:
                console.print(f"  [red]Error on {job['company']}: {e}[/red]")
                errors += 1

            progress.advance(task)
            await asyncio.sleep(delay)

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
            session.add(DailyStats(
                date=today,
                jobs_scraped=len(new_jobs),
                emails_sent=applied_email,
                forms_filled=applied_form,
                errors=errors,
            ))
        await session.commit()

    total_applied = applied_email + applied_form
    result = {
        "date": today,
        "scraped": len(new_jobs),
        "applied_email": applied_email,
        "applied_form": applied_form,
        "total_applied": total_applied,
        "skipped": skipped,
        "errors": errors,
    }

    # Summary table
    table = Table(title="Daily Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")
    table.add_row("Jobs scraped", str(len(new_jobs)))
    table.add_row("Cold emails sent", str(applied_email))
    table.add_row("Forms filled", str(applied_form))
    table.add_row("Total applied", str(total_applied))
    table.add_row("Skipped", str(skipped))
    table.add_row("Errors", str(errors))
    console.print(table)

    return result


async def run_email_only_pipeline(limit: int = None) -> dict:
    """Run only the cold email pipeline (faster, more reliable)."""
    limit = limit or settings.DAILY_LIMIT
    profile = await load_profile()
    if not profile:
        return {}
    new_jobs = await scrape_all_jobs(profile)
    applied = 0
    for job in new_jobs[:limit]:
        success = await process_job_email(job, profile)
        if success:
            applied += 1
        delay = random.uniform(60, 120)  # 1-2 min between emails
        await asyncio.sleep(delay)
    return {"applied": applied, "scraped": len(new_jobs)}
