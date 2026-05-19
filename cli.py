"""
cli.py — Command-line interface for the job auto-apply platform.

Usage:
  python cli.py parse-resume
  python cli.py run [--limit 20] [--email-only]
  python cli.py stats
  python cli.py jobs [--status applied] [--limit 50]
  python cli.py test-email
  python cli.py follow-up [--days 7]
  python cli.py export [--format csv]
"""
from __future__ import annotations
import asyncio
import csv
import sys
from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

app = typer.Typer(help="Job Auto-Apply Platform CLI")
console = Console()


@app.command()
def parse_resume(path: Optional[str] = typer.Option(None, help="Path to resume file")):
    """Parse your resume and extract structured profile."""
    from database import init_db
    from resume_parser import parse_and_save_resume
    init_db()
    profile = asyncio.run(parse_and_save_resume(path))
    console.print(Panel.fit(
        f"[green]✓[/green] Parsed successfully\n"
        f"Name: [bold]{profile.get('name')}[/bold]\n"
        f"Skills: {len(profile.get('skills', []))} detected\n"
        f"Experience: {profile.get('total_experience_years', '?')} years\n"
        f"Top skills: {', '.join(profile.get('skills', [])[:6])}",
        title="Resume Parsed",
        border_style="green"
    ))


@app.command()
def run(
    limit: int = typer.Option(None, help="Max applications to send"),
    email_only: bool = typer.Option(False, "--email-only", help="Cold email only (skip form fill)"),
):
    """Run the full application pipeline."""
    from database import init_db
    from orchestrator import run_daily_pipeline, run_email_only_pipeline
    init_db()
    if email_only:
        result = asyncio.run(run_email_only_pipeline(limit))
    else:
        result = asyncio.run(run_daily_pipeline(limit))
    console.print(f"\n[bold green]Done![/bold green] Applied to {result.get('total_applied', 0)} jobs.")


@app.command()
def stats():
    """Show application statistics."""
    from database import init_db, get_stats
    init_db()
    data = asyncio.run(get_stats())

    table = Table(title="Application Statistics", box=box.ROUNDED, border_style="cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold white", justify="right")

    table.add_row("Total jobs scraped", str(data.get("total_scraped", 0)))
    table.add_row("Total applied", str(data.get("total_applied", 0)))
    table.add_section()

    for status, count in (data.get("by_status") or {}).items():
        emoji = {
            "applied": "📤", "replied": "💬", "interview": "🎯",
            "rejected": "❌", "pending": "⏳"
        }.get(status, "•")
        table.add_row(f"{emoji} {status.capitalize()}", str(count))

    console.print(table)


@app.command()
def jobs(
    status: Optional[str] = typer.Option(None, help="Filter by status"),
    limit: int = typer.Option(20, help="Number of jobs to show"),
    applied_only: bool = typer.Option(False, "--applied", help="Show applied only"),
):
    """List tracked jobs."""
    from database import init_db, AsyncSessionLocal, Job
    from sqlalchemy import select
    init_db()

    async def _fetch():
        async with AsyncSessionLocal() as session:
            q = select(Job)
            if status:
                q = q.where(Job.status == status)
            if applied_only:
                q = q.where(Job.applied == True)
            q = q.order_by(Job.scraped_at.desc()).limit(limit)
            result = await session.execute(q)
            return result.scalars().all()

    rows = asyncio.run(_fetch())

    table = Table(title=f"Jobs (showing {len(rows)})", box=box.SIMPLE, border_style="dim")
    table.add_column("Title", style="white", max_width=35)
    table.add_column("Company", style="cyan", max_width=20)
    table.add_column("Source", style="dim", max_width=12)
    table.add_column("Method", style="dim", max_width=12)
    table.add_column("Status", max_width=10)
    table.add_column("Applied", style="dim", max_width=12)

    STATUS_COLORS = {
        "applied": "blue", "replied": "green", "interview": "magenta",
        "rejected": "red", "pending": "dim"
    }

    for j in rows:
        color = STATUS_COLORS.get(j.status or "pending", "dim")
        applied_at = j.applied_at.strftime("%m/%d %H:%M") if j.applied_at else "-"
        table.add_row(
            j.title[:35], j.company[:20],
            j.source or "-", j.apply_method or "-",
            f"[{color}]{j.status or 'pending'}[/{color}]",
            applied_at
        )

    console.print(table)


