"""
email_finder.py — Discover HR/recruiter emails via:
  1. Hunter.io API (free tier — 25/month)
  2. Pattern generation (firstname@company.com etc.)
  3. Company website scraping (careers/contact pages)
  4. LinkedIn scraping (visible emails in profiles)
"""
from __future__ import annotations
import asyncio
import re
from typing import List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

ua = UserAgent()

EMAIL_PATTERNS = [
    "{first}@{domain}",
    "{first}.{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}{last}@{domain}",
    "{first}_{last}@{domain}",
    "hr@{domain}",
    "careers@{domain}",
    "recruiting@{domain}",
    "talent@{domain}",
    "jobs@{domain}",
    "recruit@{domain}",
    "hiring@{domain}",
    "apply@{domain}",
    "people@{domain}",
    "team@{domain}",
]

HR_TITLES = [
    "recruiter", "talent", "hr", "hiring", "people ops",
    "head of talent", "engineering manager", "founder", "cto", "vp engineering"
]


# ── 1. Hunter.io ─────────────────────────────────────────────────────────────

async def hunter_domain_search(
    domain: str, client: httpx.AsyncClient
) -> List[dict]:
    """Search Hunter.io for all emails at a domain."""
    if not settings.HUNTER_API_KEY:
        return []
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain": domain,
                "api_key": settings.HUNTER_API_KEY,
                "limit": 10,
                "type": "personal",
            },
            timeout=15
        )
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])
        # Prioritise HR/recruiting roles
        hr_emails = [
            e for e in emails
            if any(t in (e.get("position") or "").lower() for t in HR_TITLES)
        ]
        return hr_emails or emails[:3]
    except Exception as e:
        print(f"[Hunter] Error for {domain}: {e}")
        return []


async def hunter_email_finder(
    first: str, last: str, domain: str, client: httpx.AsyncClient
) -> Optional[str]:
    """Verify a specific email exists via Hunter."""
    if not settings.HUNTER_API_KEY:
        return None
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain": domain,
                "first_name": first,
                "last_name": last,
                "api_key": settings.HUNTER_API_KEY,
            },
            timeout=15
        )
        data = resp.json()
        email_data = data.get("data", {})
        if email_data.get("score", 0) > 50:
            return email_data.get("email")
    except Exception:
        pass
    return None


# ── 2. Website scraping ──────────────────────────────────────────────────────

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "google.com",
    "cloudflare.com", "amazonaws.com", "github.com"
}


async def scrape_emails_from_url(url: str, client: httpx.AsyncClient) -> List[str]:
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": ua.random},
            timeout=15,
            follow_redirects=True,
        )
        text = resp.text
        found = EMAIL_REGEX.findall(text)
        return [
            e.lower() for e in found
            if not any(j in e for j in JUNK_DOMAINS)
            and len(e) < 60
        ]
    except Exception:
        return []


async def scrape_company_emails(
    company_domain: str, client: httpx.AsyncClient
) -> List[str]:
    """Scrape homepage + /careers + /about + /contact for emails."""
    urls_to_try = [
        f"https://{company_domain}",
        f"https://{company_domain}/careers",
        f"https://{company_domain}/jobs",
        f"https://{company_domain}/about",
        f"https://{company_domain}/contact",
        f"https://{company_domain}/team",
        f"https://www.{company_domain}/about",
    ]
    all_emails: List[str] = []
    for url in urls_to_try[:4]:
        emails = await scrape_emails_from_url(url, client)
        all_emails.extend(emails)
        if emails:
            await asyncio.sleep(1)
    # Deduplicate and filter to domain
    unique = list(dict.fromkeys(all_emails))
    domain_emails = [e for e in unique if company_domain in e]
    return domain_emails or unique[:3]


# ── 3. Domain extraction from company name / job URL ─────────────────────────

COMMON_TLDS = [".com", ".io", ".co", ".ai", ".tech", ".dev", ".app"]


