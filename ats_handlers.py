"""
ats_handlers.py — Dedicated handlers for major ATS platforms.

Greenhouse, Lever, Workday, Ashby, SmartRecruiters, BambooHR, iCIMS.
Each has its own form structure — these handlers fill them precisely
instead of relying on the generic screenshot-to-Claude approach.
"""
from __future__ import annotations
import asyncio
import random
from typing import Optional
from playwright.async_api import Page
from config import settings


async def _type(page: Page, selector: str, text: str, clear: bool = True):
    """Fill a field safely — skip if not found."""
    try:
        el = await page.wait_for_selector(selector, timeout=5000, state="visible")
        if el:
            if clear:
                await el.triple_click()
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await el.type(text, delay=random.uniform(30, 90))
    except Exception:
        pass


async def _upload(page: Page, selector: str, path: str):
    try:
        el = await page.query_selector(selector)
        if el:
            await el.set_input_files(path)
            print(f"[ATS] Uploaded {path}")
    except Exception as e:
        print(f"[ATS] Upload failed: {e}")


async def _click(page: Page, selector: str):
    try:
        el = await page.wait_for_selector(selector, timeout=5000)
        if el:
            await el.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass


def _name_parts(profile: dict) -> tuple[str, str]:
    full = profile.get("name", settings.USER_FULL_NAME) or settings.USER_FULL_NAME
    parts = full.strip().split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


# ── GREENHOUSE ────────────────────────────────────────────────────────────────

async def fill_greenhouse(page: Page, profile: dict, cover_letter: str):
    """
    Greenhouse apply pages — boards.greenhouse.io
    Standard fields: first, last, email, phone, resume, cover letter, LinkedIn, GitHub
    """
    first, last = _name_parts(profile)

    await _type(page, "#first_name", first)
    await _type(page, "#last_name", last)
    await _type(page, "#email", settings.USER_EMAIL)
    await _type(page, "#phone", settings.USER_PHONE)

    if settings.USER_LINKEDIN:
        await _type(page, "input[id*='linkedin']", settings.USER_LINKEDIN)
    if settings.USER_GITHUB:
        await _type(page, "input[id*='github']", settings.USER_GITHUB)
    if settings.USER_PORTFOLIO:
        await _type(page, "input[id*='website'], input[id*='portfolio']", settings.USER_PORTFOLIO)

    # Resume upload
    await _upload(page, "input[type='file'][id*='resume']", settings.RESUME_PATH)

    # Cover letter — try textarea first, then file upload
    cl_textarea = await page.query_selector("textarea[id*='cover']")
    if cl_textarea and cover_letter:
        await cl_textarea.fill(cover_letter[:4000])
    else:
        cl_file = await page.query_selector("input[type='file'][id*='cover']")
        if cl_file:
            # Would need to write cover letter to temp file — skip for now
            pass

    # Answer custom questions (Yes/No type)
    # Look for radio buttons asking about authorization / remote / relocation
    for radio in await page.query_selector_all("input[type='radio'][value='Yes']"):
        label_el = await page.query_selector(f"label[for='{await radio.get_attribute('id')}']")
        label_text = (await label_el.inner_text()).lower() if label_el else ""
        safe_yes = ["authorized", "eligible", "citizen", "remote", "willing"]
        if any(kw in label_text for kw in safe_yes):
            await radio.click()

    print("[Greenhouse] Form filled")


# ── LEVER ──────────────────────────────────────────────────────────────────────

