"""
email_generator.py — Human-like cold emails & cover letters via Gemini (free tier).

Falls back to simple templates if Gemini quota is exceeded.

Anti-AI-detection techniques baked into every prompt:
  • Varied sentence lengths (short punchy + long flowing)
  • Contractions: I'm, I've, it's, don't — mandated
  • Banned phrases list: "leverage", "synergy", "I am writing to express", etc.
  • One specific detail about the company
  • Real numbers from resume achievements
  • Casual sign-offs: "Thanks," / "Talk soon,"
  • Occasional conjunction sentence starters (And, But, So)
"""
from __future__ import annotations
import google.generativeai as genai
from config import settings


ANTI_AI_SYSTEM_INSTRUCTION = """You write authentic, human-sounding job application emails and cover letters.

RULES — follow every one without exception:
1. Write like a real person emailing a colleague, not a robot filing paperwork.
2. BANNED PHRASES — never use: "I hope this email finds you well", "I am writing to express my interest", "leverage", "utilize", "synergy", "passionate about", "team player", "hard worker", "go-getter", "proven track record", "results-driven", "I would be a great fit", "I am excited about the opportunity", "please find attached", "do not hesitate to contact me", "looking forward to hearing from you", "Best Regards", "Sincerely".
3. SENTENCE VARIETY: Mix very short sentences (4-6 words) with longer ones (20-30 words). Never write three consecutive sentences of similar length.
4. USE CONTRACTIONS everywhere natural: I'm, I've, I'd, it's, don't, can't, won't, isn't, they're.
5. START some sentences with: And, But, So, Actually, Honestly, That said.
6. Include ONE specific detail about the company — something real about their product, recent work, or mission.
7. Reference ONE concrete achievement from the resume with a real number.
8. Cold emails: max 3 paragraphs, 150-220 words. Cover letters: max 4 paragraphs, 300-380 words.
9. Sign-off: "Thanks," or "Talk soon," — never "Sincerely" or "Best Regards".
10. Output ONLY the requested content — no preamble, no explanation, no markdown."""


def _model():
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=ANTI_AI_SYSTEM_INSTRUCTION,
    )


def _links_block() -> str:
    lines = []
    if settings.USER_LINKEDIN:
        lines.append(f"LinkedIn: {settings.USER_LINKEDIN}")
    if settings.USER_GITHUB:
        lines.append(f"GitHub: {settings.USER_GITHUB}")
    if settings.USER_PORTFOLIO:
        lines.append(f"Portfolio: {settings.USER_PORTFOLIO}")
    return "\n".join(lines)


def _template_cold_email(job: dict, profile: dict, contact_name: str = "", contact_title: str = "") -> dict:
    """Simple template-based email (fallback when Gemini quota is exceeded)."""
    name = profile.get('name', settings.USER_FULL_NAME)
    greeting = f"Hi {contact_name.split()[0]}," if contact_name else "Hi there,"
    company = job.get('company', 'the team')
    title = job.get('title', 'position')
    skills = ", ".join((profile.get("skills") or [])[:5])

    subject = f"Interested in {title} at {company}"
    body = f"""{greeting}

I'm {name}, and I'm interested in the {title} role at {company}. With experience in {skills}, I believe I'd be a great fit for your team.

I'd love to chat more about how I can contribute. Feel free to reach out!

Thanks,
{name}"""
    
    links = _links_block()
    if links:
        body = body.replace("Thanks,", f"{links}\n\nThanks,")
    
    return {"subject": subject, "body": body}


def _template_cover_letter(job: dict, profile: dict) -> str:
    """Simple template-based cover letter (fallback when Gemini quota is exceeded)."""
    name = profile.get('name', settings.USER_FULL_NAME)
    company = job.get('company', 'the company')
    title = job.get('title', 'position')
    skills = ", ".join((profile.get("skills") or [])[:5])
    years = profile.get('total_experience_years', 'several')
    
    return f"""Dear Hiring Team,

I'm writing to express my interest in the {title} position at {company}. With {years} years of experience in {skills}, I'm confident I can make an immediate impact on your team.

Throughout my career, I've developed a strong foundation in the skills your role requires. I'm particularly drawn to {company} because of your commitment to innovation and excellence.

I'd welcome the opportunity to discuss how my background aligns with your needs. Thank you for considering my application.

Best regards,
{name}"""


async def generate_cold_email(
    job: dict,
    profile: dict,
    contact_name: str = "",
    contact_title: str = "",
) -> dict:
    """Returns {"subject": str, "body": str}. Falls back to simple template if Gemini quota exceeded."""
    try:
        return await _generate_cold_email_gemini(job, profile, contact_name, contact_title)
    except Exception as e:
        error_str = str(e).lower()
        if "quota" in error_str or "429" in error_str or "rate" in error_str:
            print(f"[Email] Gemini quota exceeded, using template fallback")
            return _template_cold_email(job, profile, contact_name, contact_title)
        raise


