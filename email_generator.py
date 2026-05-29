"""
email_generator.py - Professional default cold email and cover letter templates.
"""
from __future__ import annotations
from config import settings

def _contact_signature(profile: dict) -> str:
    name = profile.get("name") or settings.USER_FULL_NAME
    email = settings.USER_EMAIL or profile.get("email") or ""
    phone = settings.USER_PHONE or profile.get("phone") or ""

    lines = [name]
    if email: lines.append(f"Email: {email}")
    if phone: lines.append(f"Phone: {phone}")
    if settings.USER_LINKEDIN: lines.append(f"LinkedIn: {settings.USER_LINKEDIN}")
    if settings.USER_GITHUB: lines.append(f"GitHub: {settings.USER_GITHUB}")
    if settings.USER_PORTFOLIO: lines.append(f"Portfolio: {settings.USER_PORTFOLIO}")
    if settings.RESUME_URL: lines.append(f"Resume: {settings.RESUME_URL}")
    else: lines.append("Resume: attached")
    return "\n".join(lines)

def _template_cold_email(job: dict, profile: dict) -> dict:
    """Robust, professional default template that works for every company."""
    name = profile.get('name', settings.USER_FULL_NAME)
    title = (job.get('title') or 'the role').strip()
    company = job.get('company', 'your company')

    subject = f"AI / Backend Engineer Application - {name} ({title})"
    body = f"""Hi there,

I recently saw the {title} opening at {company} and wanted to reach out directly.

I'm a Computer Engineering graduate with a strong background in AI, Backend services, and automation. My recent work includes building FastAPI services, implementing LLM/RAG workflows, and creating automated data pipelines. I focus on shipping practical, production-ready code that solves real business problems.

I believe my technical skills and proactive approach to building AI-assisted tools would be a great addition to the {company} team.

I've attached my resume and included my portfolio links below. I'd love to share more about my relevant projects and discuss how I can contribute to your goals.

Thanks,
{name}

{_contact_signature(profile)}"""

    return {"subject": subject, "body": body}

def _template_cover_letter(job: dict, profile: dict) -> str:
    name = profile.get('name', settings.USER_FULL_NAME)
    title = (job.get('title') or 'the role').strip()
    company = job.get('company', 'your company')
    
    return f"""Dear Hiring Team at {company},

I'm writing to express my interest in the {title} position. As a Computer Engineering graduate focusing on AI and Backend engineering, I have developed a deep understanding of building scalable services and integrating modern AI technologies.

My hands-on experience includes developing FastAPI applications, fine-tuning LLM implementations, and optimizing RAG workflows for efficient data retrieval. I thrive in environments where I can learn quickly and apply new technologies to shipping practical features.

I am particularly impressed with {company}'s work in this space and am eager to contribute to your continued success. I've attached my resume for your review and am available for a discussion at your convenience.

Thanks,
{name}

{_contact_signature(profile)}"""

async def generate_cold_email(job: dict, profile: dict, **kwargs) -> dict:
    """Returns {"subject": str, "body": str}. Uses the professional default template."""
    return _template_cold_email(job, profile)

async def generate_cover_letter(job: dict, profile: dict) -> str:
    """Generate a professional cover letter using the default template."""
    return _template_cover_letter(job, profile)

async def generate_follow_up_email(job: dict, profile: dict, days_since: int = 7) -> dict:
    name = profile.get('name', settings.USER_FULL_NAME)
    title = (job.get('title') or 'the role').strip()
    return {
        "subject": f"Following up: {title} application - {name}",
        "body": f"Hi there,\n\nJust following up on my application for the {title} role. I'm still very interested in joining the team and would be happy to provide any extra details or code samples that would help.\n\nThanks,\n{name}\n\n{_contact_signature(profile)}"
    }
