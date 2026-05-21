# ⚡ Job Auto-Apply — Mayur Koli

Automated job application bot — scrapes 7 job boards, finds HR emails,
sends personalized cold emails with resume attached, fills ATS forms, tracks everything.
Runs every morning at **8:00 AM IST** automatically.

**Cost: $0.00/month** — everything is on free tiers.

| Component | Service | Cost |
|-----------|---------|------|
| AI (resume parse, email write, form mapping) | Gemini 1.5 Flash | Free |
| Email sending | Gmail SMTP | Free |
| Hosting + scheduler | Render Web Service | Free |
| Database | SQLite in `/tmp` | Free |
| Resume hosting | mayurkoli.mentesa.live | Already free |
| Keep-alive pings | cron-job.org | Free |

---

## 🚀 Deploy to Render (10 minutes)

### 1 — Push to GitHub

```bash
git init && git add . && git commit -m "init"
# then push to a new GitHub repo
```

### 2 — Create Web Service on Render

Go to **[render.com](https://render.com)** → **New +** → **Web Service** → connect your repo.

Render will detect `render.yaml` and auto-configure the build/start commands.

Set these manually if needed:

| Field | Value |
|-------|-------|
| Build Command | `pip install -r requirements.txt && playwright install --with-deps chromium` |
| Start Command | `python main.py` |
| Plan | **Free** |

### 3 — Set environment variables in Render Dashboard

Go to **Your Service → Environment → Add Environment Variable**.

**Must set (the rest are pre-filled in render.yaml):**

| Variable | Value | Where to get |
|----------|-------|--------------|
| `GEMINI_API_KEY` | `AIzaSy...` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — free, 30 sec |
| `GMAIL_ADDRESS` | `you@gmail.com` | Your Gmail |
| `GMAIL_APP_PASSWORD` | `xxxx xxxx xxxx xxxx` | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| `USER_EMAIL` | `you@gmail.com` | Used in email signatures |
| `USER_PHONE` | `+91-XXXXXXXXXX` | Your number |
| `USER_LINKEDIN` | `https://linkedin.com/in/...` | Your LinkedIn URL |
| `USER_GITHUB` | `https://github.com/...` | Your GitHub URL |

Everything else (`RESUME_URL`, `DATABASE_PATH`, `JOB_TITLES`, `TIMEZONE`, etc.)
is **already set** in `render.yaml` — you don't need to touch them.

### 4 — Keep the instance awake (free)

Render's free tier **sleeps after 15 min of no traffic**.
The 8 AM scheduler won't fire if the instance is asleep.

Fix with **[cron-job.org](https://cron-job.org)** (completely free):

1. Sign up → **New Cronjob**
2. URL: `https://YOUR-APP-NAME.onrender.com/api/ping`
3. Schedule: **Every 10 minutes**
4. Save

This keeps the instance running 24/7 so the daily run always fires.

### 5 — Verify it works

Open `https://YOUR-APP.onrender.com` — you'll see the dashboard.

Click **"Test Email Config"** — you should get a test email in your inbox within 30 seconds.

---

## 🔁 How the pipeline works

```
08:00 AM IST — scheduler fires
        ↓
Resume downloaded from mayurkoli.mentesa.live → parsed by Gemini
        ↓
7 job sources scraped in parallel:
  • RemoteOK         (free JSON API)
  • Remotive         (free JSON API)
  • WeWorkRemotely   (RSS feed)
  • The Muse         (free API)
  • Adzuna           (free API — register once)
  • Indeed           (HTML scrape)
  • LinkedIn         (Playwright stealth)
        ↓
For each job (up to 50/day):
  ① Find HR email
       Hunter.io → website scrape → pattern guess (hr@, careers@, recruiting@)
  ② Generate cold email via Gemini  ← human-like, anti-AI-detection prompt
  ③ Send via Gmail SMTP with resume PDF attached          ← PRIMARY
  ④ If job has Greenhouse/Lever/Workday URL → fill form  ← FALLBACK
        ↓
Log every application to SQLite (/tmp/jobs.db)
```

---

## 💻 CLI commands

```bash
python cli.py parse-resume              # re-parse resume
python cli.py run                       # full run (email + forms)
python cli.py run --email-only          # cold email only (faster)
python cli.py run --limit 10            # cap at 10 applications
python cli.py stats                     # show stats table
python cli.py jobs --applied            # list applied jobs
python cli.py follow-up --days 7        # send follow-ups
python cli.py export --format csv       # export to CSV
python cli.py test-email                # verify Gmail config
```

---

## 📁 File structure

```
job-auto-apply/
├── main.py            FastAPI app + APScheduler + web dashboard
├── startup.py         Resume download, DB init, preflight checks
├── config.py          All settings (env vars)
├── database.py        SQLite models — jobs, email log, stats
├── resume_parser.py   PDF → structured profile (Gemini)
├── job_scraper.py     7 sources → deduplicated, scored job list
├── email_finder.py    HR email discovery (Hunter → scrape → pattern)
├── email_generator.py Human-like cold email + cover letter (Gemini)
├── email_sender.py    Gmail SMTP with resume attachment
├── form_filler.py     Playwright + Gemini vision form automation
├── ats_handlers.py    Greenhouse, Lever, Workday, Ashby, SmartRecruiters...
├── orchestrator.py    Daily pipeline coordinator
├── rate_limiter.py    Per-domain request throttling
├── cli.py             Full CLI interface
├── render.yaml        Render Blueprint — one-click deploy
├── Dockerfile         For local Docker
├── docker-compose.yml
└── .env.example       All variables documented
```

---

## 🛡️ Anti-AI detection (built into every email)

The Gemini prompt hard-bans AI writing patterns:

- **Banned:** "leverage", "synergy", "I am writing to express my interest",
  "passionate about", "team player", "proven track record", "Best Regards"
- **Required:** contractions (I'm, I've, it's), varied sentence lengths,
  one specific company detail, one numbered achievement from resume
- **Sign-off:** "Thanks," or "Talk soon," — never "Sincerely"

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| Service sleeping at 8 AM | Set up cron-job.org ping every 10 min |
| Resume not loading | Check `RESUME_URL` is publicly accessible |
| Gmail auth failed | Use App Password (16 chars), not real password. Enable 2FA first |
| Playwright OOM on Render | Set `--email-only` mode — use email outreach only |
| LinkedIn blocked | Normal — 6 other sources provide enough jobs |
| "No new jobs" | Broaden `JOB_TITLES` or `JOB_KEYWORDS` env vars |
