# Handoff Notes for Codex — Job Auto-Apply Project

## Current Status (Commit: d7eef1c)

### ✅ Completed
- **Resume Parsing**: Robust Gemini + fallback system with progressive JSON sanitizer
- **Job Scraping**: 7 sources, keyword filtering, scoring, deduplication with drop tracking
- **Database**: SQLAlchemy async models with helper functions (get_pending_jobs)
- **Email Generation**: Gemini-powered with anti-AI-detection techniques
- **Email Finder**: Hunter.io + domain scraping + generic pattern fallback
- **API Endpoints**: /api/health, /api/ping, /api/stats, /api/jobs, /api/profile, /api/parse-resume, /api/run, /api/test-email, /api/stats-detailed (NEW)
- **Deployment**: Docker + Render ready
- **Pending Job Retry**: Added logic to retry unapplied jobs on subsequent runs
- **Gemini Quota Fallback**: Template-based email system (falls back when 429 quota exceeded)
- **SendGrid Email Integration** (NEW): Email delivery via SendGrid API (recommended for Render) with Gmail SMTP fallback
- **Stats Visualization Dashboard** (NEW): Graphify-based analytics with timeline, distribution, source breakdown

### 🔴 Known Blockers (Reduced)
1. ~~**Gemini Free Tier (20 req/day limit)**~~ → SOLVED: Template fallback system in place
   - Emails still use Gemini for personalization when quota available
   - Falls back to simple templates when 429 error detected
   
2. ~~**Gmail SMTP Unreachable from Render**~~ → SOLVED: SendGrid integration added
   - SendGrid is primary email method (free tier: 100/day, no SMTP restrictions)
   - Configure with `SENDGRID_API_KEY` environment variable
   - Gmail SMTP still available as fallback if SendGrid not configured
   - **Recommended**: Use SendGrid on Render (set SENDGRID_API_KEY in .env or Render dashboard)

3. **LinkedIn Playwright Scraping** (Minor)
   - Browser binaries not installed on Render
   - Fix: Add `RUN python -m playwright install --with-deps` to Dockerfile

## Current Status (Commit: d7eef1c)

### ✅ NEWLY COMPLETED
- **SendGrid Email Integration** (d7eef1c): 
  - Primary email delivery method (no SMTP restrictions on Render)
  - Automatic fallback to Gmail if SendGrid fails/unconfigured
  - Solves "Network is unreachable" issue on Render free tier
  - Free tier: 100 emails/day, paid: ~$20/mo for unlimited
  
- **Stats Visualization Dashboard** (d7eef1c):
  - New `/api/stats-detailed` endpoint returns JSON for visualization
  - Includes: jobs by source, applications timeline (30 days), match score distribution
  - Ready for Graphify dashboard integration
  - Data structure: timeline (date → count), distribution (score ranges → count), source breakdown

### ✅ Completed (Previous)
- **Resume Parsing**: Robust Gemini + fallback system with progressive JSON sanitizer
- **Job Scraping**: 7 sources, keyword filtering, scoring, deduplication with drop tracking
- **Database**: SQLAlchemy async models with helper functions (get_pending_jobs)
- **Email Generation**: Gemini-powered with anti-AI-detection techniques
- **Email Finder**: Hunter.io + domain scraping + generic pattern fallback
- **API Endpoints**: Full REST API with health checks and stats
- **Deployment**: Docker + Render ready
- **Pending Job Retry**: Retry mechanism for unapplied jobs
- **Gemini Quota Fallback**: Template-based email system

### 📊 Recent Changes
- **email_generator.py**: All generate_*() functions now wrap Gemini calls with try-except fallback
- **requirements.txt**: Added `graphify` for visualization

### 🚀 Next Steps (Priority Order)

1. **HIGH - Configure SendGrid for Email Delivery** (NEW PRIORITY)
   - Create SendGrid account at sendgrid.com (free tier: 100 emails/day)
   - Get API key from Settings → API Keys
   - Set `SENDGRID_API_KEY=...` in Render environment variables
   - Test with `curl -X POST http://localhost:8000/api/test-email`
   - Once SendGrid configured, emails will send successfully

2. **HIGH - Playwright Installation** (Improves job diversity)
   - Add to Dockerfile: `RUN python -m playwright install --with-deps`
   - Test LinkedIn scraping on Render