@app.command()
def test_email():
    """Send a test email to verify Gmail configuration."""
    from database import init_db
    from email_sender import test_email_config
    init_db()
    success = asyncio.run(test_email_config())
    if success:
        console.print("[bold green]✓ Test email sent! Check your inbox.[/bold green]")
    else:
        console.print("[bold red]✗ Email failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env[/bold red]")


@app.command()
def follow_up(
    days: int = typer.Option(7, help="Follow up jobs applied N days ago"),
    limit: int = typer.Option(10, help="Max follow-ups to send"),
):
    """Send follow-up emails for applications with no reply."""
    from database import init_db, AsyncSessionLocal, Job
    from sqlalchemy import select
    from resume_parser import load_profile
    from email_generator import generate_follow_up_email
    from email_sender import send_email
    from database import update_job_status
    init_db()

    async def _run():
        profile = await load_profile()
        if not profile:
            console.print("[red]No profile found. Run parse-resume first.[/red]")
            return

        cutoff = datetime.utcnow() - timedelta(days=days)
        async with AsyncSessionLocal() as session:
            q = (
                select(Job)
                .where(Job.applied == True)
                .where(Job.status == "applied")
                .where(Job.applied_at <= cutoff)
                .where(Job.contact_email != None)
                .limit(limit)
            )
            result = await session.execute(q)
            jobs_to_follow = result.scalars().all()

        console.print(f"[cyan]Found {len(jobs_to_follow)} jobs to follow up[/cyan]")

        for job in jobs_to_follow:
            job_dict = {
                "id": job.id, "title": job.title, "company": job.company,
                "url": job.url, "description": job.description or ""
            }
            email = await generate_follow_up_email(job_dict, profile, days)
            success = await send_email(
                to_address=job.contact_email,
                subject=email["subject"],
                body=email["body"],
                job_id=job.id,
                attach_resume=False,
            )
            if success:
                await update_job_status(job.id, "applied", f"Follow-up sent {datetime.utcnow().date()}")
                console.print(f"  [green]✓[/green] Follow-up → {job.company}")
            import asyncio as _a; await _a.sleep(60)

    asyncio.run(_run())


@app.command()
def export(
    fmt: str = typer.Option("csv", "--format", help="Export format: csv or json"),
    output: str = typer.Option("applications.csv", "--output", help="Output filename"),
):
    """Export all applications to CSV or JSON."""
    import json as _json
    from database import init_db, AsyncSessionLocal, Job
    from sqlalchemy import select
    init_db()

    async def _fetch():
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Job).where(Job.applied == True))
            return result.scalars().all()

    rows = asyncio.run(_fetch())

    if fmt == "csv":
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "title", "company", "location", "url", "source",
                "status", "apply_method", "contact_email", "applied_at", "match_score"
            ])
            writer.writeheader()
            for j in rows:
                writer.writerow({
                    "title": j.title, "company": j.company, "location": j.location,
                    "url": j.url, "source": j.source, "status": j.status,
                    "apply_method": j.apply_method, "contact_email": j.contact_email,
                    "applied_at": j.applied_at.isoformat() if j.applied_at else "",
                    "match_score": round(j.match_score or 0, 2),
                })
    elif fmt == "json":
        data = [
            {
                "title": j.title, "company": j.company, "status": j.status,
                "contact_email": j.contact_email,
                "applied_at": j.applied_at.isoformat() if j.applied_at else None,
            }
            for j in rows
        ]
        with open(output, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2)

    console.print(f"[green]✓[/green] Exported {len(rows)} applications to [bold]{output}[/bold]")


@app.command()
def update_status(
    job_id: str = typer.Argument(..., help="Job ID to update"),
    status: str = typer.Argument(..., help="New status: applied/replied/interview/rejected/pending"),
    notes: Optional[str] = typer.Option(None, help="Optional notes"),
):
    """Update the status of a specific job application."""
    from database import init_db, update_job_status
    init_db()
    asyncio.run(update_job_status(job_id, status, notes))
    console.print(f"[green]✓[/green] Updated {job_id} → [bold]{status}[/bold]")


if __name__ == "__main__":
    app()
