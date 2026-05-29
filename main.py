"""
main.py — FastAPI web app + APScheduler for daily automation.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import uvicorn

from config import settings
from database import init_db, get_stats, AsyncSessionLocal, Job, EmailLog, update_job_status
from resume_parser import parse_and_save_resume, load_profile
from orchestrator import run_daily_pipeline, run_email_only_pipeline
from email_sender import test_email_config, test_email_config_detailed

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH = "logs/app.log"
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_PATH, maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("job-bot")

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
    logger.info(f"Scheduler started. Daily run: {settings.RUN_HOUR:02d}:{settings.RUN_MINUTE:02d} {settings.TIMEZONE}")

# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from startup import run_all
    run_all()
    init_db()
    setup_scheduler()
    
    # Auto-parse the hydrated resume into DB if profile is empty
    profile = await load_profile()
    if not profile:
        logger.info("Database profile empty. Attempting auto-parse of hydrated resume...")
        try:
            if Path(settings.RESUME_PATH).exists():
                await parse_and_save_resume(settings.RESUME_PATH)
                logger.info("✓ Profile successfully hydrated from resume file.")
            else:
                logger.warning("No resume file found at startup to parse.")
        except Exception as e:
            logger.error(f"Failed to auto-parse resume at startup: {e}")

    logger.info("Application started and database initialized.")
    yield
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

@app.post("/api/run")
async def trigger_run(request: RunRequest):
    """Trigger a manual application run."""
    task_coro = run_email_only_pipeline(request.limit) if request.email_only else run_daily_pipeline(request.limit)
    asyncio.create_task(task_coro)
    return {"message": "Run started in background"}

@app.get("/api/jobs")
async def list_jobs(limit: int = 20):
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job).order_by(Job.scraped_at.desc()).limit(limit))
        jobs = result.scalars().all()
        return {"jobs": [
            {"company": j.company, "title": j.title, "status": j.status, "applied": j.applied}
            for j in jobs
        ]}

@app.get("/api/stats")
async def application_stats():
    stats = await get_stats()
    job = scheduler.get_job("daily_apply")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {**stats, "next_scheduled_run": next_run}

@app.get("/api/profile")
async def get_profile():
    profile = await load_profile()
    return {"profile": profile}

@app.post("/api/test-email")
async def send_test_email():
    return await test_email_config_detailed()

@app.get("/api/logs")
async def get_logs(lines: int = 100):
    if not Path(LOG_PATH).exists(): return {"logs": ""}
    with open(LOG_PATH, "r") as f:
        return {"logs": "".join(f.readlines()[-lines:])}

@app.get("/api/ping")
async def ping(): return {"pong": True}

@app.post("/api/upload-resume")
async def upload_resume_manual(file: UploadFile = File(...)):
    """Upload a PDF or DOCX resume and parse it."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, "Only PDF and DOCX files are supported")
    
    Path("uploads").mkdir(exist_ok=True)
    save_path = f"uploads/resume{suffix}"
    with open(save_path, "wb") as f:
        f.write(await file.read())
    
    settings.RESUME_PATH = save_path
    try:
        profile = await parse_and_save_resume(save_path)
        return {"success": True, "profile": profile}
    except Exception as e:
        logger.error(f"Manual resume parse failed: {e}")
        return {"success": False, "error": str(e)}

