# Deployment Guide: Render.com

## Step 1: Prepare Your Repository

1. Ensure your repo is pushed to GitHub
2. The `render.yaml` file is already included in this repo

## Step 2: Connect to Render

1. Go to [render.com](https://render.com) and sign up (free tier available)
2. Click "New +" → "Web Service"
3. Select "Build and deploy from a Git repository"
4. Connect your GitHub account and select this repo
5. Click "Connect"

## Step 3: Configure Deployment Settings

### Basic Settings
- **Name:** `job-auto-apply`
- **Runtime:** Python
- **Build Command:** `pip install -r requirements.txt && playwright install chromium && playwright install-deps chromium && mkdir -p uploads data logs`
- **Start Command:** `python main.py`
- **Branch:** main (or your default branch)
- **Region:** Choose the closest to you

### Advanced Settings
- **Auto Deploy:** Enable (redeploy on git push)
- **Instance Type:** Free Tier ✅
- **Database:** See Step 5 for options

## Step 4: Add Environment Variables

In Render dashboard, go to Environment and add ALL variables from `.env.example`:

**REQUIRED:**
```
GEMINI_API_KEY=your_gemini_api_key
GMAIL_ADDRESS=your_email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
USER_FULL_NAME=Your Name
USER_EMAIL=your@email.com
USER_PHONE=+1-555-000-0000
USER_LOCATION=Your Location
RESUME_PATH=uploads/resume.pdf
```

**JOB PREFERENCES:**
```
JOB_TITLES=["Software Engineer","Backend Developer"]
JOB_KEYWORDS=["Python","FastAPI"]
JOB_LOCATION=Remote
EXPERIENCE_LEVEL=mid-level
MIN_SALARY=80000
DAILY_LIMIT=50
```

**SCHEDULING:**
```
RUN_HOUR=8
RUN_MINUTE=0
TIMEZONE=America/New_York
MIN_DELAY_SECONDS=3
MAX_DELAY_SECONDS=12
```

**DATABASE (optional if using SQLite):**
```
DATABASE_URL=sqlite:///./job_applications.db
```

## Step 5: Handle File Uploads & Database

### ⚠️ Free Tier Limitation
**Render free tier does NOT include persistent storage.** Data will be lost when the instance restarts or redeploys.

### Option A: SQLite (Free, ephemeral)
- Uses SQLite in-memory/local storage
- ✅ Works on free tier
- ⚠️ Data lost on restart/redeploy
- Good for: Testing, development, low volume
- Set: `DATABASE_URL=sqlite:///./job_applications.db`

### Option B: PostgreSQL on Render (Recommended for Production)
1. Go to Render dashboard → Create new PostgreSQL database
2. Note the database connection string
3. Add to environment: `DATABASE_URL=postgresql://user:pass@...`
4. Cost: ~$15-50/month depending on usage

### Option C: External Storage (S3, GitHub, etc.)
For resume files and backups:
- **AWS S3** (~$0.023/GB): Store resumes, backups
- **GitHub** (Free): Commit results to private repo
- **MongoDB Atlas** (Free tier 512MB): Store job data

For free tier: Just upload resume manually each session.

## Step 6: Upload Resume & Test

1. Wait for first deployment to complete
2. Visit your app URL (e.g., `https://job-auto-apply.onrender.com`)
3. Click "Upload Resume" and select your resume file
4. **Important:** Upload it again after each restart/redeploy (free tier limitation)

**For Persistent Resume:** If using Option B/C, configure S3 or GitHub to auto-backup

## Step 7: Deploy

1. Click "Create Web Service"
2. Render will start building and deploying
3. Monitor logs in the Render dashboard
4. Check deployment status

## Troubleshooting

### Build fails with Playwright issues
- Ensure `playwright install chromium` is in build command ✓
- On Render, it automatically handles Linux dependencies

### Environment variables not loading
- In `config.py`, ensure you're using `pydantic-settings` to load from Render env
- Render passes env vars directly, no need for `.env` file

### Data lost after restart/redeploy
- **This is normal on free tier** — use SQLite but expect data to reset
- For persistence: Upgrade to Standard tier or use external database (PostgreSQL)

### Scheduler doesn't run at scheduled time
- **Free tier instances spin down after 15 min inactivity**
- Scheduler won't wake the instance automatically
- Solutions:
  1. **Upgrade to Standard tier** (~$7/month) — instance always on
  2. **Add a cron trigger** via external service (Uptime Robot, AWS Lambda)
  3. **Manual runs only** — use dashboard buttons to run on demand

### Resume file disappears after restart
- **Free tier has ephemeral storage** — all local files are lost
- Solution: Upload resume again OR use external storage (S3, GitHub)

### Large dependencies fail during build
- Free tier has 15 min build time limit
- If build fails: Reduce dependencies or upgrade to Standard tier

## Monitoring

1. Go to **Logs** tab in Render to see real-time output
2. Check **Metrics** for CPU/memory usage
3. Set up **Notifications** for deployment failures

## Cost & Free Tier Limits

| Tier | Price | Storage | Scheduler | Auto-wake | Best For |
|------|-------|---------|-----------|-----------|----------|
| **Free** | $0 | None (ephemeral) | No | No | Testing, dev, manual runs |
| **Standard** | ~$7/mo | — | ✅ Works | ✅ 24/7 on | Production, automated jobs |

**Free tier details:**
- Instance spins down after 15 min inactivity
- All data lost on restart
- Great for testing, but not for production automation
- Scheduler won't work reliably

**Recommended for production:** Upgrade to Standard ($7/month) + PostgreSQL ($15/month)

## Next Steps

### ✅ Free Tier (Testing):
1. Upload your resume to `uploads/resume.pdf` via dashboard
2. Click "Email Only" to test (faster than full run)
3. Check logs for any errors
4. Run full pipeline if test succeeds
5. Data will reset on instance restart — that's expected

### 🚀 Production Setup (Recommended):
1. Upgrade to **Standard tier** (~$7/month)
2. Add **PostgreSQL** database (~$15/month)
3. Configure scheduler — will run reliably at 8 AM
4. Set up email notifications for successful applications
5. Monitor logs for errors
6. Data persists across restarts ✓

### 💾 Storage Options:
- **Free + Persistence:** Add external DB (PostgreSQL, MongoDB Atlas free tier)
- **Free + Manual:** Commit results to GitHub after each run
- **Free + S3:** Store resume & backups in AWS S3 (~$1/month)
