"""
main.py — FastAPI web app + APScheduler for daily automation.

Endpoints:
  GET  /              → dashboard (React SPA)
  POST /api/parse-resume  → upload & parse resume
  POST /api/run       → trigger manual run
  GET  /api/jobs      → list all jobs with status
  GET  /api/stats     → application statistics
  POST /api/test-email → send test email
  GET  /api/profile   → current resume profile
  PUT  /api/job/{id}/status → update job status
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from database import init_db, get_stats, AsyncSessionLocal, Job, update_job_status
from resume_parser import parse_and_save_resume, load_profile
from orchestrator import run_daily_pipeline, run_email_only_pipeline
from email_sender import test_email_config

import uvicorn

# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


def setup_scheduler():
    tz = pytz.timezone(settings.TIMEZONE)
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(
            hour=settings.RUN_HOUR,
            minute=settings.RUN_MINUTE,
            timezone=tz
        ),
        id="daily_apply",
        name="Daily Job Application",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[Scheduler] Daily run set for {settings.RUN_HOUR:02d}:{settings.RUN_MINUTE:02d} "
          f"{settings.TIMEZONE}")


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from startup import run_all
    run_all()           # hydrate resume from env var, check config, create dirs
    init_db()
    setup_scheduler()
    print("[App] Job Auto-Apply started ✅")
    yield
    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="Job Auto-Apply", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routes ────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    limit: Optional[int] = None
    email_only: bool = False


class StatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


@app.post("/api/parse-resume")
async def upload_resume(file: UploadFile = File(...)):
    """Upload a PDF or DOCX resume and parse it."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, "Only PDF and DOCX files are supported")

    save_path = f"uploads/resume{suffix}"
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Update settings (in-process)
    settings.RESUME_PATH = save_path

    try:
        profile = await parse_and_save_resume(save_path)
        return {"success": True, "profile": profile}
    except Exception as e:
        raise HTTPException(500, f"Resume parsing failed: {e}")


@app.get("/api/profile")
async def get_profile():
    profile = await load_profile()
    if not profile:
        return {"profile": None, "message": "No resume uploaded yet"}
    return {"profile": profile}


@app.post("/api/run")
async def trigger_run(request: RunRequest, background_tasks: BackgroundTasks):
    """Trigger a manual application run."""
    if request.email_only:
        background_tasks.add_task(run_email_only_pipeline, request.limit)
    else:
        background_tasks.add_task(run_daily_pipeline, request.limit)
    return {
        "message": "Application run started in background",
        "limit": request.limit or settings.DAILY_LIMIT,
        "email_only": request.email_only,
    }


@app.get("/api/jobs")
async def list_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    applied: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
):
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        q = select(Job)
        if status:
            q = q.where(Job.status == status)
        if source:
            q = q.where(Job.source == source)
        if applied is not None:
            q = q.where(Job.applied == applied)
        q = q.order_by(Job.scraped_at.desc()).offset(offset).limit(limit)
        result = await session.execute(q)
        jobs = result.scalars().all()
        return {
            "jobs": [
                {
                    "id": j.id, "title": j.title, "company": j.company,
                    "location": j.location, "url": j.url, "source": j.source,
                    "applied": j.applied, "status": j.status,
                    "apply_method": j.apply_method,
                    "applied_at": j.applied_at.isoformat() if j.applied_at else None,
                    "contact_email": j.contact_email,
                    "match_score": j.match_score,
                    "salary": j.salary,
                }
                for j in jobs
            ],
            "total": len(jobs),
        }


@app.get("/api/stats")
async def application_stats():
    stats = await get_stats()
    # Next run time
    job = scheduler.get_job("daily_apply")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        **stats,
        "next_scheduled_run": next_run,
        "daily_limit": settings.DAILY_LIMIT,
        "run_time": f"{settings.RUN_HOUR:02d}:{settings.RUN_MINUTE:02d} {settings.TIMEZONE}",
    }


@app.put("/api/job/{job_id}/status")
async def update_status(job_id: str, update: StatusUpdate):
    await update_job_status(job_id, update.status, update.notes)
    return {"success": True}


@app.post("/api/test-email")
async def send_test_email():
    success = await test_email_config()
    return {"success": success, "message": "Check your inbox!" if success else "Email failed — check config"}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "scheduler": scheduler.running,
    }

@app.get("/api/ping")
async def ping():
    """Lightweight keep-alive endpoint — hit this every 10 min via cron-job.org
    to prevent Render free tier from spinning down before the 8 AM scheduler fires."""
    return {"pong": True, "time": datetime.utcnow().isoformat()}


