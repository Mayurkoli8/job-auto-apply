# Handoff Notes for Codex — Job Auto-Apply Project

## Current Status (Commit: e2daa2c)

### ✅ Completed
- **Resume Parsing**: Robust Gemini + fallback system with progressive JSON sanitizer
- **Job Scraping**: 7 sources, keyword filtering, scoring, deduplication with drop tracking
- **Database**: SQLAlchemy async models with helper functions (get_pending_jobs)
- **Email Generation**: Gemini-powered with anti-AI-detection techniques
- **Email Finder**: Hunter.io + domain scraping + generic pattern fallback
- **API Endpoints**: /api/health, /api/ping, /api/stats, /api/jobs, /api/profile, /api/parse-resume, /api/run, /api/test-email
- **Deployment**: Docker + Render ready
- **Pending Job Retry**: Added logic to retry unapplied jobs on subsequent runs
- **Gemini Quota Fallback**: Added template-based email system (NEW) — falls back when Gemini 429 quota exceeded

### 🔴 Known Blockers
1. **Gemini Free Tier (20 req/day limit)**
   - Emails hit quota after ~5-6 personalized generations
   - **Solution implemented**: `_template_cold_email()` fallback takes over when 429 error detected
   - Templates use job title, company, candidate skills — simple but functional

2. **Gmail SMTP Unreachable from Render**
   - `OSError(101, 'Network is unreachable')` when sending from Render free tier
   - Render blocks outbound SMTP on free tier
   - **Options**:
     - Use email relay service (SendGrid, Mailgun, etc.)
     - Switch to SendGrid/Mailgun SMTP (requires API key, ~$10-20/mo)
     - Implement in-app email queue for manual review
     - Use Render Pro tier

3. **LinkedIn Playwright Scraping** (Minor)
   - Browser binaries not installed on Render
   - Fix: Add `RUN python -m playwright install --with-deps` to Dockerfile

### 📊 Recent Changes
- **email_generator.py**: All generate_*() functions now wrap Gemini calls with try-except fallback
- **requirements.txt**: Added `graphify` for visualization

### 🚀 Next Steps (Priority Order)

1. **URGENT - Fix Email Delivery** (Currently 0% emails sent)
   - Implement SendGrid or Mailgun SMTP integration
   - Or use email relay service
   - Test with `/api/test-email` endpoint

2. **HIGH - Playwright Installation** (Improves job diversity)
   - Add to Dockerfile: `RUN python -m playwright install --with-deps`
   - Test LinkedIn scraping on Render

3. **MEDIUM - Visualization/Dashboard** (Optional, using graphify)
   - Create charts for job application stats over time
   - Success rates by source, company, etc.

4. **MEDIUM - Form Filling** (Complex, requires testing)
   - Currently has placeholder code in form_filler.py
   - Requires LinkedIn login or public ATS URLs with known systems
   - Low priority unless needed

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

# Manual trigger full pipeline
curl -X POST http://localhost:8000/api/run

# Test email sending (currently blocked by SMTP)
curl -X POST http://localhost:8000/api/test-email
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
Ensure `.env` has:
- `GEMINI_API_KEY` (free tier: 20 req/day, 1.5-flash model)
- `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` (Gmail SMTP, currently blocked)
- `USER_FULL_NAME`, `USER_EMAIL`, `JOB_TITLES`, `JOB_KEYWORDS`, etc.
- Optional: `HUNTER_API_KEY` (for email discovery)

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