3. **MEDIUM - Build Frontend Dashboard** (Using visualization data)
   - Consume `/api/stats-detailed` endpoint
   - Display charts: timeline, source breakdown, match score distribution
   - Graphify already installed and visualization functions ready

4. **MEDIUM - Form Filling** (Complex, requires testing)
   - Currently has placeholder code in form_filler.py
   - Requires LinkedIn login or public ATS URLs with known systems
   - Low priority unless form applications needed
### 🔧 Local Testing Commands
```bash
# Activate venv
.\.venv\Scripts\Activate.ps1

# Run daily pipeline (scrape + apply)
python main.py

# Test resume upload endpoint
curl -X POST http://localhost:8000/api/parse-resume -F "resume=@your_resume.pdf"

# Check stats
curl http://localhost:8000/api/stats

# Check detailed stats with visualization data
curl http://localhost:8000/api/stats-detailed

# Manual trigger full pipeline
curl -X POST http://localhost:8000/api/run

# Test email sending (currently blocked by SMTP - fix with SendGrid)
curl -X POST http://localhost:8000/api/test-email
```

### 📊 New Visualization Endpoint
**GET /api/stats-detailed** returns:
```json
{
  "generated_at": "2025-05-23T...",
  "summary": {
    "total_jobs": 49,
    "applied": 0,
    "pending": 49,
    "average_match_score": 0.108,
    "success_rate_percent": 0.0,
    "by_source": {"RemoteOK": 15, "Remotive": 12, ...}
  },
  "timeline_30_days": {"2025-05-20": 5, "2025-05-21": 0, ...},
  "match_score_distribution": {
    "0.0-0.2": 42,
    "0.2-0.4": 5,
    "0.4-0.6": 2,
    "0.6-0.8": 0,
    "0.8-1.0": 0
  }
}
```

### 📁 Key Files
- **main.py**: FastAPI app + APScheduler (runs daily at 9 AM)
- **orchestrator.py**: Coordinates scrape → email/form pipeline
- **email_generator.py**: Gemini + template fallback (MODIFIED)
- **email_sender.py**: Gmail SMTP wrapper (needs SMTP fix)
- **email_finder.py**: Contact discovery
- **job_scraper.py**: Multi-source job aggregation
- **resume_parser.py**: PDF/DOCX → structured profile
- **database.py**: SQLAlchemy models
- **config.py**: Environment variables + validation

### 🔑 Environment Variables
Ensure `.env` has (for local testing):
```
# Email (choose SendGrid OR Gmail, or both for redundancy)
SENDGRID_API_KEY=SG.xxxxxxxxxxxx (recommended for Render, free tier: 100/day)
GMAIL_ADDRESS=your-email@gmail.com (Gmail SMTP fallback)
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx (Gmail app password, no spaces in env)

# AI & APIs
GEMINI_API_KEY=AIzaSy... (free tier: 20 req/day, falls back to templates)
HUNTER_API_KEY=... (optional, for email discovery)

# User Profile
USER_FULL_NAME=Your Name
USER_EMAIL=your-email@example.com
JOB_TITLES=["AI Engineer", "ML Engineer", "Software Engineer"]
JOB_KEYWORDS=["Python", "Machine Learning", "LLM"]
USER_LINKEDIN=https://linkedin.com/in/yourprofile
USER_GITHUB=https://github.com/yourprofile
```

**For Render Deployment:**
1. Create SendGrid account, get API key
2. In Render dashboard → Environment → Add `SENDGRID_API_KEY`
3. No Gmail needed on Render (uses SendGrid by default)

**Email Priority Order:**
- SendGrid (if `SENDGRID_API_KEY` set) → best for Render
- Gmail SMTP (if `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` set) → fallback
- Template emails (no API needed) → fallback if both fail

### 🎯 Render Deployment
- **Current Issues**: SMTP unreachable, Playwright not installed
- **Solutions**: See "URGENT" and "HIGH" sections above
- **Environment**: Render free tier, ephemeral `/tmp` storage, auto-detected PORT

### 💡 Tips for Continuation
1. Focus on **email delivery** first — currently biggest blocker (0% emails sent)
2. Test SMTP integration locally before pushing to Render
3. Use `/api/run` to trigger full pipeline; check Render logs for real-time output
4. Fallback template system means app won't completely fail after 20 Gemini calls — it degrades gracefully
5. Pending job retry is already implemented — app retries unapplied jobs on next run

---
Ready for Codex to continue. Good luck! 🚀
