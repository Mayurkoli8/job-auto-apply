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
    success = await test_email_config()
    return {"success": success, "message": "Check your inbox!" if success else "Email failed — check config"}


@app.get("/api/stats-detailed")
async def detailed_stats():
    """Detailed stats including timeline and distribution (for visualization)."""
    from visualizer import export_stats_json
    return await export_stats_json()


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
    """Serve the modern React-like dashboard."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" href="data:,">
  <title>Job Auto-Apply — AI-Powered Job Bot</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #e2e8f0;
      line-height: 1.6;
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
    header {
      background: rgba(15, 23, 42, 0.8);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid #334155;
      padding: 20px 0;
      sticky-top: 0;
      z-index: 100;
    }
    header h1 { font-size: 28px; font-weight: 700; color: #38bdf8; margin-bottom: 4px; }
    header p { font-size: 14px; color: #94a3b8; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin: 30px 0; }
    .card {
      background: rgba(30, 41, 59, 0.5);
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 24px;
      transition: all 0.3s;
    }
    .card:hover { border-color: #64748b; background: rgba(30, 41, 59, 0.7); }
    .stat-card { text-align: center; }
    .stat-number { font-size: 40px; font-weight: 700; color: #38bdf8; margin: 12px 0; }
    .stat-label { font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
    .btn {
      display: inline-block;
      padding: 12px 24px;
      background: #0ea5e9;
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      transition: all 0.3s;
      text-decoration: none;
    }
    .btn:hover { background: #0284c7; transform: translateY(-2px); box-shadow: 0 10px 20px rgba(14, 165, 233, 0.2); }
    .btn:disabled { background: #64748b; cursor: not-allowed; transform: none; }
    .btn-secondary { background: #475569; }
    .btn-secondary:hover { background: #64748b; }
    .btn-small { padding: 8px 16px; font-size: 12px; }
    .btn-group { display: flex; gap: 12px; flex-wrap: wrap; }
    .input-group {
      display: flex;
      gap: 12px;
      margin: 16px 0;
    }
    input[type="file"], input[type="number"] {
      flex: 1;
      padding: 12px;
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid #334155;
      border-radius: 8px;
      color: #e2e8f0;
      font-size: 14px;
    }
    input[type="file"]::file-selector-button {
      background: #475569;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      cursor: pointer;
      margin-right: 12px;
    }
    .tabs {
      display: flex;
      gap: 12px;
      border-bottom: 1px solid #334155;
      margin-bottom: 20px;
    }
    .tab {
      padding: 12px 20px;
      background: transparent;
      border: none;
      color: #94a3b8;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      border-bottom: 2px solid transparent;
      transition: all 0.3s;
    }
    .tab.active {
      color: #38bdf8;
      border-bottom-color: #38bdf8;
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .alert {
      padding: 16px;
      border-radius: 8px;
      margin: 16px 0;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .alert-success { background: rgba(34, 197, 94, 0.1); border: 1px solid #22c55e; color: #86efac; }
    .alert-error { background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; color: #fca5a5; }
    .alert-info { background: rgba(59, 130, 246, 0.1); border: 1px solid #3b82f6; color: #93c5fd; }
    .job-item {
      background: rgba(30, 41, 59, 0.3);
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 12px;
      transition: all 0.3s;
    }
    .job-item:hover { border-color: #64748b; background: rgba(30, 41, 59, 0.5); }
    .job-title { font-size: 16px; font-weight: 600; color: #e2e8f0; margin-bottom: 4px; }
    .job-company { font-size: 14px; color: #38bdf8; margin-bottom: 8px; }
    .job-meta { font-size: 12px; color: #94a3b8; margin-bottom: 12px; }
    .job-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .badge { display: inline-block; padding: 4px 12px; background: rgba(56, 189, 248, 0.2); color: #38bdf8; border-radius: 4px; font-size: 11px; font-weight: 600; }
    .badge-success { background: rgba(34, 197, 94, 0.2); color: #86efac; }
    .badge-pending { background: rgba(251, 146, 60, 0.2); color: #fed7aa; }
    .profile-item { margin-bottom: 16px; }
    .profile-label { font-size: 12px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px; margin-bottom: 4px; }
    .profile-value { font-size: 14px; color: #e2e8f0; word-break: break-word; }
    .skill-list { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .skill-tag { background: rgba(56, 189, 248, 0.1); border: 1px solid #38bdf8; color: #38bdf8; padding: 4px 10px; border-radius: 4px; font-size: 12px; }
    .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
    .section-heading h3 { color: #38bdf8; font-size: 20px; }
    .metric-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }
    .metric {
      border-top: 1px solid #334155;
      padding-top: 12px;
    }
    .metric-value { font-size: 24px; font-weight: 700; color: #e2e8f0; }
    .metric-label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
    .analytics-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr); gap: 24px; }
    .analytics-panel { min-height: 260px; }
    .analytics-panel h4 { font-size: 14px; color: #cbd5e1; margin-bottom: 14px; }
    .bar-chart { display: flex; flex-direction: column; gap: 10px; }
    .bar-row { display: grid; grid-template-columns: minmax(84px, 140px) 1fr 42px; gap: 10px; align-items: center; font-size: 12px; color: #cbd5e1; }
    .bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-track { height: 10px; background: rgba(148, 163, 184, 0.16); border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; background: linear-gradient(90deg, #38bdf8, #22c55e); border-radius: 999px; min-width: 2px; }
    .bar-value { text-align: right; color: #94a3b8; }
    .timeline-chart {
      height: 180px;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(6px, 1fr);
      align-items: end;
      gap: 4px;
      padding: 12px 0 4px;
      border-bottom: 1px solid #334155;
    }
    .timeline-bar { background: #38bdf8; border-radius: 4px 4px 0 0; min-height: 2px; opacity: 0.9; }
    .empty-state { color: #94a3b8; font-size: 14px; padding: 12px 0; }
    .spinner {
      display: inline-block;
      width: 20px;
      height: 20px;
      border: 3px solid rgba(56, 189, 248, 0.3);
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 760px) {
      .container { padding: 14px; }
      .tabs { overflow-x: auto; }
      .tab { padding: 12px 14px; white-space: nowrap; }
      .input-group { flex-direction: column; }
      .analytics-grid { grid-template-columns: 1fr; }
      .bar-row { grid-template-columns: minmax(70px, 110px) 1fr 34px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>⚡ Job Auto-Apply</h1>
      <p>AI-powered automated job applications • Scrapes 7 job boards • Sends personalized emails • Fills ATS forms</p>
    </div>
  </header>

  <div class="container">
    <!-- Stats Row -->
    <div class="grid">
      <div class="card stat-card">
        <div class="stat-label">Scraped Jobs</div>
        <div class="stat-number" id="stat-scraped">0</div>
      </div>
      <div class="card stat-card">
        <div class="stat-label">Applied</div>
        <div class="stat-number" id="stat-applied">0</div>
      </div>
      <div class="card stat-card">
        <div class="stat-label">Interviews</div>
        <div class="stat-number" id="stat-interviews">0</div>
      </div>
      <div class="card stat-card">
        <div class="stat-label">Next Run</div>
        <div class="stat-number" id="stat-nextrun" style="font-size: 16px;">--:-- --</div>
      </div>
    </div>

    <!-- Main Tabs -->
    <div class="card">
      <div class="tabs">
        <button class="tab active" onclick="switchTab(this, 'dashboard')">Dashboard</button>
        <button class="tab" onclick="switchTab(this, 'analytics')">Analytics</button>
        <button class="tab" onclick="switchTab(this, 'resume')">Resume</button>
        <button class="tab" onclick="switchTab(this, 'jobs')">Jobs</button>
        <button class="tab" onclick="switchTab(this, 'run')">Run Now</button>
      </div>

      <!-- Dashboard Tab -->
      <div id="dashboard" class="tab-content active">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">Quick Actions</h3>
        <div class="btn-group">
          <button class="btn" onclick="manualRun(false)">▶ Full Run (Email + Forms)</button>
          <button class="btn btn-secondary" onclick="manualRun(true)">📧 Email Only</button>
          <button class="btn btn-secondary" onclick="testEmailConfig(this)">🔧 Test Email Config</button>
        </div>
        <div id="run-status"></div>
        <hr style="margin: 24px 0; border: none; border-top: 1px solid #334155;">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">Recent Applications</h3>
        <div id="recent-jobs">Loading...</div>
      </div>

      <!-- Analytics Tab -->
      <div id="analytics" class="tab-content">
        <div class="section-heading">
          <h3>Analytics</h3>
          <button class="btn btn-small btn-secondary" onclick="loadDetailedStats()">Refresh</button>
        </div>
        <div id="analytics-summary" class="metric-row">
          <div class="empty-state">Loading analytics...</div>
        </div>
        <div class="analytics-grid">
          <section class="analytics-panel">
            <h4>Applications over 30 days</h4>
            <div id="chart-timeline"></div>
          </section>
          <section class="analytics-panel">
            <h4>Jobs by source</h4>
            <div id="chart-source"></div>
          </section>
          <section class="analytics-panel">
            <h4>Match score distribution</h4>
            <div id="chart-match"></div>
          </section>
        </div>
      </div>

      <!-- Resume Tab -->
      <div id="resume" class="tab-content">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">📄 Resume Upload & Parsing</h3>
        <div class="input-group">
          <input type="file" id="resumeFile" accept=".pdf,.docx" placeholder="Choose PDF or DOCX">
          <button class="btn" onclick="uploadResume()">Parse Resume</button>
        </div>
        <div id="resume-upload-result"></div>
        <hr style="margin: 24px 0; border: none; border-top: 1px solid #334155;">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">Parsed Profile</h3>
        <div id="profile-display">No resume uploaded yet</div>
      </div>

      <!-- Jobs Tab -->
      <div id="jobs" class="tab-content">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">📊 Job Listings</h3>
        <div class="btn-group" style="margin-bottom: 16px;">
          <button class="btn btn-small" onclick="filterJobs('all')">All</button>
          <button class="btn btn-small btn-secondary" onclick="filterJobs('applied')">Applied</button>
          <button class="btn btn-small btn-secondary" onclick="filterJobs('pending')">Pending</button>
        </div>
        <div id="jobs-list">Loading jobs...</div>
      </div>

      <!-- Run Now Tab -->
      <div id="run" class="tab-content">
        <h3 style="margin-bottom: 16px; color: #38bdf8;">⚙️ Manual Trigger</h3>
        <div style="margin-bottom: 16px;">
          <label style="display: block; margin-bottom: 8px; font-size: 14px;">Job Limit (leave 0 for default: 50)</label>
          <input type="number" id="jobLimit" value="50" min="0" max="200" style="width: 100%;"/>
        </div>
        <div class="btn-group">
          <button class="btn" onclick="customRun(false)">▶ Run Full Pipeline</button>
          <button class="btn btn-secondary" onclick="customRun(true)">📧 Email Only</button>
        </div>
        <div id="custom-run-result"></div>
      </div>
    </div>
  </div>

  <script>
    let currentFilter = 'all';

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[c]));
    }

    function safeHttpUrl(value) {
      if (!value) return '';
      try {
        const url = new URL(value, window.location.href);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
      } catch (_) {
        return '';
      }
    }

    function renderEmpty(containerId, message) {
      document.getElementById(containerId).innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    }

    function renderBarChart(containerId, data, limit = 8) {
      const entries = Object.entries(data || {})
        .filter(([, value]) => Number(value) > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, limit);
      if (!entries.length) {
        renderEmpty(containerId, 'No data yet');
        return;
      }
      const max = Math.max(...entries.map(([, value]) => Number(value)), 1);
      document.getElementById(containerId).innerHTML = `
        <div class="bar-chart">
          ${entries.map(([label, value]) => {
            const width = Math.max(2, Math.round((Number(value) / max) * 100));
            return `
              <div class="bar-row" title="${escapeHtml(label)}: ${Number(value)}">
                <div class="bar-label">${escapeHtml(label)}</div>
                <div class="bar-track"><div class="bar-fill" style="width: ${width}%"></div></div>
                <div class="bar-value">${Number(value)}</div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    function renderTimeline(containerId, data) {
      const entries = Object.entries(data || {}).sort((a, b) => a[0].localeCompare(b[0]));
      if (!entries.length || entries.every(([, value]) => Number(value) === 0)) {
        renderEmpty(containerId, 'No applications recorded in the last 30 days');
        return;
      }
      const max = Math.max(...entries.map(([, value]) => Number(value)), 1);
      document.getElementById(containerId).innerHTML = `
        <div class="timeline-chart">
          ${entries.map(([date, value]) => {
            const height = Math.max(2, Math.round((Number(value) / max) * 100));
            return `<div class="timeline-bar" title="${escapeHtml(date)}: ${Number(value)}" style="height: ${height}%"></div>`;
          }).join('')}
        </div>
      `;
    }

    // Tab switching
    function switchTab(button, tab) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      button.classList.add('active');
      document.getElementById(tab).classList.add('active');
      if (tab === 'analytics') loadDetailedStats();
      if (tab === 'jobs') loadJobs();
      if (tab === 'resume') loadProfile();
    }

    // Load stats
    async function loadStats() {
      try {
        const r = await fetch('/api/stats');
        const d = await r.json();
        document.getElementById('stat-scraped').textContent = d.total_scraped || 0;
        document.getElementById('stat-applied').textContent = d.total_applied || 0;
        document.getElementById('stat-interviews').textContent = (d.by_status?.interview || 0);
        if (d.next_scheduled_run) {
          const next = new Date(d.next_scheduled_run);
          document.getElementById('stat-nextrun').textContent = next.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        }
      } catch (e) { console.error('Stats error:', e); }
    }

    async function loadDetailedStats() {
      try {
        const r = await fetch('/api/stats-detailed');
        const d = await r.json();
        const summary = d.summary || {};
        document.getElementById('analytics-summary').innerHTML = `
          <div class="metric">
            <div class="metric-value">${Number(summary.total_jobs || 0)}</div>
            <div class="metric-label">Total Jobs</div>
          </div>
          <div class="metric">
            <div class="metric-value">${Number(summary.applied || 0)}</div>
            <div class="metric-label">Applied</div>
          </div>
          <div class="metric">
            <div class="metric-value">${Number(summary.pending || 0)}</div>
            <div class="metric-label">Pending</div>
          </div>
          <div class="metric">
            <div class="metric-value">${Number(summary.average_match_score || 0).toFixed(3)}</div>
            <div class="metric-label">Avg Match</div>
          </div>
        `;
        renderTimeline('chart-timeline', d.timeline_30_days || {});
        renderBarChart('chart-source', summary.by_source || {});
        renderBarChart('chart-match', d.match_score_distribution || {}, 5);
      } catch (e) {
        console.error('Detailed stats error:', e);
        renderEmpty('analytics-summary', 'Unable to load analytics');
        renderEmpty('chart-timeline', 'Unable to load timeline');
        renderEmpty('chart-source', 'Unable to load source data');
        renderEmpty('chart-match', 'Unable to load match scores');
      }
    }

    // Upload resume
    async function uploadResume() {
      const file = document.getElementById('resumeFile').files[0];
      if (!file) { showAlert('Please select a file', 'error'); return; }
      
      const fd = new FormData();
      fd.append('file', file);
      const resultDiv = document.getElementById('resume-upload-result');
      resultDiv.innerHTML = '<div class="alert alert-info"><span class="spinner"></span> Parsing resume...</div>';
      
      try {
        const r = await fetch('/api/parse-resume', { method: 'POST', body: fd });
        const d = await r.json();
        if (d.success) {
          resultDiv.innerHTML = '<div class="alert alert-success">✅ Resume parsed successfully!</div>';
          loadProfile();
          setTimeout(() => loadStats(), 1000);
        } else {
          resultDiv.innerHTML = '<div class="alert alert-error">❌ ' + escapeHtml(d.detail || JSON.stringify(d)) + '</div>';
        }
      } catch (e) {
        resultDiv.innerHTML = '<div class="alert alert-error">❌ Error: ' + escapeHtml(e.message) + '</div>';
      }
    }

    // Load profile
    async function loadProfile() {
      try {
        const r = await fetch('/api/profile');
        const d = await r.json();
        if (!d.profile) {
          document.getElementById('profile-display').innerHTML = '<div class="alert alert-info">No resume uploaded yet. Upload a PDF or DOCX file above.</div>';
          return;
        }
        const p = d.profile;
        let html = `
          <div class="profile-item">
            <div class="profile-label">Name</div>
            <div class="profile-value">${escapeHtml(p.name || 'N/A')}</div>
          </div>
          <div class="profile-item">
            <div class="profile-label">Email</div>
            <div class="profile-value">${escapeHtml(p.email || 'N/A')}</div>
          </div>
          <div class="profile-item">
            <div class="profile-label">Phone</div>
            <div class="profile-value">${escapeHtml(p.phone || 'N/A')}</div>
          </div>
          <div class="profile-item">
            <div class="profile-label">Location</div>
            <div class="profile-value">${escapeHtml(p.location || 'N/A')}</div>
          </div>
          <div class="profile-item">
            <div class="profile-label">Experience</div>
            <div class="profile-value">${escapeHtml(p.total_experience_years || 0)} years</div>
          </div>
          <div class="profile-item">
            <div class="profile-label">Skills (${(p.skills || []).length})</div>
            <div class="skill-list">
              ${(p.skills || []).slice(0, 15).map(s => `<span class="skill-tag">${escapeHtml(s)}</span>`).join('')}
              ${(p.skills || []).length > 15 ? `<span class="skill-tag">+${(p.skills || []).length - 15} more</span>` : ''}
            </div>
          </div>
        `;
        document.getElementById('profile-display').innerHTML = html;
      } catch (e) {
        document.getElementById('profile-display').innerHTML = '<div class="alert alert-error">Error loading profile</div>';
      }
    }

    // Load jobs
    async function loadJobs() {
      try {
        const applied = currentFilter === 'applied' ? true : currentFilter === 'pending' ? false : null;
        const url = '/api/jobs?limit=100' + (applied !== null ? '&applied=' + applied : '');
        const r = await fetch(url);
        const d = await r.json();
        if (!d.jobs || d.jobs.length === 0) {
          document.getElementById('jobs-list').innerHTML = '<div class="alert alert-info">No jobs found. Run the job scraper to fetch listings.</div>';
          return;
        }
        document.getElementById('jobs-list').innerHTML = d.jobs.map(j => {
          const jobUrl = safeHttpUrl(j.url);
          const emailHref = j.contact_email ? `mailto:${encodeURIComponent(j.contact_email)}` : '';
          return `
            <div class="job-item">
              <div class="job-title">${escapeHtml(j.title || 'Untitled')}</div>
              <div class="job-company">${escapeHtml(j.company || 'Unknown company')}</div>
              <div class="job-meta">
                <span class="badge">${escapeHtml(j.source || 'unknown')}</span>
                <span class="badge">${escapeHtml(j.apply_method || 'email')}</span>
                <span class="badge ${j.applied ? 'badge-success' : 'badge-pending'}">${escapeHtml(j.status || 'pending')}</span>
              </div>
              <div class="job-actions">
                ${jobUrl ? `<a href="${escapeHtml(jobUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-small">View Job</a>` : ''}
                ${emailHref ? `<a href="${escapeHtml(emailHref)}" class="btn btn-small btn-secondary">Email</a>` : ''}
              </div>
            </div>
          `;
        }).join('');
      } catch (e) {
        document.getElementById('jobs-list').innerHTML = '<div class="alert alert-error">Error loading jobs</div>';
      }
    }

    // Load recent jobs for dashboard
    async function loadRecentJobs() {
      try {
        const r = await fetch('/api/jobs?applied=true&limit=5');
        const d = await r.json();
        if (!d.jobs || d.jobs.length === 0) {
          document.getElementById('recent-jobs').innerHTML = '<div class="alert alert-info">No applications yet. Run a job application cycle to get started.</div>';
          return;
        }
        document.getElementById('recent-jobs').innerHTML = d.jobs.map(j => `
          <div class="job-item">
            <div class="job-title">${escapeHtml(j.title || 'Untitled')}</div>
            <div class="job-company">${escapeHtml(j.company || 'Unknown company')}</div>
            <div class="job-meta"><span class="badge">${escapeHtml(j.source || 'unknown')}</span> <span class="badge">${escapeHtml(j.status || 'pending')}</span></div>
          </div>
        `).join('');
      } catch (e) {
        console.error('Error loading recent jobs:', e);
      }
    }

    // Filter jobs
    function filterJobs(filter) {
      currentFilter = filter;
      loadJobs();
    }

    // Manual run
    async function manualRun(emailOnly) {
      const r = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_only: emailOnly, limit: 50 })
      });
      const d = await r.json();
      document.getElementById('run-status').innerHTML = '<div class="alert alert-success">✅ ' + escapeHtml(d.message) + '</div>';
      setTimeout(() => loadStats(), 3000);
      setTimeout(() => loadRecentJobs(), 5000);
    }

    // Custom run
    async function customRun(emailOnly) {
      const limit = parseInt(document.getElementById('jobLimit').value) || 50;
      const r = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_only: emailOnly, limit })
      });
      const d = await r.json();
      document.getElementById('custom-run-result').innerHTML = '<div class="alert alert-success">✅ ' + escapeHtml(d.message) + ' (Limit: ' + limit + ')</div>';
    }

    // Test email
    async function testEmailConfig(btn) {
      if (!btn) return;
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.innerHTML = '<span class="spinner" style="display: inline-block;"></span> Testing...';
      
      try {
        const r = await fetch('/api/test-email', { method: 'POST' });
        const d = await r.json();
        if (d.success) {
          showAlert('✅ Test email sent! Check your inbox in 30 seconds.', 'success');
        } else {
          showAlert('❌ ' + d.message, 'error');
        }
      } catch (e) {
        showAlert('❌ Error: ' + e.message, 'error');
      }
      
      btn.disabled = false;
      btn.textContent = originalText;
    }

    // Show alert
    function showAlert(msg, type) {
      const div = document.createElement('div');
      div.className = 'alert alert-' + type;
      div.textContent = msg;
      document.body.insertBefore(div, document.body.firstChild);
      setTimeout(() => div.remove(), 5000);
    }

    // Init
    loadStats();
    loadDetailedStats();
    loadRecentJobs();
    setInterval(loadStats, 30000);
    setInterval(loadDetailedStats, 60000);
    setInterval(loadRecentJobs, 60000);
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
