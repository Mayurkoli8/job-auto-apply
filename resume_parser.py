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


def build_fallback_profile(raw_text: str) -> dict:
    text = raw_text.replace('\r', '\n')
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def section_key(line: str) -> str | None:
        lower = line.lower()
        if 'professional summary' in lower or lower == 'summary' or 'about me' in lower:
            return 'summary'
        if 'academic qualifications' in lower or lower == 'education':
            return 'education'
        if lower in {'skills', 'technical skills', 'technologies'} or lower.startswith('skills:') or lower.startswith('technical skills:') or lower.startswith('technologies:'):
            return 'skills'
        if lower == 'experience' or lower.startswith('experience ') or lower.startswith('experience:') or lower.endswith(' experience') or lower.endswith(' experience:'):
            return 'experience'
        if 'project' in lower and len(lower) < 40:
            return 'projects'
        if lower in {'certifications', 'certification', 'training'} or lower.startswith('certifications:') or lower.startswith('certification:') or lower.startswith('training:'):
            return 'certifications'
        if 'achievement' in lower and len(lower) < 40:
            return 'achievements'
        if lower in {'languages', 'language'} or lower.startswith('languages:') or lower.startswith('language:'):
            return 'languages'
        return None

    sections: dict[str, list[str]] = {'header': []}
    current_section = 'header'
    for line in lines:
        key = section_key(line)
        if key:
            current_section = key
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)

    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw_text)
    phone_match = re.search(r"(\+?\d[\d\s\-\(\)]{7,}\d)", raw_text)

    contact_line = next((line for line in sections['header'] if '@' in line or 'location' in line.lower()), '')
    location = None
    if 'location:' in contact_line.lower():
        location = re.search(r'location:\s*([^|]+)', contact_line, re.IGNORECASE)
        location = location.group(1).strip() if location else None
    elif '|' in contact_line:
        parts = [part.strip() for part in contact_line.split('|')]
        loc_parts = [part for part in parts if 'location' in part.lower()]
        if loc_parts:
            location = re.search(r'location:\s*(.+)', loc_parts[0], re.IGNORECASE)
            location = location.group(1).strip() if location else loc_parts[0]
        else:
            for part in parts:
                if re.match(r'[A-Za-z].+', part) and 'github' not in part.lower() and 'linkedin' not in part.lower() and '@' not in part:
                    location = part
                    break

    def parse_skills(skill_lines: list[str]) -> list[str]:
        skills = []
        for line in skill_lines:
            line = line.replace('•', '').replace('�', '').strip()
            if ':' in line:
                _, values = line.split(':', 1)
            else:
                values = line
            parts = re.split(r'[|,;\n]', values)
            for part in parts:
                cleaned = part.strip()
                if cleaned and len(cleaned) > 1:
                    skills.append(cleaned)
        return skills

    skills = parse_skills(sections.get('skills', []))
    if not skills:
        skills = parse_skills([line for line in sections.get('header', []) if 'python' in line.lower() or 'fastapi' in line.lower()])
    skills = list(dict.fromkeys(skills))[:30]

    def parse_summary(summary_lines: list[str]) -> str:
        if summary_lines:
            return ' '.join(summary_lines[:3]).strip()
        return 'Resume parsed without AI. Please verify the extracted data.'

    def parse_education(education_lines: list[str]) -> list[dict]:
        edu = []
        for line in education_lines:
            if line and any(token.isdigit() for token in line):
                edu.append({
                    'school': line,
                    'degree': '',
                    'field': '',
                    'year': ''
                })
        return edu

    def parse_experience(experience_lines: list[str]) -> list[dict]:
        experience = []
        current = None

        def clean_bullet(line: str) -> str:
            return line.lstrip("-•▪•	\n\r ").strip()

        for line in experience_lines:
            if line.startswith(("-", "•", "▪", "•")):
                bullet = clean_bullet(line)
                if current is not None and bullet:
                    current["bullets"].append(bullet)
                continue
            if "|" in line:
                parts = [part.strip() for part in line.split("|")]
                title = parts[0]
                company = parts[1] if len(parts) >= 2 else ""
                duration = ""
                if len(parts) >= 3:
                    duration = parts[2]
                else:
                    date_match = re.search(r"((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Present|\d{4}).*)$", company)
                    if date_match:
                        duration = date_match.group(1).strip()
                        company = company[:date_match.start()].strip()
                current = {
                    "company": company,
                    "title": title,
                    "duration": duration,
                    "years": 0.0,
                    "bullets": []
                }
                experience.append(current)
            elif line and current is None:
                current = {
                    "company": "",
                    "title": line,
                    "duration": "",
                    "years": 0.0,
                    "bullets": []
                }
                experience.append(current)
            elif line and current is not None:
                current["bullets"].append(clean_bullet(line))
        return experience
    name = sections['header'][0] if sections['header'] else 'Unknown'
    summary = parse_summary(sections.get('summary', []))
    education = parse_education(sections.get('education', []))
    experience = parse_experience(sections.get('experience', []))

    if not education and sections.get('header'):
        education = parse_education(sections['header'])

    return {
        'name': name,
        'email': email_match.group(0) if email_match else None,
        'phone': phone_match.group(0).strip() if phone_match else None,
        'location': location,
        'summary': summary,
        'total_experience_years': 0.0,
        'skills': skills,
        'experience': experience,
        'education': education,
        'certifications': sections.get('certifications', []),
        'languages': sections.get('languages', ['English']),
        'notable_projects': [],
        'keywords': skills[:10] if skills else [],
    }


def parse_resume_with_gemini(raw_text: str) -> dict:
    if not settings.GEMINI_API_KEY:
        print("[Resume Parser] No GEMINI_API_KEY configured — using fallback parser")
        return build_fallback_profile(raw_text)

    try:
        model = _configure_gemini()
        response = model.generate_content(
            EXTRACTION_PROMPT + raw_text,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2000,
            )
        )
        content = response.text.strip()
    except Exception as e:
        print(f"[Resume Parser] Gemini API failure: {e}")
        return build_fallback_profile(raw_text)

    # Strip any accidental markdown fences
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()

    # Try to extract JSON if wrapped in other text
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    # Attempt progressive sanitization of Gemini output to handle
    # common model formatting issues (trailing commas, control chars,
    # and single-quote strings) before falling back.
    def _sanitize_candidate(cand: str) -> str:
        # Remove low-control characters that break JSON parsing
        cand = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', ' ', cand)
        # Remove trailing commas before closing braces/brackets
        cand = re.sub(r',\s*([}\]])', r"\1", cand)
        # Heuristic: if single quotes are much more common than double
        # quotes, try converting single->double quotes (models sometimes
        # emit python-style dicts)
        if cand.count("'") > cand.count('"'):
            cand = cand.replace("'", '"')
        return cand

    # Try raw parse first, then apply sanitizers progressively
    for attempt, candidate in enumerate([content, _sanitize_candidate(content)], start=1):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            # provide concise debug info for each attempt
            print(f"[Resume Parser] JSON decode attempt {attempt} failed: {e}")
            if attempt == 1:
                # show a short snippet only on first failure
                print(f"[Resume Parser] Snippet: {candidate[:200]}")
            continue

    # Last resort: give up and use fallback parser
    print("[Resume Parser] All JSON parsing attempts failed; using fallback parser")
    return build_fallback_profile(raw_text)


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
