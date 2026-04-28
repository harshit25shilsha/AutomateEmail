import os
import json, re
from functools import lru_cache

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from resume_analyzer.schemas import ResumeAnalysisResult



VALID_DOMAINS = [
    "Python Developer", "React Developer", "Java Developer",
    "Node.js Developer", "Angular Developer", "Vue.js Developer",
    "Full Stack Developer", "Flutter Developer", "Android Developer",
    "iOS Developer", "Data Analyst", "Data Scientist",
    "DevOps Engineer", "UI/UX Designer", "QA Engineer", "HR", "General",
]


@lru_cache(maxsize=1)
def _get_llm() -> ChatGroq:

    return ChatGroq(
        model="deepseek-r1-distill-llama-70b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,     
        max_tokens=700,
        max_retries=3,        
    )


def _get_parser() -> JsonOutputParser:
    return JsonOutputParser(pydantic_object=ResumeAnalysisResult)


def _get_prompt(parser: JsonOutputParser) -> PromptTemplate:
    template = """You are an expert technical recruiter and resume analyst.

Analyze the following resume data and return a structured JSON response.

Candidate Information:
- Name: {name}
- Skills: {skills}
- Total Experience: {experience_years} years
- Number of Work Experiences: {experience_entries}
- Education entries: {education_count}
- Projects: {projects_count}
- Certifications: {certifications_count}
- Resume Text Snippet:
{raw_text_snippet}

You MUST choose domain from ONLY this list:
{valid_domains}

Scoring guide (total 100 pts):
- Skills match for detected domain : 30 pts
- Work experience quality/duration : 30 pts
- Education background             : 20 pts
- Projects, certifications, quality: 20 pts

Level guide:
- Fresher   = 0 to 1 year
- Mid-Level = 2 to 4 years
- Senior    = 5 or more years

Filename format  : FirstName_LastName_DomainSlug_NYrs.pdf
                   Example: John_Doe_Python_Developer_3Yrs.pdf
                   Use 0Yrs for freshers. No spaces, underscores only.

Folder format    : Candidates/DomainSlug/
                   Example: Candidates/Python_Developer/

Summary format   : One professional sentence.
                   Example: Backend Python developer with 3 years of experience in Django and REST APIs.

{format_instructions}
"""
    return PromptTemplate(
        template=template,
        input_variables=[
            "name",
            "skills",
            "experience_years",
            "experience_entries",
            "education_count",
            "projects_count",
            "certifications_count",
            "raw_text_snippet",
            "valid_domains",
        ],
        partial_variables={
            "format_instructions": _get_parser().get_format_instructions(),
        },
    )


def _build_chain():
    parser = _get_parser()
    prompt = _get_prompt(parser)
    llm    = _get_llm()

    chain = prompt | llm | parser
    return chain


_chain = None

def _get_chain():
    global _chain
    if _chain is None:
        _chain = _build_chain()
    return _chain


def _build_chain_input(parsed_resume: dict) -> dict:
    name      = (parsed_resume.get("name") or "Candidate").strip()
    skills    = parsed_resume.get("skills") or []
    work_exp  = parsed_resume.get("experience") or []
    education = parsed_resume.get("education") or []
    projects  = parsed_resume.get("projects") or []
    certs     = parsed_resume.get("certifications") or []
    raw_text  = (parsed_resume.get("raw_text") or "")[:2500]  

    exp_years = _calculate_exp_years(work_exp)

    return {
        "name":               name,
        "skills":             ", ".join(str(s) for s in skills[:25]),
        "experience_years":   exp_years,
        "experience_entries": len(work_exp),
        "education_count":    len(education),
        "projects_count":     len(projects),
        "certifications_count": len(certs),
        "raw_text_snippet":   raw_text,
        "valid_domains":      "\n".join(f"  - {d}" for d in VALID_DOMAINS),
    }


