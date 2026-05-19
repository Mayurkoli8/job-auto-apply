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

### 5. Add Persistent Storage ⚠️ Free Tier Note
**Free tier does NOT include persistent disks.** Choose one:

**Option A: Free + Ephemeral (Testing)**
- Skip this step
- Data will reset on restart
- Resume must be re-uploaded each time
- Good for: Testing, low volume

**Option B: Add PostgreSQL Database**
- Go to Render dashboard → Create PostgreSQL
- Note the connection string
- Add to Environment: `DATABASE_URL=postgresql://...`
- Cost: ~$15/month

**Option C: Skip Storage (Use Default SQLite)**
- Data stored in ephemeral storage
- Will reset on restart
- Fine for occasional testing

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

## Important Notes

✅ **What's Done:**
- `render.yaml` configured with correct build & start commands
- `main.py` updated to use `PORT` environment variable
- All dependencies listed in `requirements.txt`

⚠️ **Free Tier Limitations:**
- ❌ No persistent storage (data resets on restart)
- ❌ Instance spins down after 15 min inactivity
- ❌ Scheduler won't run reliably
- ✅ **Good for:** Testing, manual runs only
- ✅ **For Production:** Upgrade to Standard tier (~$7/mo) + PostgreSQL (~$15/mo)

📝 **What to Expect:**
- Resume file disappears after restart (re-upload via dashboard)
- Application history lost on restart
- Scheduler won't trigger automatically unless instance is awake
- Run manually via dashboard for testing

## Monitoring

- **Logs:** View in Render dashboard → Logs tab
- **Health Check:** Visit `/api/health` endpoint
- **Stats:** Visit `/api/stats` endpoint

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Data lost after restart | Normal on free tier - use Standard tier for persistence |
| Resume disappeared | Free tier storage is ephemeral - re-upload before each run |
| Scheduler doesn't run | Free tier instance sleeps after 15 min - upgrade to Standard or run manually |
| Build fails | Check Render logs. Try clearing build cache in settings. |
| App crashes after deploy | Check environment variables are set correctly |
| Scheduler doesn't trigger at 8 AM | Free tier needs manual trigger or Standard tier upgrade |

## API Endpoints
- `GET /` - Dashboard
- `POST /api/parse-resume` - Upload resume
- `POST /api/run?email_only=true` - Run job search
- `GET /api/jobs` - View all applications
- `GET /api/stats` - Statistics
- `GET /api/health` - Health check
