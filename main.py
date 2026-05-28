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

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from database import init_db, get_stats, AsyncSessionLocal, Job, EmailLog, update_job_status
from resume_parser import parse_and_save_resume, load_profile
from orchestrator import run_daily_pipeline, run_email_only_pipeline
from email_sender import test_email_config, test_email_config_detailed

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
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60 * 60 * 6,
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
async def trigger_run(request: RunRequest):
    """Trigger a manual application run."""
    task_coro = run_email_only_pipeline(request.limit) if request.email_only else run_daily_pipeline(request.limit)
    task = asyncio.create_task(task_coro)

    def _task_done(future: asyncio.Future):
        try:
            exc = future.exception()
            if exc:
                print(f"[Run] Background task failed: {exc}")
        except asyncio.CancelledError:
            print("[Run] Background task was cancelled")

    task.add_done_callback(_task_done)
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
    return await test_email_config_detailed()


@app.get("/api/stats-detailed")
async def detailed_stats():
    """Detailed stats including timeline and distribution (for visualization)."""
    from visualizer import export_stats_json
    return await export_stats_json()


@app.get("/api/email-audit")
async def email_audit(token: Optional[str] = None, limit: int = 25):
    """Review stored sent email content. Requires EMAIL_AUDIT_TOKEN."""
    if not settings.EMAIL_AUDIT_TOKEN:
        raise HTTPException(
            403,
            "Email audit is disabled. Set EMAIL_AUDIT_TOKEN in the environment first.",
        )
    if token != settings.EMAIL_AUDIT_TOKEN:
        raise HTTPException(403, "Invalid email audit token")

    from sqlalchemy import select
    safe_limit = max(1, min(limit, 100))
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailLog)
            .order_by(EmailLog.sent_at.desc())
            .limit(safe_limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": log.id,
                    "job_id": log.job_id,
                    "to_address": log.to_address,
                    "to_name": log.to_name,
                    "subject": log.subject,
                    "body": log.body,
                    "sent_at": log.sent_at.isoformat() if log.sent_at else None,
                    "success": log.success,
                    "error": log.error,
                }
                for log in logs
            ]
        }


