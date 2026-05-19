"""
form_filler.py — Playwright-based form automation with Gemini vision for field mapping.

Gemini 1.5 Flash supports image input on the free tier — perfect for
screenshot-to-field-mapping without paying for vision APIs.
"""
from __future__ import annotations
import asyncio
import base64
import json
import random
import re
from typing import Optional
import google.generativeai as genai
import PIL.Image
import io
from playwright.async_api import async_playwright, Page
from fake_useragent import UserAgent
from config import settings
from ats_handlers import dispatch_ats_handler, ATS_HANDLERS

ua = UserAgent()

ATS_DETECTORS = {
    "greenhouse": ["greenhouse.io", "boards.greenhouse"],
    "lever": ["lever.co", "jobs.lever"],
    "workday": ["workday.com", "myworkdayjobs"],
    "ashby": ["ashbyhq.com"],
    "bamboohr": ["bamboohr.com"],
    "smartrecruiters": ["smartrecruiters.com"],
    "icims": ["icims.com"],
}


def detect_ats(url: str) -> Optional[str]:
    url_l = url.lower()
    for ats, patterns in ATS_DETECTORS.items():
        if any(p in url_l for p in patterns):
            return ats
    return None


async def human_type(page: Page, selector: str, text: str):
    elem = await page.query_selector(selector)
    if not elem:
        return
    await elem.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    for char in text:
        await elem.type(char, delay=random.uniform(40, 120))
        if random.random() < 0.04:
            wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
            await elem.type(wrong, delay=random.uniform(40, 80))
            await asyncio.sleep(0.3)
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)


FIELD_MAPPING_PROMPT = """Analyze this job application form screenshot.
Identify ALL visible input fields and return a JSON array.

For each field:
{
  "label": "field label text",
  "type": "text|email|phone|textarea|select|checkbox|file|radio",
  "selector_hint": "best CSS selector or aria-label",
  "value_key": "name|email|phone|location|linkedin|github|portfolio|cover_letter|resume_file|years_experience|salary_expectation|how_did_you_hear|custom",
  "custom_value": "if value_key is custom, the value to enter"
}

Return ONLY a valid JSON array. No explanation, no markdown."""

VALUE_MAP = {
    "name": lambda p: p.get("name", settings.USER_FULL_NAME),
    "email": lambda p: settings.USER_EMAIL,
    "phone": lambda p: settings.USER_PHONE,
    "location": lambda p: settings.USER_LOCATION,
    "linkedin": lambda p: settings.USER_LINKEDIN or "",
    "github": lambda p: settings.USER_GITHUB or "",
    "portfolio": lambda p: settings.USER_PORTFOLIO or "",
    "years_experience": lambda p: str(int(p.get("total_experience_years", 0))),
    "salary_expectation": lambda p: str(settings.MIN_SALARY) if settings.MIN_SALARY else "",
    "how_did_you_hear": lambda p: "Online job board",
}


async def analyze_form_with_gemini(screenshot_b64: str, profile: dict) -> list:
    """Send screenshot to Gemini Vision and get field mappings back."""
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)

    image_bytes = base64.b64decode(screenshot_b64)
    image = PIL.Image.open(io.BytesIO(image_bytes))

    profile_ctx = json.dumps({
        "name": profile.get("name", settings.USER_FULL_NAME),
        "email": settings.USER_EMAIL,
        "phone": settings.USER_PHONE,
        "location": settings.USER_LOCATION,
        "linkedin": settings.USER_LINKEDIN,
        "github": settings.USER_GITHUB,
        "years_experience": profile.get("total_experience_years", ""),
    })

    response = model.generate_content(
        [FIELD_MAPPING_PROMPT + f"\n\nUser profile for reference: {profile_ctx}", image],
        generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=1500),
    )
    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except Exception:
        return []


