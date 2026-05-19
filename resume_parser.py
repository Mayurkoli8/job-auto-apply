"""
resume_parser.py — Extract structured profile from PDF/DOCX using pdfplumber + Gemini (free)
"""
from __future__ import annotations
import json
import re
from pathlib import Path
import pdfplumber
import google.generativeai as genai
from docx import Document
from config import settings
from database import ResumeProfile, AsyncSessionLocal
from datetime import datetime


def _configure_gemini():
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(settings.GEMINI_MODEL)


# ── Raw text extraction ──────────────────────────────────────────────────────

def extract_text_from_pdf(path: str) -> str:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


def extract_text_from_docx(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_raw_text(resume_path: str) -> str:
    path = Path(resume_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")
    if path.suffix.lower() == ".pdf":
        return extract_text_from_pdf(str(path))
    elif path.suffix.lower() in (".docx", ".doc"):
        return extract_text_from_docx(str(path))
    else:
        raise ValueError(f"Unsupported format: {path.suffix}")


# ── Gemini-powered structured extraction ─────────────────────────────────────

EXTRACTION_PROMPT = """You are a resume parser. Extract structured information from the resume text below.

Return ONLY valid JSON (no markdown, no explanation, no code fences) matching this exact schema:
{
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "location": "string or null",
  "summary": "2-3 sentence professional summary",
  "total_experience_years": 0.0,
  "skills": ["skill1", "skill2"],
  "experience": [
    {
      "company": "string",
      "title": "string",
      "duration": "string e.g. Jan 2021 - Present",
      "years": 0.0,
      "bullets": ["achievement1", "achievement2"]
    }
  ],
  "education": [
    {
      "school": "string",
      "degree": "string",
      "field": "string",
      "year": "string or null"
    }
  ],
  "certifications": ["cert1"],
  "languages": ["English"],
  "notable_projects": [
    {"name": "string", "description": "string", "tech": ["tech1"]}
  ],
  "keywords": ["keyword1", "keyword2"]
}

Resume text:
"""


def parse_resume_with_gemini(raw_text: str) -> dict:
    model = _configure_gemini()
    response = model.generate_content(
        EXTRACTION_PROMPT + raw_text,
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            max_output_tokens=2000,
        )
    )
    content = response.text.strip()
    # Strip any accidental markdown fences
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()
    return json.loads(content)


# ── Save to DB ───────────────────────────────────────────────────────────────

async def save_profile(profile_data: dict, raw_text: str):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(delete(ResumeProfile))
        profile = ResumeProfile(
            raw_text=raw_text,
            name=profile_data.get("name"),
            email=profile_data.get("email"),
            phone=profile_data.get("phone"),
            location=profile_data.get("location"),
            summary=profile_data.get("summary"),
            skills=profile_data.get("skills", []),
            experience=profile_data.get("experience", []),
            education=profile_data.get("education", []),
            certifications=profile_data.get("certifications", []),
            languages=profile_data.get("languages", []),
            total_experience_years=profile_data.get("total_experience_years", 0),
            parsed_at=datetime.utcnow()
        )
        session.add(profile)
        await session.commit()
        return profile


async def load_profile() -> dict | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ResumeProfile).limit(1))
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
            "location": row.location,
            "summary": row.summary,
            "skills": row.skills or [],
            "experience": row.experience or [],
            "education": row.education or [],
            "certifications": row.certifications or [],
            "total_experience_years": row.total_experience_years,
            "raw_text": row.raw_text,
        }


async def parse_and_save_resume(resume_path: str = None) -> dict:
    path = resume_path or settings.RESUME_PATH
    print(f"[Resume] Parsing: {path}")
    raw = extract_raw_text(path)
    print(f"[Resume] Extracted {len(raw)} chars. Sending to Gemini...")
    profile = parse_resume_with_gemini(raw)
    await save_profile(profile, raw)
    print(f"[Resume] Parsed: {profile.get('name')} | "
          f"{len(profile.get('skills', []))} skills | "
          f"{profile.get('total_experience_years', 0)} yrs exp")
    return profile