async def fill_lever(page: Page, profile: dict, cover_letter: str):
    """
    Lever apply pages — jobs.lever.co
    """
    first, last = _name_parts(profile)
    full_name = f"{first} {last}".strip()

    await _type(page, "#name", full_name)
    await _type(page, "#email", settings.USER_EMAIL)
    await _type(page, "#phone", settings.USER_PHONE)

    # Current company (optional — leave blank or use "Open to opportunities")
    curr_company = (profile.get("experience") or [{}])[0].get("company", "")
    await _type(page, "#org", curr_company)

    # Links
    if settings.USER_LINKEDIN:
        await _type(page, "#urls_LinkedIn", settings.USER_LINKEDIN)
    if settings.USER_GITHUB:
        await _type(page, "#urls_Github", settings.USER_GITHUB)
    if settings.USER_PORTFOLIO:
        await _type(page, "#urls_Portfolio", settings.USER_PORTFOLIO)

    # Cover letter in the "comments" textarea
    if cover_letter:
        await _type(page, "#comments", cover_letter[:3000])

    # Resume
    await _upload(page, "input[type='file']", settings.RESUME_PATH)

    print("[Lever] Form filled")


# ── WORKDAY ────────────────────────────────────────────────────────────────────

async def fill_workday(page: Page, profile: dict, cover_letter: str):
    """
    Workday is complex — multi-step wizard. This handles the most common pages.
    """
    first, last = _name_parts(profile)

    # Step 1: Personal info
    await _type(page, "[data-automation-id='firstName']", first)
    await _type(page, "[data-automation-id='lastName']", last)
    await _type(page, "[data-automation-id='email']", settings.USER_EMAIL)
    await _type(page, "[data-automation-id='phone']", settings.USER_PHONE)
    await _type(page, "[data-automation-id='addressLine1']", settings.USER_LOCATION)

    # Step 2: Resume upload (Workday has a specific dropzone)
    resume_drop = await page.query_selector("[data-automation-id='file-upload-drop-zone']")
    if resume_drop:
        file_input = await page.query_selector("input[type='file']")
        if file_input:
            await file_input.set_input_files(settings.RESUME_PATH)

    # Step 3: Work experience (Workday often pre-fills from resume parse)
    # Try to skip/continue past experience sections
    continue_btn = await page.query_selector("[data-automation-id='bottom-navigation-next-btn']")
    if continue_btn:
        await continue_btn.click()
        await asyncio.sleep(2)

    print("[Workday] Attempted form fill (multi-step)")


# ── ASHBY ──────────────────────────────────────────────────────────────────────

async def fill_ashby(page: Page, profile: dict, cover_letter: str):
    """
    Ashby HQ — ashbyhq.com
    Modern, clean ATS used by many startups.
    """
    first, last = _name_parts(profile)

    await _type(page, "input[name='_systemfield_name']", f"{first} {last}")
    await _type(page, "input[name='_systemfield_email']", settings.USER_EMAIL)
    await _type(page, "input[name='_systemfield_phone']", settings.USER_PHONE)

    # Links
    if settings.USER_LINKEDIN:
        await _type(page, "input[placeholder*='LinkedIn']", settings.USER_LINKEDIN)
    if settings.USER_GITHUB:
        await _type(page, "input[placeholder*='GitHub']", settings.USER_GITHUB)
    if settings.USER_PORTFOLIO:
        await _type(page, "input[placeholder*='Website'], input[placeholder*='Portfolio']",
                    settings.USER_PORTFOLIO)

    # Resume
    await _upload(page, "input[type='file'][accept*='pdf']", settings.RESUME_PATH)

    # Cover letter
    if cover_letter:
        await _type(page, "textarea[placeholder*='cover'], textarea[name*='cover']",
                    cover_letter[:3000])

    print("[Ashby] Form filled")


# ── SMARTRECRUITERS ──────────────────────────────────────────────────────────

async def fill_smartrecruiters(page: Page, profile: dict, cover_letter: str):
    """
    SmartRecruiters — smartrecruiters.com
    """
    first, last = _name_parts(profile)

    await _type(page, "input[name='firstName']", first)
    await _type(page, "input[name='lastName']", last)
    await _type(page, "input[name='email']", settings.USER_EMAIL)
    await _type(page, "input[name='phoneNumber']", settings.USER_PHONE)

    await _upload(page, "input[type='file']", settings.RESUME_PATH)

    if cover_letter:
        await _type(page, "textarea[name='message'], textarea[placeholder*='cover']",
                    cover_letter[:2000])

    print("[SmartRecruiters] Form filled")


