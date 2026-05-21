"""
job_scraper.py — Aggregate jobs from multiple FREE sources

Sources (all free, no login required unless noted):
  1. RemoteOK      — JSON API, no key needed
  2. Remotive      — JSON API, no key needed
  3. WeWorkRemotely — RSS feed
  4. The Muse      — free API (key optional)
  5. Adzuna        — free API (requires free registration)
  6. Indeed        — HTML scraping (careful, rate-limit friendly)
  7. LinkedIn      — HTML scraping (stealth mode via Playwright)
"""
from __future__ import annotations
import asyncio
import hashlib
import re
from datetime import datetime
from typing import List, Optional
import httpx
import feedparser
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from database import upsert_job, get_all_job_ids

ua = UserAgent()

HEADERS = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",

    "Connection": "keep-alive",
}


def make_job_id(source: str, uid: str) -> str:
    return f"{source}:{uid}"


def score_job(job: dict, profile: dict) -> float:
    """Simple keyword-based match score 0-1."""
    if not profile:
        return 0.5
    skills = {s.lower() for s in profile.get("skills", [])}
    desc = (job.get("description", "") + " " + job.get("title", "")).lower()
    hits = sum(1 for s in skills if s in desc)
    return min(hits / max(len(skills), 1), 1.0)


# ── 1. RemoteOK ─────────────────────────────────────────────────────────────

async def scrape_remoteok(client: httpx.AsyncClient, keywords: List[str]) -> List[dict]:
    jobs = []
    try:
        resp = await client.get(
            "https://remoteok.com/api",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20
        )
        data = resp.json()
        for item in data:
            if not isinstance(item, dict) or "position" not in item:
                continue
            title = item.get("position", "")
            company = item.get("company", "")
            tags = " ".join(item.get("tags", []))
            desc = item.get("description", "")
            # keyword filter
            text = f"{title} {tags} {desc}".lower()
            if not any(kw.lower() in text for kw in keywords):
                continue
            slug = item.get("slug", str(item.get("id", "")))
            jobs.append({
                "id": make_job_id("remoteok", slug),
                "title": title,
                "company": company,
                "location": "Remote",
                "url": f"https://remoteok.com/remote-jobs/{slug}",
                "description": desc,
                "salary": item.get("salary", ""),
                "source": "remoteok",
                "posted_at": datetime.utcfromtimestamp(int(item.get("epoch", 0)))
                             if item.get("epoch") else None,
            })
    except Exception as e:
        print(f"[RemoteOK] Error: {e}")
    print(f"[RemoteOK] Found {len(jobs)} jobs")
    return jobs


# ── 2. Remotive ─────────────────────────────────────────────────────────────

async def scrape_remotive(client: httpx.AsyncClient, keywords: List[str]) -> List[dict]:
    jobs = []
    try:
        for title in settings.JOB_TITLES[:3]:
            resp = await client.get(
                f"https://remotive.com/api/remote-jobs",
                headers={**HEADERS, "Accept": "application/json"},
                params={"search": title, "limit": 50},
                timeout=20
            )
            data = resp.json()
            for item in data.get("jobs", []):
                desc = item.get("description", "")
                text = f"{item.get('title','')} {item.get('tags','')} {desc}".lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                jid = str(item.get("id", ""))
                jobs.append({
                    "id": make_job_id("remotive", jid),
                    "title": item.get("title", ""),
                    "company": item.get("company_name", ""),
                    "location": item.get("candidate_required_location", "Remote"),
                    "url": item.get("url", ""),
                    "description": BeautifulSoup(desc, "html.parser").get_text(),
                    "salary": item.get("salary", ""),
                    "source": "remotive",
                    "posted_at": datetime.strptime(item["publication_date"][:10], "%Y-%m-%d")
                                 if item.get("publication_date") else None,
                })
            await asyncio.sleep(1)
    except Exception as e:
        print(f"[Remotive] Error: {e}")
    print(f"[Remotive] Found {len(jobs)} jobs")
    return jobs


# ── 3. WeWorkRemotely (RSS) ──────────────────────────────────────────────────

WWREMOTE_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]


async def scrape_weworkremotely(keywords: List[str]) -> List[dict]:
    jobs = []
    try:
        for feed_url in WWREMOTE_FEEDS:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                desc = entry.get("summary", "")
                text = f"{title} {desc}".lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                link = entry.get("link", "")
                uid = hashlib.md5(link.encode()).hexdigest()[:12]
                # Parse company from title "Company: Job Title"
                company = ""
                if ": " in title:
                    company, title = title.split(": ", 1)
                jobs.append({
                    "id": make_job_id("weworkremotely", uid),
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": "Remote",
                    "url": link,
                    "description": BeautifulSoup(desc, "html.parser").get_text(),
                    "salary": "",
                    "source": "weworkremotely",
                    "posted_at": datetime(*entry.published_parsed[:6])
                                 if entry.get("published_parsed") else None,
                })
    except Exception as e:
        print(f"[WeWorkRemotely] Error: {e}")
    print(f"[WeWorkRemotely] Found {len(jobs)} jobs")
    return jobs