def _calculate_exp_years(work_experiences: list) -> float:
    """Calculate total experience years from structured work_experience list."""
    if not work_experiences:
        return 0.0
    try:
        from dateutil import parser as date_parser
        from datetime import datetime
        from zoneinfo import ZoneInfo

        total_months = 0
        for w in work_experiences:
            if not isinstance(w, dict):
                continue
            sd = w.get("startDate")
            ed = w.get("endDate")
            if not sd:
                continue
            try:
                start = date_parser.parse(str(sd))
                end   = (
                    date_parser.parse(str(ed))
                    if ed and str(ed).lower() not in ("present", "current")
                    else datetime.now(ZoneInfo("Asia/Kolkata"))
                )
                diff = (end.year - start.year) * 12 + (end.month - start.month)
                total_months += max(0, diff)
            except Exception:
                continue
        return round(total_months / 12, 1)
    except Exception:
        return float(len(work_experiences))


DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "Python Developer":     ["python", "django", "flask", "fastapi"],
    "React Developer":      ["react", "redux", "nextjs", "jsx"],
    "Java Developer":       ["java", "spring", "springboot", "hibernate"],
    "Node.js Developer":    ["nodejs", "node.js", "express", "nestjs"],
    "Angular Developer":    ["angular", "rxjs"],
    "Vue.js Developer":     ["vue", "vuex", "nuxt"],
    "Full Stack Developer": ["fullstack", "full stack", "mern", "mean"],
    "Flutter Developer":    ["flutter", "dart"],
    "Android Developer":    ["android", "kotlin"],
    "iOS Developer":        ["ios", "swift"],
    "Data Analyst":         ["tableau", "powerbi", "data analysis", "excel"],
    "Data Scientist":       ["machine learning", "tensorflow", "pytorch", "nlp"],
    "DevOps Engineer":      ["docker", "kubernetes", "jenkins", "terraform"],
    "UI/UX Designer":       ["figma", "wireframe", "prototyping", "ui/ux"],
    "QA Engineer":          ["selenium", "cypress", "jest", "qa", "testing"],
    "HR":                   ["recruitment", "talent acquisition", "hris"],
}

def _rule_based_fallback(parsed_resume: dict) -> dict:
    text      = json.dumps(parsed_resume).lower()
    scores    = {d: sum(1 for kw in kws if kw in text) for d, kws in DOMAIN_KEYWORDS.items()}
    domain    = max(scores, key=scores.get) if max(scores.values()) > 0 else "General"

    name      = (parsed_resume.get("name") or "Candidate").strip()
    skills    = [str(s) for s in (parsed_resume.get("skills") or [])[:8]]
    work_exp  = parsed_resume.get("experience") or []
    exp_years = _calculate_exp_years(work_exp)

    level = (
        "Fresher"   if exp_years <= 1 else
        "Mid-Level" if exp_years <= 4 else
        "Senior"
    )

    safe_name   = re.sub(r"[^A-Za-z0-9]", "_", name).strip("_") or "Candidate"
    domain_slug = re.sub(r"[^A-Za-z0-9]", "_", domain).strip("_")
    filename    = f"{safe_name}_{domain_slug}_{int(exp_years)}Yrs.pdf"
    folder      = f"Candidates/{domain_slug}/"

    print(f"[ANALYZER] Rule-based fallback → {domain}")
    return {
        "domain":   domain,
        "skills":   skills,
        "level":    level,
        "score":    50.0,
        "summary":  f"{domain} with {exp_years} year(s) of experience.",
        "filename": filename,
        "folder":   folder,
    }

def run_chain(parsed_resume: dict) -> dict:
    try:
        chain_input = _build_chain_input(parsed_resume)
        chain       = _get_chain()

        print(f"[ANALYZER] Running LangChain chain for: {chain_input['name']}")
        result = chain.invoke(chain_input)

        print(
            f"[ANALYZER] ✓ Chain success → {result.get('domain')} | "
            f"Score: {result.get('score')} | Level: {result.get('level')}"
        )
        return result

    except Exception as e:
        print(f"[ANALYZER] Chain failed ({e}), using rule-based fallback")
        return _rule_based_fallback(parsed_resume)