async def fill_field(page: Page, field: dict, profile: dict, cover_letter: str = ""):
    selector_hint = field.get("selector_hint", "")
    field_type = field.get("type", "text")
    value_key = field.get("value_key", "custom")
    label = field.get("label", "").lower()

    if value_key == "cover_letter":
        value = cover_letter
    elif value_key == "resume_file":
        value = settings.RESUME_PATH
    elif value_key == "custom":
        value = field.get("custom_value", "")
    else:
        getter = VALUE_MAP.get(value_key)
        value = getter(profile) if getter else ""

    if not value:
        return

    selectors = [
        selector_hint,
        f'[aria-label*="{field.get("label","")}" i]',
        f'[placeholder*="{field.get("label","")}" i]',
    ]

    elem = None
    for sel in selectors:
        if not sel:
            continue
        try:
            elem = await page.query_selector(sel)
            if elem and await elem.is_visible():
                break
        except Exception:
            continue

    if not elem:
        return

    try:
        if field_type == "file":
            await elem.set_input_files(value)
        elif field_type == "select":
            options = await page.eval_on_selector(
                selector_hint, "el => [...el.options].map(o => o.value)"
            )
            best = next((o for o in options if str(value).lower() in o.lower()),
                        options[0] if options else "")
            if best:
                await page.select_option(selector_hint, best)
        elif field_type == "checkbox":
            if str(value).lower() in ("yes", "true", "1"):
                await elem.check()
        else:
            await elem.click()
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await elem.fill("")
            await human_type(page, selector_hint, str(value))
    except Exception as e:
        print(f"[Form] Error on '{label}': {e}")


async def solve_recaptcha_v2(page: Page, site_key: str) -> Optional[str]:
    if not settings.TWOCAPTCHA_API_KEY:
        return None
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.post("https://2captcha.com/in.php", data={
            "key": settings.TWOCAPTCHA_API_KEY,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page.url,
            "json": 1,
        })
        captcha_id = r.json().get("request")
        if not captcha_id:
            return None
        for _ in range(30):
            await asyncio.sleep(5)
            r2 = await client.get("https://2captcha.com/res.php", params={
                "key": settings.TWOCAPTCHA_API_KEY, "action": "get",
                "id": captcha_id, "json": 1
            })
            result = r2.json()
            if result.get("status") == 1:
                return result.get("request")
    return None


async def fill_application_form(
    job: dict, profile: dict, cover_letter: str = "", headless: bool = True
) -> bool:
    url = job.get("url", "")
    if not url:
        return False

    print(f"[Form] Filling: {job.get('title')} @ {job.get('company')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=ua.random,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))

            ats = detect_ats(url)
            print(f"[Form] Detected ATS: {ats or 'generic'}")

            if ats and ats in ATS_HANDLERS:
                await dispatch_ats_handler(ats, page, profile, cover_letter)
            else:
                # Generic: screenshot → Gemini vision → fill
                screenshot = await page.screenshot(full_page=True)
                b64 = base64.b64encode(screenshot).decode()
                fields = await analyze_form_with_gemini(b64, profile)
                print(f"[Form] Gemini identified {len(fields)} fields")
                for field in fields:
                    await fill_field(page, field, profile, cover_letter)
                    await asyncio.sleep(random.uniform(0.5, 1.5))

            # CAPTCHA
            recaptcha = await page.query_selector("iframe[src*='recaptcha']")
            if recaptcha:
                m = re.search(r'sitekey[=\'"]+([A-Za-z0-9_-]+)', await page.content())
                if m:
                    token = await solve_recaptcha_v2(page, m.group(1))
                    if token:
                        await page.eval_on_selector(
                            "#g-recaptcha-response",
                            f"el => {{ el.value = '{token}'; }}"
                        )

            # Submit
            for sel in [
                "button[type='submit']", "input[type='submit']",
                "button:has-text('Submit')", "button:has-text('Apply')",
                "button:has-text('Send Application')", "[data-qa='btn-submit']",
            ]:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await asyncio.sleep(random.uniform(1, 2))
                    await btn.click()
                    await asyncio.sleep(3)
                    print(f"[Form] Submitted via {sel}")
                    break

            page_text = await page.inner_text("body")
            return any(kw in page_text.lower() for kw in [
                "thank you", "application received", "successfully submitted",
                "we'll be in touch", "application complete"
            ])

        except Exception as e:
            print(f"[Form] Error: {e}")
            return False
        finally:
            await browser.close()