@app.get("/api/logs")
async def get_logs(lines: int = 100):
    """Return the last N lines of the application log."""
    if not Path(LOG_PATH).exists():
        return {"logs": "Log file not found."}
    with open(LOG_PATH, "r") as f:
        content = f.readlines()
        return {"logs": "".join(content[-lines:])}

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
    """Serve the modern React-like dashboard with simple password protection."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" href="data:,">
  <title>Job Auto-Apply — AI Dashboard</title>
  <style>
    :root {
      --primary: #38bdf8;
      --primary-hover: #0ea5e9;
      --bg: #0f172a;
      --card-bg: rgba(30, 41, 59, 0.7);
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --border: #334155;
      --success: #22c55e;
      --error: #ef4444;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: radial-gradient(circle at top right, #1e293b, #0f172a);
      color: var(--text);
      line-height: 1.6;
      min-height: 100vh;
    }
    .login-overlay {
      position: fixed; top: 0; left: 0; width: 100%; height: 100%;
      background: var(--bg); z-index: 1000;
      display: flex; align-items: center; justify-content: center;
      transition: opacity 0.5s;
    }
    .login-card {
      background: var(--card-bg); border: 1px solid var(--border);
      padding: 40px; border-radius: 16px; width: 100%; max-width: 400px;
      text-align: center; backdrop-filter: blur(10px);
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 20px; display: none; }
    header {
      padding: 40px 0; border-bottom: 1px solid var(--border); margin-bottom: 40px;
    }
    h1 { font-size: 32px; color: var(--primary); letter-spacing: -1px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-bottom: 40px; }
    .card {
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: 16px; padding: 24px; backdrop-filter: blur(10px);
      transition: transform 0.2s, border-color 0.2s;
    }
    .card:hover { transform: translateY(-4px); border-color: var(--primary); }
    .stat-val { font-size: 36px; font-weight: 800; color: var(--primary); }
    .stat-label { font-size: 12px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 1px; }
    .btn {
      padding: 12px 24px; border-radius: 8px; border: none; font-weight: 600;
      cursor: pointer; transition: 0.2s; font-size: 14px;
    }
    .btn-primary { background: var(--primary); color: #000; }
    .btn-primary:hover { background: var(--primary-hover); box-shadow: 0 0 20px rgba(56, 189, 248, 0.4); }
    .btn-secondary { background: var(--border); color: var(--text); }
    input {
      width: 100%; padding: 12px; background: rgba(0,0,0,0.2);
      border: 1px solid var(--border); border-radius: 8px; color: white; margin-bottom: 16px;
    }
    .job-item {
      padding: 20px; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center;
    }
    .job-item:last-child { border: none; }
    .badge { padding: 4px 12px; border-radius: 99px; font-size: 11px; font-weight: 700; }
    .badge-applied { background: rgba(34, 197, 94, 0.2); color: var(--success); }
    .tabs { display: flex; gap: 20px; margin-bottom: 30px; border-bottom: 1px solid var(--border); }
    .tab { padding: 12px 0; color: var(--text-muted); cursor: pointer; position: relative; }
    .tab.active { color: var(--primary); font-weight: 700; }
    .tab.active::after { content: ''; position: absolute; bottom: -1px; left: 0; width: 100%; height: 2px; background: var(--primary); }
  </style>
</head>
<body>
  <div id="login" class="login-overlay">
    <div class="login-card">
      <h2 style="margin-bottom: 24px;">🔒 Access Locked</h2>
      <input type="password" id="pass" placeholder="Enter Password" onkeypress="if(event.key==='Enter') checkPass()">
      <button class="btn btn-primary" style="width: 100%;" onclick="checkPass()">Unlock Dashboard</button>
      <p id="err" style="color: var(--error); margin-top: 16px; font-size: 13px; display: none;">Invalid Password</p>
    </div>
  </div>

  <div id="main-content" class="container">
    <header>
      <h1>⚡ Mayur's Job Bot</h1>
      <p style="color: var(--text-muted);">Autonomous Job Application Engine • Powered by Gemini 1.5 Flash</p>
    </header>

    <div class="grid">
      <div class="card">
        <div class="stat-label">Total Scraped</div>
        <div class="stat-val" id="s-scraped">0</div>
      </div>
      <div class="card">
        <div class="stat-label">Applications Sent</div>
        <div class="stat-val" id="s-applied">0</div>
      </div>
      <div class="card">
        <div class="stat-label">Interview Status</div>
        <div class="stat-val" id="s-interviews">0</div>
      </div>
    </div>

    <div class="card">
      <div class="tabs">
        <div class="tab active" onclick="show('pane-home', this)">Control Center</div>
        <div class="tab" onclick="show('pane-jobs', this)">Live Log</div>
        <div class="tab" onclick="show('pane-resume', this)">Resume Profile</div>
        <div class="tab" onclick="show('pane-logs', this)">System Logs</div>
      </div>

      <div id="pane-home" class="pane">
        <h3 style="margin-bottom: 20px;">Manual Controls</h3>
        <div style="display: flex; gap: 12px;">
          <button class="btn btn-primary" onclick="run(false)">▶ Trigger Daily Run</button>
          <button class="btn btn-secondary" onclick="run(true)">📧 Email Only Mode</button>
          <button class="btn btn-secondary" onclick="testMail()">🔧 Test Config</button>
        </div>
        <div id="status" style="margin-top: 20px;"></div>
      </div>

      <div id="pane-jobs" class="pane" style="display: none;">
        <div id="job-list">Loading jobs...</div>
      </div>

      <div id="pane-resume" class="pane" style="display: none;">
        <div id="profile-data">Loading profile...</div>
      </div>
    </div>
  </div>

  <script>
    const PASS = "mayurjob08";
    
    function checkPass() {
      if (document.getElementById('pass').value === PASS) {
        document.getElementById('login').style.opacity = '0';
        setTimeout(() => {
          document.getElementById('login').style.display = 'none';
          document.getElementById('main-content').style.display = 'block';
          loadAll();
        }, 500);
      } else {
        document.getElementById('err').style.display = 'block';
      }
    }

    function show(id, el) {
      document.querySelectorAll('.pane').forEach(p => p.style.display = 'none');
      document.getElementById(id).style.display = 'block';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      el.classList.add('active');
      if(id === 'pane-jobs') loadJobs();
      if(id === 'pane-resume') loadProfile();
    }

    async function loadAll() {
      const r = await fetch('/api/stats');
      const d = await r.json();
      document.getElementById('s-scraped').textContent = d.total_scraped || 0;
      document.getElementById('s-applied').textContent = d.total_applied || 0;
      document.getElementById('s-interviews').textContent = d.by_status?.interview || 0;
    }

    async function loadJobs() {
      const r = await fetch('/api/jobs?limit=20');
      const d = await r.json();
      document.getElementById('job-list').innerHTML = d.jobs.map(j => `
        <div class="job-item">
          <div>
            <div style="font-weight: 700;">${j.company}</div>
            <div style="font-size: 13px; color: var(--text-muted);">${j.title}</div>
          </div>
          <span class="badge ${j.applied ? 'badge-applied' : ''}" style="background: ${j.applied ? '' : '#334155'}">
            ${j.status.toUpperCase()}
          </span>
        </div>
      `).join('');
    }

    async function loadProfile() {
      const r = await fetch('/api/profile');
      const d = await r.json();
      if(!d.profile) return;
      document.getElementById('profile-data').innerHTML = `
        <p><strong>Name:</strong> ${d.profile.name}</p>
        <p><strong>Skills:</strong> ${d.profile.skills.slice(0,10).join(', ')}...</p>
      `;
    }

    async function run(emailOnly) {
      document.getElementById('status').innerHTML = '⏳ Triggering pipeline...';
      const r = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email_only: emailOnly})
      });
      document.getElementById('status').innerHTML = '✅ Run started in background. Check logs in a few minutes.';
    }

    async function testMail() {
      const r = await fetch('/api/test-email', {method: 'POST'});
      alert('Test email request sent!');
    }
  </script>
</body>
</html>"""


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
eline())
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