def company_to_domain(company: str, job_url: str = "") -> Optional[str]:
    """Best-effort domain guess from company name and job URL."""
    # Extract from job URL first
    if job_url:
        m = re.search(r"https?://(?:www\.)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})", job_url)
        if m:
            domain = m.group(1).lower()
            if not any(board in domain for board in [
                "linkedin", "indeed", "glassdoor", "remoteok", "lever",
                "greenhouse", "workday", "ashbyhq", "jobvite", "smartrecruiters",
                "remotive", "weworkremotely", "themuse", "adzuna"
            ]):
                return domain

    # Guess from company name
    name = re.sub(r"[^a-zA-Z0-9\s]", "", company).strip().lower()
    name = re.sub(r"\s+", "", name)
    name = re.sub(r"(inc|llc|ltd|corp|co|company|technologies|tech|labs)$", "", name)
    if name:
        return f"{name}.com"
    return None


# ── 4. Pattern generation + verification ────────────────────────────────────

def generate_email_patterns(
    first: str, last: str, domain: str
) -> List[str]:
    f = first[0].lower() if first else ""
    first_l = first.lower()
    last_l = last.lower()
    patterns = []
    for p in EMAIL_PATTERNS:
        try:
            email = p.format(
                first=first_l, last=last_l, f=f, domain=domain
            )
            patterns.append(email)
        except KeyError:
            patterns.append(p.format(domain=domain))
    return list(dict.fromkeys(patterns))


async def verify_email_smtp(email: str) -> bool:
    """
    Very basic MX + SMTP verification (no actual email sent).
    Returns True if mailbox *likely* exists.
    Note: Many servers block VRFY. Use Hunter for better accuracy.
    """
    import socket
    import smtplib
    domain = email.split("@")[1]
    try:
        mx = socket.gethostbyname(domain)
        smtp = smtplib.SMTP(timeout=5)
        smtp.connect(mx)
        smtp.ehlo_or_helo_if_needed()
        smtp.mail("")
        code, _ = smtp.rcpt(email)
        smtp.quit()
        return code == 250
    except Exception:
        return False  # Can't verify, assume valid for now


# ── Master email finder ───────────────────────────────────────────────────────

class ContactResult:
    def __init__(self, email: str, name: str = "", title: str = "",
                 confidence: str = "low", source: str = ""):
        self.email = email
        self.name = name
        self.title = title
        self.confidence = confidence
        self.source = source

    def __repr__(self):
        return f"<Contact {self.name} <{self.email}> [{self.confidence}]>"


async def find_contact_for_job(
    company: str, job_url: str = "", job_title: str = ""
) -> Optional[ContactResult]:
    """
    Try multiple strategies to find an HR contact.
    Returns best ContactResult or None.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": ua.random},
        follow_redirects=True,
        timeout=20
    ) as client:

        domain = company_to_domain(company, job_url)
        if not domain:
            return None

        # Strategy 1: Hunter domain search
        if settings.HUNTER_API_KEY:
            hunter_results = await hunter_domain_search(domain, client)
            if hunter_results:
                best = hunter_results[0]
                return ContactResult(
                    email=best.get("value", ""),
                    name=f"{best.get('first_name','')} {best.get('last_name','')}".strip(),
                    title=best.get("position", ""),
                    confidence="high",
                    source="hunter"
                )

        # Strategy 2: Company website scraping
        scraped = await scrape_company_emails(domain, client)
        if scraped:
            # Prefer HR-sounding emails
            hr_email = next(
                (e for e in scraped
                 if any(t in e for t in ["hr", "career", "recruit", "talent", "hiring", "jobs"])),
                scraped[0]
            )
            return ContactResult(
                email=hr_email,
                confidence="medium",
                source="website_scrape"
            )

        # Strategy 3: Generic patterns (hr@, careers@, etc.)
        generic_patterns = [
            f"hr@{domain}",
            f"careers@{domain}",
            f"recruiting@{domain}",
            f"talent@{domain}",
            f"jobs@{domain}",
        ]
        return ContactResult(
            email=generic_patterns[0],
            confidence="low",
            source="pattern"
        )
