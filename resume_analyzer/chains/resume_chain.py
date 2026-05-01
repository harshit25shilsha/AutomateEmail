from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

from resume_analyzer.schemas import ResumeAnalysisResult

log = logging.getLogger(__name__)

EXAMPLE_DOMAINS: list[str] = [
    "Python Developer",
    "React Developer",
    "Java Developer",
    "Node.js Developer",
    "Angular Developer",
    "Vue.js Developer",
    "Full Stack Developer",
    "Flutter Developer",
    "Android Developer",
    "iOS Developer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "UI/UX Designer",
    "QA Engineer",
    "HR",
    "Blockchain Developer",
    "Embedded Systems Engineer",
    "Cybersecurity Engineer",
    "Game Developer",
]


@lru_cache(maxsize=1)
def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        max_tokens=900,
        max_retries=3,
    )


_PROMPT_TEMPLATE = """\
You are a senior technical recruiter with 15 years of experience.
Analyze the resume data below and return ONLY a valid JSON object — no markdown, no preamble, no explanation.

════════════════════════════════════
CANDIDATE DATA
════════════════════════════════════
Name                : {name}
Email               : {email}
Profile Summary     : {profile_summary}
Skills              : {skills}
Total Experience    : {experience_years}
Work Entries        : {experience_entries}
Education Entries   : {education_count}
Projects            : {projects_count}
Certifications      : {certifications_count}

Resume Text (first 2500 chars):
{raw_text_snippet}

════════════════════════════════════
INSTRUCTIONS
════════════════════════════════════

1. DOMAIN
   - Carefully read the candidate's PRIMARY tech stack, job title, and most recent role.
   - Infer the most precise and accurate job domain from the resume itself.
   - Write the domain as a clean professional title, e.g.:
       "React Developer", "Node.js Developer", "Python Developer",
       "Data Scientist", "DevOps Engineer", "UI/UX Designer", etc.
   - The following are EXAMPLES for reference — you are NOT limited to this list.
     If the candidate has a niche role (e.g. "Blockchain Developer", "Embedded Systems Engineer",
     "Site Reliability Engineer"), use that exact title:
{example_domains}
   - Rules:
       ── FRONTEND ───────────────────────────────────────────────────────
       • Primarily React / Redux / Next.js / React Native (web)     → React Developer
       • Primarily Angular / RxJS / NgRx / Angular Material         → Angular Developer
       • Primarily Vue.js / Vuex / Nuxt.js                          → Vue.js Developer
       • Primarily HTML / CSS / SASS / jQuery / Bootstrap (no FW)   → Frontend Developer
       • Primarily React Native / Expo (mobile focus)                → React Native Developer

       ── BACKEND ────────────────────────────────────────────────────────
       • Primarily Node.js / Express / NestJS (backend focus)        → Node.js Developer
       • Primarily Python / Django / Flask / FastAPI                 → Python Developer
       • Primarily Java / Spring / SpringBoot / Hibernate             → Java Developer
       • Primarily C# / .NET / ASP.NET / Entity Framework           → .NET Developer
       • Primarily Go / Golang                                       → Golang Developer

       ── FULL STACK ──────────────────────────────────────────────────────
       • Equal React + Node, or MERN / MEAN / MEVN stack title      → Full Stack Developer
       • SDE Intern with MERN / MEAN / full-stack project            → Full Stack Developer
       • Next.js + Node.js / Prisma with equal frontend+backend     → Full Stack Developer

       ── MOBILE ─────────────────────────────────────────────────────────
       • Primarily Flutter / Dart                                    → Flutter Developer
       • Primarily Swift / SwiftUI / Xcode / iOS SDK                 → iOS Developer
       • Primarily Kotlin / Jetpack Compose / Android SDK            → Android Developer

       ── DATA & AI ───────────────────────────────────────────────────────
       • Primarily ML / TensorFlow / PyTorch / Scikit-learn / NLP   → Machine Learning Engineer
       • Primarily LLMs / LangChain / RAG / Prompt Engineering      → AI/ML Engineer
       • Primarily Tableau / Power BI / Looker / data analysis      → Data Analyst
       • Primarily Spark / Hadoop / Airflow / ETL pipelines          → Data Engineer
       • Primarily statistics / R / Python (analysis + modeling)    → Data Scientist

       ── DEVOPS & CLOUD ──────────────────────────────────────────────────
       • Primarily Docker / Kubernetes / Terraform / CI-CD          → DevOps Engineer
       • Primarily AWS / GCP / Azure architecture and services      → Cloud Engineer

       ── FALLBACK ────────────────────────────────────────────────────────
       • Resume is completely unclear or unrelated to above          → General

   - Hard Rules:
       • Do NOT assign a domain based on one minor library mention.
       • Always prefer the most specific domain over a generic one.
       • Never use "General" if any tech pattern is detectable.

2. SKILLS
   - List the top 10-20 skills extracted directly from the resume.
   - Use exact short names: "React.js", "Node.js", "Redux", "NestJS", "AWS", "PostgreSQL".

3. LEVEL  (based ONLY on experience_years above)
   Fresher   = 0 – 1 year   (includes internships < 1 year)
   Mid-Level = 2 – 4 years
   Senior    = 5+ years

4. SCORE  (integer 0–100, never blindly return 50)
   Skills match for detected domain  : 30 pts max
   Work experience quality           : 30 pts max
   Education background              : 20 pts max
   Projects + certifications         : 20 pts max

5. SUMMARY — one concise professional sentence, 15–25 words.
   Format : "<Role> with <exp> of experience in <top 2–3 skills>."
   Examples:
     "React developer with 3 years of experience in Redux, Next.js, and RESTful APIs."
     "Full Stack developer with 6 months of experience in React, Node.js, and MongoDB."
   Use the EXACT experience label provided: {exp_label}
   Use the candidate's ACTUAL role and skills — never use placeholder text.

6. FILENAME : Use EXACTLY this value: {exp_label}
   Format: FirstName_LastName_DomainSlug_{exp_label}.pdf
   Example with years : Ariba_Nusra_React_Developer_3Yrs.pdf
   Example with months: Sakshi_Semwal_Full_Stack_Developer_3Months.pdf
   Rules: underscores only, no spaces.

7. FOLDER   : Candidates/DomainSlug/
   Example   : Candidates/React_Developer/
   Must match the domain from step 1, slugified with underscores.

{format_instructions}
"""