async def _generate_cold_email_gemini(
    job: dict,
    profile: dict,
    contact_name: str = "",
    contact_title: str = "",
) -> dict:
    """Gemini-powered cold email generation."""
    skills_top = ", ".join((profile.get("skills") or [])[:8])
    exp_summary = ""
    for exp in (profile.get("experience") or [])[:2]:
        bullets = (exp.get("bullets") or [])[:2]
        exp_summary += f"- {exp.get('title')} at {exp.get('company')}: {'; '.join(bullets)}\n"

    greeting = f"Hi {contact_name.split()[0]}," if contact_name else "Hi there,"

    prompt = f"""Write a cold outreach email from a job seeker to a recruiter/hiring manager.

CANDIDATE:
Name: {profile.get('name', settings.USER_FULL_NAME)}
Top skills: {skills_top}
Recent experience:
{exp_summary}
Total experience: {profile.get('total_experience_years', '?')} years
LinkedIn: {settings.USER_LINKEDIN or 'not provided'}
GitHub: {settings.USER_GITHUB or 'not provided'}
Portfolio: {settings.USER_PORTFOLIO or 'not provided'}

TARGET JOB:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Job snippet: {(job.get('description') or '')[:500]}

CONTACT:
Name: {contact_name or 'the hiring team'}
Title: {contact_title or 'recruiter'}

GREETING TO USE: {greeting}

Format your output as:
SUBJECT: [subject line here]
---
[email body here]

The email must be 150-220 words. Be direct, specific, and genuinely interesting — not generic."""

    response = _model().generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.85, max_output_tokens=600),
    )
    raw = response.text.strip()

    subject, body = "", raw
    if "SUBJECT:" in raw and "---" in raw:
        parts = raw.split("---", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()

    links = _links_block()
    if links and links.split("\n")[0] not in body:
        body = body + "\n\n" + links

    return {"subject": subject, "body": body}


async def generate_cover_letter(job: dict, profile: dict) -> str:
    """Generate a 300-380 word human-like cover letter. Falls back to template if Gemini quota exceeded."""
    try:
        return await _generate_cover_letter_gemini(job, profile)
    except Exception as e:
        error_str = str(e).lower()
        if "quota" in error_str or "429" in error_str or "rate" in error_str:
            print(f"[Email] Gemini quota exceeded, using cover letter template fallback")
            return _template_cover_letter(job, profile)
        raise


async def _generate_cover_letter_gemini(job: dict, profile: dict) -> str:
    """Gemini-powered cover letter generation."""
    skills_top = ", ".join((profile.get("skills") or [])[:10])
    exp_detail = ""
    for e in (profile.get("experience") or [])[:3]:
        b = (e.get("bullets") or [])[:3]
        exp_detail += f"\n{e.get('title')} @ {e.get('company')} ({e.get('duration','')}):\n"
        exp_detail += "\n".join(f"  - {b_}" for b_ in b)

    edu = (profile.get("education") or [{}])[0]
    edu_str = f"{edu.get('degree','')} from {edu.get('school','')}" if edu else ""

    prompt = f"""Write a cover letter for this job application.

CANDIDATE:
Name: {profile.get('name', settings.USER_FULL_NAME)}
Email: {settings.USER_EMAIL}
Skills: {skills_top}
Experience ({profile.get('total_experience_years','?')} yrs):{exp_detail}
Education: {edu_str}

JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Description: {(job.get('description') or '')[:800]}

Write a cover letter that:
- Opens with something specific about the company, not "I am writing to apply for..."
- Mentions 2-3 concrete achievements with numbers from the experience above
- Shows genuine understanding of what the company does
- Is 300-380 words
- Ends naturally, not with boilerplate CTA
- Reads like a real person wrote it

Output ONLY the cover letter text."""

    response = _model().generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.85, max_output_tokens=800),
    )
    return response.text.strip()


async def generate_follow_up_email(
    job: dict, profile: dict, days_since: int = 7
) -> dict:
    """Short follow-up for an application sent X days ago. Falls back to template if Gemini quota exceeded."""
    try:
        return await _generate_follow_up_email_gemini(job, profile, days_since)
    except Exception as e:
        error_str = str(e).lower()
        if "quota" in error_str or "429" in error_str or "rate" in error_str:
            print(f"[Email] Gemini quota exceeded, using follow-up template fallback")
            name = profile.get('name', settings.USER_FULL_NAME)
            company = job.get('company', 'the company')
            return {
                "subject": f"Following up on {job.get('title')} at {company}",
                "body": f"Hi,\n\nJust following up on my recent application for the {job.get('title')} role. I remain very interested and happy to discuss further.\n\nThanks,\n{name}"
            }
        raise


async def _generate_follow_up_email_gemini(
    job: dict, profile: dict, days_since: int = 7
) -> dict:
    """Gemini-powered follow-up email generation."""
    prompt = f"""Write a short follow-up email. The candidate applied {days_since} days ago and hasn't heard back.

Job: {job.get('title')} at {job.get('company')}
Candidate: {profile.get('name', settings.USER_FULL_NAME)}

Rules:
- Max 80 words
- Reference the original application naturally
- Don't be needy or aggressive
- Mention one new relevant thought or a project that's relevant
- Casual, direct tone

Format:
SUBJECT: [subject]
---
[body]"""

    response = _model().generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.8, max_output_tokens=250),
    )
    raw = response.text.strip()
    subject, body = "", raw
    if "SUBJECT:" in raw and "---" in raw:
        parts = raw.split("---", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
    return {"subject": subject, "body": body}