# ── Serve dashboard ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the React dashboard (built separately or inline)."""
    return """
<!DOCTYPE html>
<html><head>
<title>Job Auto-Apply</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: system-ui; background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px; }
  h1 { color: #38bdf8; }
  .card { background: #1e293b; border-radius: 8px; padding: 16px; margin: 12px 0; }
  .btn { background: #0ea5e9; color: white; border: none; padding: 8px 16px;
         border-radius: 6px; cursor: pointer; margin: 4px; }
  .btn:hover { background: #0284c7; }
  .stat { display: inline-block; margin: 8px; text-align: center; }
  .stat .num { font-size: 2em; font-weight: bold; color: #38bdf8; }
  input[type=file] { color: #e2e8f0; }
</style>
</head>
<body>
<h1>⚡ Job Auto-Apply</h1>
<div class="card" id="stats">Loading stats...</div>
<div class="card">
  <h3>Upload Resume</h3>
  <input type="file" id="resumeFile" accept=".pdf,.docx">
  <button class="btn" onclick="uploadResume()">Parse Resume</button>
  <div id="resumeResult"></div>
</div>
<div class="card">
  <h3>Run Now</h3>
  <button class="btn" onclick="runNow(false)">▶ Full Run (Email + Forms)</button>
  <button class="btn" onclick="runNow(true)">📧 Email Only</button>
  <button class="btn" onclick="testEmail()">🔧 Test Email Config</button>
  <div id="runResult"></div>
</div>
<div class="card">
  <h3>Recent Applications</h3>
  <div id="jobs">Loading...</div>
</div>
<script>
async function loadStats() {
  const r = await fetch('/api/stats'); const d = await r.json();
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="num">${d.total_scraped||0}</div>Scraped</div>
    <div class="stat"><div class="num">${d.total_applied||0}</div>Applied</div>
    <div class="stat"><div class="num">${(d.by_status||{}).interview||0}</div>Interviews</div>
    <div class="stat"><div class="num">${(d.by_status||{}).replied||0}</div>Replies</div>
    <small>Next run: ${d.next_scheduled_run ? new Date(d.next_scheduled_run).toLocaleString() : 'not scheduled'}</small>`;
}
async function uploadResume() {
  const f = document.getElementById('resumeFile').files[0];
  if (!f) return alert('Select a file first');
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/parse-resume', {method:'POST', body:fd});
  const d = await r.json();
  document.getElementById('resumeResult').innerHTML = d.success
    ? `✅ Parsed: ${d.profile.name} | ${d.profile.skills?.length} skills`
    : `❌ ${JSON.stringify(d)}`;
}
async function runNow(emailOnly) {
  const r = await fetch('/api/run', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email_only:emailOnly})});
  const d = await r.json();
  document.getElementById('runResult').innerHTML = `✅ ${d.message}`;
  setTimeout(loadStats, 5000);
}
async function testEmail() {
  const r = await fetch('/api/test-email', {method:'POST'});
  const d = await r.json();
  document.getElementById('runResult').innerHTML = d.success
    ? '✅ Test email sent — check your inbox!'
    : `❌ ${d.message}`;
}
async function loadJobs() {
  const r = await fetch('/api/jobs?applied=true&limit=20');
  const d = await r.json();
  document.getElementById('jobs').innerHTML = d.jobs.length === 0 ? 'No applications yet' :
    d.jobs.map(j => `<div style="border-bottom:1px solid #334155;padding:8px 0">
      <strong>${j.title}</strong> @ ${j.company}
      <span style="color:#94a3b8;font-size:0.85em"> · ${j.source} · ${j.apply_method||''} · ${j.status}</span>
      ${j.url ? `<a href="${j.url}" target="_blank" style="color:#38bdf8;margin-left:8px">View</a>` : ''}
    </div>`).join('');
}
loadStats(); loadJobs();
</script>
</body></html>"""


# ── CLI entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import typer
    import sys

    args = sys.argv[1:]

    if "--parse-resume" in args:
        asyncio.run(parse_and_save_resume())
    elif "--run" in args:
        asyncio.run(run_daily_pipeline())
    elif "--email-only" in args:
        asyncio.run(run_email_only_pipeline())
    elif "--test-email" in args:
        asyncio.run(test_email_config())
    else:
        import os
        port = int(os.environ.get("PORT", 8000))  # Render injects PORT
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=port,
            reload=False,
            log_level="info"
        )
