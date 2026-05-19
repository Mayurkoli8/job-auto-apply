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
- **Instance Type:** Free Tier (or upgrade as needed)

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

### Option A: Persistent Storage (Recommended)
1. In Render dashboard, go to "Disks"
2. Create a new disk:
   - **Mount Path:** `/app/data`
   - **Size:** 1 GB (free tier)
3. Also create for uploads:
   - **Mount Path:** `/app/uploads`
   - **Size:** 1 GB (free tier)

### Option B: External Database (PostgreSQL)
If you need a database that persists across deployments:
1. Create a new PostgreSQL database on Render
2. Add `DATABASE_URL=postgresql://user:pass@host/db` to environment

## Step 6: Upload Resume

1. Wait for first deployment to complete
2. The app will create the `uploads/` folder
3. Manual upload:
   - SSH into Render service OR
   - Use API endpoint if you add file upload capability

## Step 7: Deploy

1. Click "Create Web Service"
2. Render will start building and deploying
3. Monitor logs in the Render dashboard
4. Check deployment status

## Troubleshooting

### Build fails with Playwright issues
- Ensure `playwright install chromium` is in build command
- On Render, it automatically handles Linux dependencies

### Environment variables not loading
- In `config.py`, ensure you're using `pydantic-settings` to load from Render env
- Render passes env vars directly, no need for `.env` file

### Database not persisting
- Use mounted disks (not SQLite on ephemeral instance)
- Or switch to Render's PostgreSQL

### Scheduler not running at scheduled time
- Render free tier instances may spin down
- Consider adding a cron endpoint to trigger manually or upgrade instance

### Large dependencies fail
- Free tier has limited build time (15 min)
- If build fails, upgrade to standard tier

## Monitoring

1. Go to **Logs** tab in Render to see real-time output
2. Check **Metrics** for CPU/memory usage
3. Set up **Notifications** for deployment failures

## Cost
- **Free tier:** Always free (instance may spin down with inactivity)
- **Standard tier:** ~$7/month (keeps instance always running)
- **Disk storage:** $0.30/GB/month

## Next Steps

After deployment, consider:
1. ✅ Manually upload your resume to `uploads/resume.pdf`
2. ✅ Test the application with a few job searches
3. ✅ Set up email notifications for successful applications
4. ✅ Monitor logs for any errors
5. ✅ Upgrade to Standard tier if you want guaranteed uptime
