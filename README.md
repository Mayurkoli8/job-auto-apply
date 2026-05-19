# ⚡ Job Auto-Apply Platform

Automated job application platform that:
- Parses your resume with AI
- Scrapes 7 job sources daily (RemoteOK, Remotive, WeWorkRemotely, The Muse, Adzuna, Indeed, LinkedIn)
- Finds HR email contacts for each company
- Sends personalized, human-sounding cold emails with your resume attached
- Fills job application forms automatically (Greenhouse, Lever, Workday, generic)
- Tracks every application in a database
- Runs every morning at 8 AM automatically

---

## 📋 Prerequisites

- Python 3.11+ **or** Docker
- Gmail account with [App Password](https://myaccount.google.com/apppasswords) enabled
- [Google Gemini API key](https://aistudio.google.com/app/apikey) (completely FREE — 1500 req/day)

---

## 🚀 Quick Start (Local — 5 minutes)

### 1. Clone & Install

```bash
git clone <this-repo>
cd job-auto-apply
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium  # Linux only
```

### 2. Configure

```bash
cp .env.example .env
nano .env   # or open in any editor
```

Fill in at minimum:
```env
GEMINI_API_KEY=AIzaSy...
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
USER_FULL_NAME=Your Name
USER_EMAIL=you@gmail.com
JOB_TITLES=["Software Engineer", "Backend Developer"]
JOB_KEYWORDS=["Python", "FastAPI", "React"]
```

### 3. Add Your Resume

Copy your resume to the project folder:
```bash
cp ~/Downloads/resume.pdf uploads/resume.pdf
```

### 4. Parse Resume

```bash
python main.py --parse-resume
```

### 5. Test Email Config

```bash
python main.py --test-email
```

### 6. Run Manually

```bash
python main.py --run           # full run (email + forms)
python main.py --email-only    # cold email only (faster)
```

### 7. Start the Server (with daily automation)

```bash
python main.py
```

Open http://localhost:8000 to see the dashboard.

---

## 🐳 Docker (Recommended)

```bash
cp .env.example .env
# Edit .env with your credentials
cp ~/Downloads/resume.pdf uploads/resume.pdf

docker-compose up -d
```

The app runs at http://localhost:8000 and applies to jobs every morning at 8 AM.

---

## ☁️ Cloud Deployment (Free)

### Option A: Railway (Recommended — 500 hrs/month free)

1. Install Railway CLI: `npm install -g @railway/cli`
2. `railway login`
3. `railway init` (in project folder)
4. `railway up`
5. Set environment variables in Railway dashboard → Variables

Or deploy via GitHub:
1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add all `.env` variables in the Railway dashboard
4. Done — it auto-deploys on every push

### Option B: Render (Free tier — 750 hrs/month)

1. Push to GitHub
2. [render.com](https://render.com) → New Web Service → Connect repo
3. Build command: `pip install -r requirements.txt && playwright install chromium`
4. Start command: `python main.py`
5. Add environment variables in Render dashboard
6. **Note**: Render's free tier sleeps after 15 min inactivity — use a cron job
   (e.g. [cron-job.org](https://cron-job.org)) to ping `/api/health` every 10 min

### Option C: Local with always-on (using `screen` or `pm2`)

```bash
# Using screen
screen -S jobapply
python main.py
# Ctrl+A D to detach

# Using pm2
npm install -g pm2
pm2 start "python main.py" --name job-apply
pm2 startup
pm2 save
```

---

## ⚙️ Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Claude API key |
| `GMAIL_ADDRESS` | ✅ | — | Your Gmail address |
| `GMAIL_APP_PASSWORD` | ✅ | — | Gmail App Password (not your real password) |
| `USER_FULL_NAME` | ✅ | — | Your full name |
| `USER_EMAIL` | ✅ | — | Email shown in applications |
| `JOB_TITLES` | ✅ | — | JSON array of job titles to search |
| `JOB_KEYWORDS` | ✅ | — | JSON array of skills/keywords |
| `DAILY_LIMIT` | — | 50 | Max applications per day |
| `RUN_HOUR` | — | 8 | Hour to run daily (24h format) |
| `TIMEZONE` | — | America/New_York | Your timezone |
| `HUNTER_API_KEY` | — | — | Hunter.io key (25 free/month) |
| `ADZUNA_APP_ID/KEY` | — | — | Adzuna free API (register at app.adzuna.com) |
| `TWOCAPTCHA_API_KEY` | — | — | 2captcha for CAPTCHA solving ($1/1000) |

---

## 📊 Free API Keys to Get

| Service | What it does | Free limit | Get it |
|---------|-------------|------------|--------|
| [Hunter.io](https://hunter.io) | Find HR emails by company domain | 25/month | hunter.io/users/sign_up |
| [Adzuna](https://developer.adzuna.com) | More job listings | 250 req/day | developer.adzuna.com |
| [The Muse](https://www.themuse.com/developers/api/v2) | Startup jobs | Unlimited (key optional) | themuse.com |
| [2captcha](https://2captcha.com) | Solve CAPTCHAs on form fills | $1/1000 solves | 2captcha.com |

---

## 🎯 How It Works

### Email Strategy (PRIMARY — most effective)

1. Scrapes job listing
2. Finds HR contact email (Hunter.io → website scrape → pattern guess)
3. Generates a personalized cold email using Claude with anti-AI techniques
4. Attaches resume as PDF
5. Sends via Gmail SMTP
6. Logs in database

### Form Fill Strategy (SECONDARY — for ATS jobs)

1. Detects ATS type (Greenhouse, Lever, Workday, etc.)
2. Uses Playwright to navigate to the apply page
3. Screenshots the form → sends to Claude → gets field mappings
4. Fills each field with human-like typing speed/delays
5. Uploads resume file
6. Submits form
7. Solves CAPTCHAs via 2captcha if configured

---

## 🛡️ Anti-AI Detection (Cover Letters & Emails)

The AI generator uses these techniques to produce human-sounding writing:

- **Varied sentence lengths**: Mix 4-word punchy lines with 25-word flowing sentences
- **Contractions**: I'm, I've, it's, don't (not "I am", "I have")
- **Forbidden phrases**: The model is explicitly banned from using AI clichés
- **Specific details**: References real numbers/achievements from your resume
- **Company research**: Mentions something specific about the company
- **Natural sign-offs**: "Thanks," or "Talk soon," not "Best Regards,"
- **Conjunction starts**: Occasionally begins sentences with "And", "But", "So"

---

## 📧 Gmail Setup (Important)

1. Go to your Google Account → Security → 2-Step Verification → Enable it
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Select "Mail" + "Windows Computer" → Generate
4. Copy the 16-character password → paste as `GMAIL_APP_PASSWORD`

Gmail limits: 500 emails/day (personal), 2000/day (Workspace)

---

## 📁 Project Structure

```
job-auto-apply/
├── main.py              # FastAPI app + scheduler entry point
├── config.py            # Settings (loaded from .env)
├── database.py          # SQLite models (jobs, emails, stats)
├── resume_parser.py     # PDF/DOCX → structured profile via Claude
├── job_scraper.py       # 7 job sources → deduplicated job list
├── email_finder.py      # Company domain → HR email discovery
├── email_generator.py   # Human-like cold emails + cover letters
├── email_sender.py      # Gmail SMTP with resume attachment
├── form_filler.py       # Playwright ATS form automation
├── orchestrator.py      # Daily pipeline coordinator
├── uploads/             # Your resume goes here
├── data/                # SQLite database (auto-created)
├── logs/                # Application logs
├── Dockerfile
├── docker-compose.yml
├── railway.json
└── .env.example
```

---

## 🔧 Troubleshooting

**"Gmail auth failed"**
→ Make sure you're using an App Password, not your real password
→ Check that 2FA is enabled on your Google account

**"No new jobs found"**
→ Your keywords may be too narrow — try broader JOB_TITLES
→ Some scrapers may be rate-limited temporarily — wait and retry

**"CAPTCHA detected on form"**
→ Add `TWOCAPTCHA_API_KEY` to your .env (costs ~$1/1000 solves)
→ Or skip form filling and rely on cold email only

**"Resume parsing failed"**
→ Check ANTHROPIC_API_KEY is valid
→ Make sure the resume file exists at RESUME_PATH

**LinkedIn scraping blocked**
→ This is normal — LinkedIn aggressively blocks scrapers
→ The other 6 sources provide plenty of jobs

---

## ⚠️ Legal & Ethical Notes

- **Cold emailing** is legal in most jurisdictions if you include an unsubscribe option
- **Job site scraping** — some sites' ToS prohibit it. Use their official APIs where available
- **LinkedIn scraping** is against their ToS — use at your own risk or use their official API
- **Rate limiting** — the app has built-in delays to be respectful of servers
- Apply to jobs you're genuinely qualified for — don't spam every listing
