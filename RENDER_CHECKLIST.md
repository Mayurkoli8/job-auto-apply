# 🚀 Render Deployment Checklist

## Pre-Deployment (Local)
- [ ] Commit and push your code to GitHub
  ```bash
  git add .
  git commit -m "Add Render deployment config"
  git push
  ```

## Deployment Steps

### 1. Create Render Account
- [ ] Go to [render.com](https://render.com)
- [ ] Sign up with GitHub

### 2. Create Web Service
- [ ] Click "New +" → "Web Service"
- [ ] Select your `job-auto-apply` repository
- [ ] Click "Connect"

### 3. Configure Service
- [ ] **Name:** `job-auto-apply`
- [ ] **Runtime:** Python
- [ ] **Branch:** main
- [ ] **Build Command:** Should auto-populate from `render.yaml` ✓
- [ ] **Start Command:** Should auto-populate from `render.yaml` ✓
- [ ] **Region:** Choose closest to you
- [ ] **Auto Deploy:** Enable

### 4. Add Environment Variables ⚠️ REQUIRED
Go to **Environment** tab and add these:

**AI & Email (REQUIRED):**
```
GEMINI_API_KEY = AIzaSy...                    (from aistudio.google.com/app/apikey)
GMAIL_ADDRESS = your_email@gmail.com
GMAIL_APP_PASSWORD = xxxx-xxxx-xxxx-xxxx     (from myaccount.google.com/apppasswords)
```

**User Profile (REQUIRED):**
```
USER_FULL_NAME = Your Name
USER_EMAIL = your_email@gmail.com
USER_PHONE = +1-555-0000
USER_LOCATION = Your City, Country
RESUME_PATH = uploads/resume.pdf
```

**Job Preferences:**
```
JOB_TITLES = ["Software Engineer","Backend Developer"]
JOB_KEYWORDS = ["Python","FastAPI"]
JOB_LOCATION = Remote
EXPERIENCE_LEVEL = mid-level
MIN_SALARY = 80000
DAILY_LIMIT = 50
```

**Scheduling:**
```
RUN_HOUR = 8
RUN_MINUTE = 0
TIMEZONE = America/New_York
MIN_DELAY_SECONDS = 3
MAX_DELAY_SECONDS = 12
```

### 5. Add Persistent Storage (for Database & Resume)
- [ ] Go to **Disks** tab
- [ ] Create new disk:
  - **Mount Path:** `/app/data`
  - **Size:** 1 GB
- [ ] Create another disk:
  - **Mount Path:** `/app/uploads`
  - **Size:** 1 GB

### 6. Deploy
- [ ] Click "Create Web Service"
- [ ] Wait for build to complete (~3-5 minutes)
- [ ] Check **Logs** tab for any errors
- [ ] Once deployed, visit your service URL (e.g., `https://job-auto-apply.onrender.com`)

### 7. Post-Deployment
- [ ] Visit your app's dashboard at `https://your-app.onrender.com`
- [ ] Click "Upload Resume" and add your resume file
- [ ] Test with "Email Only" first to verify configuration
- [ ] If successful, try "Full Run" or wait for scheduled time

## Important Notes

✅ **What's Done:**
- `render.yaml` configured with correct build & start commands
- `main.py` updated to use `PORT` environment variable
- All dependencies listed in `requirements.txt`

⚠️ **Important:**
- Free tier instances may sleep after 15 minutes of inactivity
- For production, upgrade to **Standard tier** (~$7/month)
- Scheduler will pause if instance is asleep
- Resume file must be uploaded manually after first deployment

## Monitoring

- **Logs:** View in Render dashboard → Logs tab
- **Health Check:** Visit `/api/health` endpoint
- **Stats:** Visit `/api/stats` endpoint

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Build fails | Check Render logs - likely Playwright issue. Contact support if needed. |
| App crashes after deploy | Check environment variables are set correctly |
| Scheduler doesn't run | Free tier may auto-sleep. Upgrade to Standard tier or check logs. |
| Resume upload fails | Ensure `/app/uploads` disk is mounted |
| Database not persisting | Ensure `/app/data` disk is mounted |

## API Endpoints
- `GET /` - Dashboard
- `POST /api/parse-resume` - Upload resume
- `POST /api/run?email_only=true` - Run job search
- `GET /api/jobs` - View all applications
- `GET /api/stats` - Statistics
- `GET /api/health` - Health check