def _format_exp(exp_years: float) -> str:
    if exp_years < 1.0:
        months = round(exp_years * 12)
        return f"{months}Months" if months > 0 else "0Months"
    return f"{int(exp_years)}Yrs"


def _format_exp_text(exp_years: float) -> str:
    if exp_years < 1.0:
        months = round(exp_years * 12)
        return f"{months} month{'s' if months != 1 else ''}"
    yrs = int(exp_years)
    return f"{yrs} year{'s' if yrs != 1 else ''}"


def _build_chain():
    parser = JsonOutputParser(pydantic_object=ResumeAnalysisResult)
    prompt = PromptTemplate(
        template=_PROMPT_TEMPLATE,
        input_variables=[
            "name", "email", "profile_summary", "skills",
            "experience_years", "exp_label", "experience_entries",
            "education_count", "projects_count", "certifications_count",
            "raw_text_snippet", "example_domains",
        ],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )
    return prompt | _get_llm() | parser


_chain = None


def _get_chain():
    global _chain
    if _chain is None:
        _chain = _build_chain()
    return _chain


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    s = raw.strip()
    if s.lower() in ("present", "current", "till date", "ongoing", "now", ""):
        return datetime.now(ZoneInfo("Asia/Kolkata"))

    s = re.sub(
        r'^([A-Za-z]+)\s+(\d{2})$',
        lambda m: f"{m.group(1)} {2000 + int(m.group(2))}",
        s
    )

    formats = [
        "%Y-%m",
        "%b %Y",
        "%B %Y",
        "%m/%Y",
        "%b-%Y",
        "%B-%Y",
        "%Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    try:
        from dateutil import parser as dp
        return dp.parse(s, default=datetime(2000, 1, 1))
    except Exception:
        return None


def _calculate_exp_years(work_experiences: list) -> float:
    if not work_experiences:
        return 0.0

    now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    intervals: list[tuple[datetime, datetime]] = []

    for entry in work_experiences:
        if not isinstance(entry, dict):
            continue

        sd_raw = (
            entry.get("startDate") or entry.get("start_date") or
            entry.get("from") or ""
        )
        ed_raw = (
            entry.get("endDate") or entry.get("end_date") or
            entry.get("to") or "present"
        )

        if not sd_raw:
            log.warning("[EXP] Skipping entry with no startDate: %s", entry)
            continue

        start = _parse_date(str(sd_raw))
        end = _parse_date(str(ed_raw)) if ed_raw else now

        if start is None:
            log.warning("[EXP] Could not parse startDate: %r", sd_raw)
            continue
        if end is None:
            end = now

        if hasattr(start, "tzinfo") and start.tzinfo:
            start = start.replace(tzinfo=None)
        if hasattr(end, "tzinfo") and end.tzinfo:
            end = end.replace(tzinfo=None)

        end = min(end, now)

        if end > start:
            intervals.append((start, end))
        else:
            log.warning("[EXP] Skipping invalid interval: %s → %s", start, end)

    if not intervals:
        return 0.0

    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [intervals[0]]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    total_days = sum((e - s).days for s, e in merged)
    result = round(total_days / 365.25, 1)
    log.info("[EXP] Total: %.1f years from %d merged intervals", result, len(merged))
    return result


def _calculate_exp_years_from_parsed(parsed: dict) -> float:
    work_exp = parsed.get("work_experiences") or []
    work_exp = [e for e in work_exp if isinstance(e, dict) and e.get("startDate")]

    if work_exp:
        return _calculate_exp_years(work_exp)

    llm_exp = parsed.get("experience") or []
    llm_exp = [e for e in llm_exp if isinstance(e, dict) and e.get("startDate")]

    if llm_exp:
        return _calculate_exp_years(llm_exp)

    return 0.0


def _slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def _level(exp_years: float) -> str:
    if exp_years < 1:
        return "Fresher"
    if exp_years <= 4:
        return "Mid-Level"
    return "Senior"


def _build_filename(name: str, domain: str, exp_years: float) -> str:
    safe_name = _slugify(name) or "Candidate"
    domain_slug = _slugify(domain)
    exp_str = _format_exp(exp_years)
    return f"{safe_name}_{domain_slug}_{exp_str}.pdf"


def _build_folder(domain: str) -> str:
    return f"Candidates/{_slugify(domain)}/"


def _build_chain_input(parsed: dict, exp_years: float) -> dict:
    name = (parsed.get("name") or "Candidate").strip()
    email = parsed.get("email") or ""
    skills = parsed.get("skills") or []

    work_exp = parsed.get("work_experiences") or []
    work_exp = [e for e in work_exp if isinstance(e, dict)]
    if not work_exp:
        work_exp = [e for e in (parsed.get("experience") or []) if isinstance(e, dict)]

    raw_text = (parsed.get("raw_text") or "")[:2500]
    profile_summary = parsed.get("summary") or parsed.get("profile") or raw_text[:300]

    return {
        "name": name,
        "email": email,
        "profile_summary": profile_summary,
        "skills": ", ".join(str(s) for s in skills[:25]),
        "experience_years": _format_exp_text(exp_years),
        "exp_label": _format_exp(exp_years),
        "experience_entries": len(work_exp),
        "education_count": len(parsed.get("education") or []),
        "projects_count": len(parsed.get("projects") or []),
        "certifications_count": len(parsed.get("certifications") or []),
        "raw_text_snippet": raw_text,
        "example_domains": "\n".join(f"     • {d}" for d in EXAMPLE_DOMAINS),
    }


def _rule_based_fallback(parsed: dict) -> dict:
    exp_years = _calculate_exp_years_from_parsed(parsed)

    raw_text = (parsed.get("raw_text") or json.dumps(parsed)).lower()
    name = (parsed.get("name") or "Candidate").strip()
    skills = [str(s) for s in (parsed.get("skills") or [])[:10]]

    hints = {
        "React Developer": ["react", "redux", "next.js"],
        "Node.js Developer": ["node.js", "nodejs", "nestjs"],
        "Python Developer": ["python", "django", "flask", "fastapi"],
        "Java Developer": ["java", "spring"],
        "Full Stack Developer": ["mern", "mean", "full stack", "fullstack"],
        "Machine Learning Engineer": ["machine learning", "tensorflow", "pytorch"],
        "Data Analyst": ["tableau", "power bi", "data analysis"],
        "DevOps Engineer": ["docker", "kubernetes", "terraform"],
        "UI/UX Designer": ["figma", "wireframe", "ux"],
        "Flutter Developer": ["flutter", "dart"],
        "QA Engineer": ["selenium", "cypress", "playwright"],
        "HR": ["recruitment", "talent acquisition"],
    }

    best_domain, best_score = "General", 0
    for domain, kws in hints.items():
        score = sum(1 for kw in kws if kw in raw_text)
        if score > best_score:
            best_domain, best_score = domain, score

    top_skills = ", ".join(skills[:3]) or "relevant technologies"

    return {
        "domain": best_domain,
        "skills": skills,
        "level": _level(exp_years),
        "score": 50.0,
        "summary": f"{best_domain} with {_format_exp_text(exp_years)} of experience in {top_skills}.",
        "filename": _build_filename(name, best_domain, exp_years),
        "folder": _build_folder(best_domain),
    }


async def run_chain(parsed_resume: dict) -> dict:
    exp_years = _calculate_exp_years_from_parsed(parsed_resume)

    try:
        chain_input = _build_chain_input(parsed_resume, exp_years)
        result = await _get_chain().invoke(chain_input)

        domain = (result.get("domain") or "General").strip()
        name = (parsed_resume.get("name") or "Candidate").strip()

        result["domain"] = domain
        result["filename"] = _build_filename(name, domain, exp_years)
        result["folder"] = _build_folder(domain)

        summary = result.get("summary", "")
        if not summary or len(summary) < 20 or "john doe" in summary.lower():
            skills_list = result.get("skills") or []
            top_skills = ", ".join(str(s) for s in skills_list[:3]) or "relevant technologies"
            result["summary"] = (
                f"{domain} with {_format_exp_text(exp_years)} of experience in {top_skills}."
            )

        return result

    except Exception as exc:
        log.error("[CHAIN] LLM failed (%s: %s) — using fallback", type(exc).__name__, exc)
        return _rule_based_fallback(parsed_resume)