# ── 4. The Muse ──────────────────────────────────────────────────────────────

async def scrape_the_muse(client: httpx.AsyncClient, keywords: List[str]) -> List[dict]:
    jobs = []
    try:
        params = {
            "category": "Engineering",
            "level": "Mid Level",
            "page": 1,
            "api_key": settings.THE_MUSE_API_KEY or "",
        }
        resp = await client.get("https://www.themuse.com/api/public/jobs",
                                headers={**HEADERS, "Accept": "application/json"},
                                params=params, timeout=20)
        data = resp.json()
        for item in data.get("results", []):
            title = item.get("name", "")
            desc_parts = [c.get("body", "") for c in item.get("contents", [])]
            desc = " ".join(desc_parts)
            text = f"{title} {desc}".lower()
            if not any(kw.lower() in text for kw in keywords):
                continue
            uid = str(item.get("id", ""))
            jobs.append({
                "id": make_job_id("themuse", uid),
                "title": title,
                "company": item.get("company", {}).get("name", ""),
                "location": ", ".join(
                    loc.get("name", "") for loc in item.get("locations", [])
                ) or "Remote",
                "url": item.get("refs", {}).get("landing_page", ""),
                "description": BeautifulSoup(desc, "html.parser").get_text(),
                "salary": "",
                "source": "themuse",
                "posted_at": datetime.strptime(
                    item["publication_date"][:10], "%Y-%m-%d"
                ) if item.get("publication_date") else None,
            })
    except Exception as e:
        print(f"[TheMuse] Error: {e}")
    print(f"[TheMuse] Found {len(jobs)} jobs")
    return jobs


# ── 5. Adzuna ────────────────────────────────────────────────────────────────

async def scrape_adzuna(client: httpx.AsyncClient, keywords: List[str]) -> List[dict]:
    if not settings.ADZUNA_APP_ID or not settings.ADZUNA_APP_KEY:
        return []
    jobs = []
    try:
        for title in settings.JOB_TITLES[:2]:
            resp = await client.get(
                f"https://api.adzuna.com/v1/api/jobs/us/search/1",
                params={
                    "app_id": settings.ADZUNA_APP_ID,
                    "app_key": settings.ADZUNA_APP_KEY,
                    "what": title,
                    "where": settings.JOB_LOCATION,
                    "results_per_page": 50,
                    "content-type": "application/json",
                },
                timeout=20
            )
            data = resp.json()
            for item in data.get("results", []):
                uid = item.get("id", "")
                desc = item.get("description", "")
                jobs.append({
                    "id": make_job_id("adzuna", uid),
                    "title": item.get("title", ""),
                    "company": item.get("company", {}).get("display_name", ""),
                    "location": item.get("location", {}).get("display_name", ""),
                    "url": item.get("redirect_url", ""),
                    "description": desc,
                    "salary": f"{item.get('salary_min','')} - {item.get('salary_max','')}",
                    "source": "adzuna",
                    "posted_at": datetime.strptime(
                        item["created"][:10], "%Y-%m-%d"
                    ) if item.get("created") else None,
                })
            await asyncio.sleep(1)
    except Exception as e:
        print(f"[Adzuna] Error: {e}")
    print(f"[Adzuna] Found {len(jobs)} jobs")
    return jobs


# ── 6. Indeed (HTML scraping) ────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
async def scrape_indeed(client: httpx.AsyncClient, keywords: List[str]) -> List[dict]:
    jobs = []
    try:
        for title in settings.JOB_TITLES[:2]:
            params = {
                "q": title,
                "l": settings.JOB_LOCATION,
                "sort": "date",
                "fromage": "7",  # last 7 days
            }
            resp = await client.get(
                "https://www.indeed.com/jobs",
                params=params,
                headers={**HEADERS, "User-Agent": ua.random},
                follow_redirects=True,
                timeout=30
            )
            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("[data-jk]")
            for card in cards[:25]:
                jk = card.get("data-jk", "")
                t = card.select_one("h2.jobTitle")
                c = card.select_one("[data-testid='company-name']")
                l = card.select_one("[data-testid='text-location']")
                s = card.select_one("[data-testid='attribute_snippet_testid']")
                title_text = t.get_text(strip=True) if t else ""
                if not title_text:
                    continue
                description = s.get_text(strip=True) if s else ""
                text = f"{title_text} {description} {c.get_text(strip=True) if c else ''} {l.get_text(strip=True) if l else ''}".lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                jobs.append({
                    "id": make_job_id("indeed", jk),
                    "title": title_text,
                    "company": c.get_text(strip=True) if c else "",
                    "location": l.get_text(strip=True) if l else "",
                    "url": f"https://www.indeed.com/viewjob?jk={jk}",
                    "description": description,
                    "salary": "",
                    "source": "indeed",
                    "posted_at": None,
                })
            await asyncio.sleep(5)  # be polite
    except Exception as e:
        print(f"[Indeed] Error: {e}")
    print(f"[Indeed] Found {len(jobs)} jobs")
    return jobs