# ── Dashboard UI ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Auto-Apply Dashboard</title>
  <style>
    :root { --primary: #38bdf8; --bg: #0f172a; --card: rgba(30, 41, 59, 0.7); --text: #f1f5f9; --border: #334155; }
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 20px; }
    .overlay { position: fixed; inset: 0; background: var(--bg); z-index: 100; display: flex; align-items: center; justify-content: center; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 24px; backdrop-filter: blur(10px); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 20px; }
    .btn { padding: 10px 20px; border-radius: 6px; border: none; font-weight: 600; cursor: pointer; transition: 0.2s; background: var(--primary); color: #000; }
    input { width: 100%; padding: 10px; background: #000; border: 1px solid var(--border); color: #fff; border-radius: 6px; margin: 10px 0; }
    .tabs { display: flex; gap: 20px; border-bottom: 1px solid var(--border); margin: 20px 0; }
    .tab { padding: 10px; cursor: pointer; color: #94a3b8; }
    .tab.active { color: var(--primary); border-bottom: 2px solid var(--primary); }
    pre { background: #000; padding: 15px; border-radius: 8px; font-size: 12px; height: 300px; overflow: auto; border: 1px solid var(--border); }
  </style>
</head>
<body>
  <div id="login" class="overlay">
    <div class="card" style="width: 300px; text-align: center;">
      <h3>🔒 Unlock</h3>
      <input type="password" id="pass" placeholder="Password">
      <button class="btn" onclick="login()" style="width: 100%;">Login</button>
    </div>
  </div>

  <div id="main" style="max-width: 1000px; margin: 0 auto; display: none;">
    <h1>⚡ Mayur's Job Bot</h1>
    <div class="grid">
      <div class="card"><h5>Scraped</h5><h2 id="s-scraped">0</h2></div>
      <div class="card"><h5>Applied</h5><h2 id="s-applied">0</h2></div>
      <div class="card"><h5>Next Run</h5><p id="s-next">--</p></div>
    </div>

    <div class="tabs">
      <div class="tab active" onclick="tab('home', this)">Control</div>
      <div class="tab" onclick="tab('logs', this)">Logs</div>
      <div class="tab" onclick="tab('jobs', this)">Jobs</div>
      <div class="tab" onclick="tab('resume', this)">Resume</div>
    </div>

    <div id="p-home" class="pane">
      <button class="btn" onclick="run(false)">Trigger Full Run</button>
      <button class="btn" onclick="run(true)" style="background: #475569; color: #fff;">Email Only</button>
      <button class="btn" onclick="test()" style="background: #475569; color: #fff;">Test Email</button>
      <p id="status" style="margin-top: 15px; color: var(--primary);"></p>
    </div>
    <div id="p-logs" class="pane" style="display: none;"><pre id="log-c"></pre></div>
    <div id="p-jobs" class="pane" style="display: none;"><div id="job-l"></div></div>
    <div id="p-resume" class="pane" style="display: none;">
      <h3>Resume Profile</h3>
      <div id="profile-c" style="margin: 15px 0; font-size: 14px; background: rgba(0,0,0,0.3); padding: 15px; border-radius: 8px;">Loading...</div>
      <hr style="border:0; border-top:1px solid var(--border); margin: 20px 0;">
      <h3>Update Resume</h3>
      <input type="file" id="r-file" accept=".pdf,.docx">
      <button class="btn" onclick="upload()">Parse & Save</button>
    </div>
  </div>

  <script>
    const PASS = "mayurjob08";
    if(localStorage.getItem('auth') === PASS) unlock();

    function login() {
      if(document.getElementById('pass').value === PASS) {
        localStorage.setItem('auth', PASS);
        unlock();
      } else alert('Wrong password');
    }

    function unlock() {
      document.getElementById('login').style.display = 'none';
      document.getElementById('main').style.display = 'block';
      refresh();
    }

    function tab(id, el) {
      document.querySelectorAll('.pane').forEach(p => p.style.display = 'none');
      document.getElementById('p-'+id).style.display = 'block';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      el.classList.add('active');
      if(id === 'logs') loadLogs();
      if(id === 'jobs') loadJobs();
      if(id === 'resume') loadProfile();
    }

    async function refresh() {
      const d = await (await fetch('/api/stats')).json();
      document.getElementById('s-scraped').textContent = d.total_scraped || 0;
      document.getElementById('s-applied').textContent = d.total_applied || 0;
      document.getElementById('s-next').textContent = d.next_scheduled_run ? new Date(d.next_scheduled_run).toLocaleTimeString() : '--';
    }

    async function run(eo) {
      document.getElementById('status').textContent = 'Starting...';
      await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email_only:eo})});
      document.getElementById('status').textContent = 'Running in background. Check Logs tab.';
    }

    async function loadLogs() {
      const d = await (await fetch('/api/logs')).json();
      const el = document.getElementById('log-c');
      el.textContent = d.logs || 'No logs yet.';
      el.scrollTop = el.scrollHeight;
    }

    async function loadJobs() {
      const d = await (await fetch('/api/jobs')).json();
      document.getElementById('job-l').innerHTML = d.jobs.map(j => `<div style="padding:10px; border-bottom:1px solid #334155">${j.company} - ${j.title} (${j.status})</div>`).join('');
    }

    async function loadProfile() {
      const d = await (await fetch('/api/profile')).json();
      if(!d.profile) {
        document.getElementById('profile-c').textContent = "No profile found. Upload resume below.";
        return;
      }
      document.getElementById('profile-c').innerHTML = `
        <p><strong>Name:</strong> ${d.profile.name}</p>
        <p><strong>Skills:</strong> ${d.profile.skills.slice(0, 15).join(', ')}...</p>
        <p><strong>AI Suggested Roles:</strong> ${d.profile.suggested_titles ? d.profile.suggested_titles.join(', ') : 'None'}</p>
        <p><strong>AI Search Keywords:</strong> ${d.profile.suggested_keywords ? d.profile.suggested_keywords.join(', ') : 'None'}</p>
      `;
    }

    async function upload() {
      const file = document.getElementById('r-file').files[0];
      if(!file) return alert('Select a file');
      const fd = new FormData(); fd.append('file', file);
      document.getElementById('profile-c').textContent = "Parsing...";
      const r = await fetch('/api/upload-resume', {method:'POST', body:fd});
      const res = await r.json();
      if(res.success) loadProfile();
      else alert('Failed: ' + res.error);
    }

    async function test() { await fetch('/api/test-email', {method:'POST'}); alert('Test email sent'); }
    setInterval(refresh, 30000);
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--parse-resume" in args: asyncio.run(parse_and_save_resume())
    elif "--run" in args: asyncio.run(run_daily_pipeline())
    elif "--test-email" in args: asyncio.run(test_email_config())
    else:
        import os
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