# ── BAMBOOHR ──────────────────────────────────────────────────────────────────

async def fill_bamboohr(page: Page, profile: dict, cover_letter: str):
    """
    BambooHR — bamboohr.com
    """
    first, last = _name_parts(profile)

    await _type(page, "input[id='firstName']", first)
    await _type(page, "input[id='lastName']", last)
    await _type(page, "input[id='email']", settings.USER_EMAIL)
    await _type(page, "input[id='phone']", settings.USER_PHONE)

    if settings.USER_LINKEDIN:
        await _type(page, "input[id='linkedIn']", settings.USER_LINKEDIN)

    await _upload(page, "input[type='file'][id*='resume']", settings.RESUME_PATH)

    if cover_letter:
        cl_el = await page.query_selector("textarea[id*='coverLetter'], textarea[id*='cover']")
        if cl_el:
            await cl_el.fill(cover_letter[:3000])

    print("[BambooHR] Form filled")


# ── ICIMS ────────────────────────────────────────────────────────────────────

async def fill_icims(page: Page, profile: dict, cover_letter: str):
    """
    iCIMS — icims.com. Often has multi-page wizards.
    """
    first, last = _name_parts(profile)

    await _type(page, "input[name='firstname']", first)
    await _type(page, "input[name='lastname']", last)
    await _type(page, "input[name='email']", settings.USER_EMAIL)
    await _type(page, "input[name='phone']", settings.USER_PHONE)
    await _type(page, "input[name='address']", settings.USER_LOCATION)

    await _upload(page, "input[type='file']", settings.RESUME_PATH)

    print("[iCIMS] Form filled")


# ── LINKEDIN EASY APPLY ───────────────────────────────────────────────────────

async def fill_linkedin_easy_apply(page: Page, profile: dict, cover_letter: str):
    """
    LinkedIn Easy Apply — requires being logged in.
    Note: LinkedIn account required. Handle with care.
    """
    # Most Easy Apply forms pre-fill from your LinkedIn profile
    # We just handle the extra questions

    # Phone number (often asked)
    await _type(page, "input[id*='phoneNumber']", settings.USER_PHONE)

    # City/location
    city = settings.USER_LOCATION.split(",")[0].strip()
    await _type(page, "input[id*='city']", city)

    # Common yes/no questions — always answer Yes to work authorization
    for radio in await page.query_selector_all("input[type='radio']"):
        val = (await radio.get_attribute("value") or "").lower()
        label_id = await radio.get_attribute("id")
        label_el = await page.query_selector(f"label[for='{label_id}']")
        label_txt = (await label_el.inner_text()).lower() if label_el else ""

        if val == "yes" and any(kw in label_txt for kw in
                                ["authorized", "eligible", "legally", "remote"]):
            await radio.click()

    # Cover letter textarea
    if cover_letter:
        cl_area = await page.query_selector("textarea")
        if cl_area:
            await cl_area.fill(cover_letter[:1900])  # LinkedIn has 2000 char limit

    # Click next through multi-step
    next_btn = await page.query_selector("button[aria-label='Continue to next step']")
    if next_btn:
        await next_btn.click()
        await asyncio.sleep(1.5)

    print("[LinkedIn EasyApply] Form filled")


# ── DISPATCHER ───────────────────────────────────────────────────────────────

ATS_HANDLERS = {
    "greenhouse": fill_greenhouse,
    "lever": fill_lever,
    "workday": fill_workday,
    "ashby": fill_ashby,
    "smartrecruiters": fill_smartrecruiters,
    "bamboohr": fill_bamboohr,
    "icims": fill_icims,
    "linkedin": fill_linkedin_easy_apply,
}


async def dispatch_ats_handler(
    ats: str, page: Page, profile: dict, cover_letter: str
) -> bool:
    handler = ATS_HANDLERS.get(ats)
    if handler:
        await handler(page, profile, cover_letter)
        return True
    return False