# ── 7. LinkedIn (Playwright stealth) ─────────────────────────────────────────

async def scrape_linkedin(keywords: List[str]) -> List[dict]:
    """Scrape LinkedIn public job search — no login required for basic results."""
    jobs = []
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )
            context = await browser.new_context(
                user_agent=ua.random,
                viewport={"width": 1366, "height": 768},
            )
            page = await context.new_page()
            # Remove webdriver property
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            for title in settings.JOB_TITLES[:2]:
                url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={title.replace(' ','+')}"
                    f"&location={settings.JOB_LOCATION.replace(' ','+')}"
                    f"&f_TPR=r604800&sortBy=DD"  # last week, recent first
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # Scroll to load more
                for _ in range(3):
                    await page.keyboard.press("End")
                    await asyncio.sleep(2)

                cards = await page.query_selector_all(".jobs-search__results-list li")
                for card in cards[:30]:
                    try:
                        title_el = await card.query_selector("h3")
                        company_el = await card.query_selector("h4")
                        loc_el = await card.query_selector(".job-search-card__location")
                        link_el = await card.query_selector("a.base-card__full-link")
                        title_text = await title_el.inner_text() if title_el else ""
                        company_text = await company_el.inner_text() if company_el else ""
                        loc_text = await loc_el.inner_text() if loc_el else ""
                        link = await link_el.get_attribute("href") if link_el else ""
                        if not title_text or not link:
                            continue
                        text = f"{title_text} {company_text} {loc_text}".lower()
                        if not any(kw.lower() in text for kw in keywords):
                            continue
                        uid = hashlib.md5(link.encode()).hexdigest()[:12]
                        jobs.append({
                            "id": make_job_id("linkedin", uid),
                            "title": title_text.strip(),
                            "company": company_text.strip(),
                            "location": loc_text.strip(),
                            "url": link.split("?")[0],
                            "description": "",
                            "salary": "",
                            "source": "linkedin",
                            "posted_at": None,
                        })
                    except Exception:
                        continue
                await asyncio.sleep(4)
            await browser.close()
    except Exception as e:
        print(f"[LinkedIn] Error: {e}")
    print(f"[LinkedIn] Found {len(jobs)} jobs")
    return jobs


# ── Deduplicate & filter ─────────────────────────────────────────────────────

def deduplicate(jobs: List[dict]) -> List[dict]:
    seen_ids = set()
    seen_titles = {}  # (company_lower, title_lower) -> True
    result = []
    for job in jobs:
        jid = job["id"]
        key = (job["company"].lower().strip(), job["title"].lower().strip())
        if jid in seen_ids or key in seen_titles:
            continue
        # Skip excluded companies
        if any(ex.lower() in job["company"].lower()
               for ex in settings.EXCLUDED_COMPANIES):
            continue
        seen_ids.add(jid)
        seen_titles[key] = True
        result.append(job)
    return result


# ── Master scraper ───────────────────────────────────────────────────────────

async def scrape_all_jobs(profile: dict = None) -> List[dict]:
    keywords = list(set(
        settings.JOB_TITLES + settings.JOB_KEYWORDS +
        (profile.get("skills", [])[:10] if profile else [])
    ))
    print(f"[Scraper] Searching with {len(keywords)} keywords across all sources...")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        results = await asyncio.gather(
            scrape_remoteok(client, keywords),
            scrape_remotive(client, keywords),
            scrape_weworkremotely(keywords),
            scrape_the_muse(client, keywords),
            scrape_adzuna(client, keywords),
            scrape_indeed(client, keywords),
            scrape_linkedin(keywords),
            return_exceptions=True
        )

    all_jobs = []
    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)
        elif isinstance(r, Exception):
            print(f"[Scraper] Source error: {r!r}")

    # Score and deduplicate
    for job in all_jobs:
        job["match_score"] = score_job(job, profile)

    # Filter by relevance threshold
    filtered_jobs = [j for j in all_jobs if j["match_score"] >= settings.MIN_MATCH_SCORE]
    dropped = len(all_jobs) - len(filtered_jobs)
    if dropped:
        print(f"[Scraper] Dropped {dropped} low-relevance jobs below match score {settings.MIN_MATCH_SCORE}")

    all_jobs = deduplicate(filtered_jobs)
    all_jobs.sort(key=lambda j: j["match_score"], reverse=True)

    # Filter already-seen jobs
    known_ids = await get_all_job_ids()
    new_jobs = [j for j in all_jobs if j["id"] not in known_ids]

    # Save to DB
    saved = 0
    for job in all_jobs:
        if await upsert_job(job):
            saved += 1

    print(f"[Scraper] Total: {len(all_jobs)} | New: {saved} | "
          f"Best match: {all_jobs[0]['title'] if all_jobs else 'n/a'}")
    return new_jobs
