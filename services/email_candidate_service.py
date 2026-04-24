import os
import re
import json
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from groq import Groq
from fastapi import UploadFile
from urllib.parse import urlparse
from models.candidate import Candidate

from services.resume_service import (
    extract_text,
    extract_text_and_links,       
    parse_resume_text,
    parse_with_llm,
    sanitize_text,
    upload_file_to_s3,
    parse_work_experiences,
    parse_education_items,
    parse_projects,
    normalize_date,
    _clean_work_experience,   
    _split_role_company,  
    _is_tech_string,  
)

class _FileWrapper:
    def __init__(self, filename: str, file_path: str):
        self.filename = filename
        self._path    = file_path
        self.file     = open(file_path, "rb")

    def seek(self, pos):
        self.file.seek(pos)

    def close(self):
        self.file.close()


def _is_resume_file(filename: str) -> bool:
    if not filename:
        return False
    return filename.lower().endswith((".pdf", ".docx"))


def _build_work_experiences(llm_exp):
    result = []
    for exp in llm_exp:
        if not isinstance(exp, dict):
            continue
        company = exp.get("company", "") or ""
        role = exp.get("role", "") or ""
        
        if _is_tech_string(company) and not exp.get("startDate"):
            continue

        end_raw = (exp.get("endDate", "") or "").strip()
        is_current = end_raw.lower() in ("present", "current")
        
        entry = {
            "candidateId":        None,
            "workExperienceId":   None,
            "role":               role,
            "companyName":        company,
            "startDate":          normalize_date(exp.get("startDate", "")),
            "endDate":            None if is_current else normalize_date(end_raw) if end_raw else None,
            "isCurrentlyWorking": is_current,
        }
        entry = _split_role_company(entry)
        entry = _clean_work_experience(entry)
        
        if not entry.get("companyName"):
            continue
            
        result.append(entry)
    return result


def _build_educations(llm_edu):
    degree_type_map = {
        "master": "POST_GRADUATION", "mba": "POST_GRADUATION",
        "mca": "POST_GRADUATION",    "m.tech": "POST_GRADUATION",
        "m.sc": "POST_GRADUATION",   "ph.d": "DOCTORATE",
        "doctorate": "DOCTORATE",    "10th": "SCHOOLING",
        "12th": "SCHOOLING",         "intermediate": "SCHOOLING",
        "senior secondary": "SCHOOLING", "high school": "SCHOOLING",
        "ssc": "SCHOOLING",          "hsc": "SCHOOLING",
    }
    now_str  = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    edu_list = []
    for edu in llm_edu:
        if not isinstance(edu, dict):
            continue
        degree      = edu.get("degree", "") or ""
        institution = edu.get("institution", "") or ""
        edu_type    = "GRADUATION"
        for kw, et in degree_type_map.items():
            if kw in degree.lower():
                edu_type = et
                break
        edu_list.append({
            "educationId":     None,
            "type":            edu_type,
            "institutionName": institution,
            "passingYear":     edu.get("year", ""),
            "degreeName":      degree,
            "board":           edu.get("board", ""),
            "percentage":      edu.get("percentage", ""),
            "university":      institution,
            "createdAt":       now_str,
            "updatedAt":       now_str,
            "educationStatus": "COMPLETED",
        })
    return edu_list


def _extract_projects_from_experience(work_experiences: list) -> list:
    projects = []
    for exp in work_experiences:
        if not isinstance(exp, dict):
            continue
        for proj in exp.get("projects") or []:
            if not isinstance(proj, dict):
                continue
            projects.append({
                "projectId":     None,
                "candidateId":   None, 
                "projectName":   proj.get("name", ""),
                "technologies":  proj.get("technologies", []),
                "description":   proj.get("description", ""),
                "startDate":     None,
                "role":          None,  
                "endDate":       None,
                "client":        None,
                "projectIndustry": None,      
                "duration":       None, 
                "projectUrl":    None,
                "projectImages": [],
            })
    return projects




def _extract_projects_via_llm(resume_text: str) -> list:
    try:
        prompt = f"""
You are a resume parser. The resume below has no dedicated Projects section,
but the work experience bullets describe specific systems/products the candidate built.

Extract each distinct project or system built as a separate entry.
Return ONLY a JSON array (not an object, not wrapped in any key), no markdown, no explanation.
Each element must have exactly these keys:
  "name"         – short project/product name (e.g. "Remote Assistance Web App", NOT "Language: Java...")
  "description"  – one sentence summarising what was built
  "technologies" – list of tech strings mentioned

Rules:
- Never use a line starting with "Language:" as the project name
- Extract the actual product/system name from the Description text
- Extract technologies from any "Language:" or "Tech Used:" lines

If no identifiable projects exist, return [].

Resume:
{resume_text[:4000]}
"""
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout=10
        )
        content = response.choices[0].message.content.strip()
        content = re.sub(r"```json|```", "", content).strip()
        
        projects = json.loads(content)
        if isinstance(projects, dict):
            projects = projects.get("projects") or []
        if not isinstance(projects, list):
            return []

        return [
            {
                "projectId":      None,
                "candidateId":    None,
                "projectName":    p.get("name", ""),
                "client":         None,
                "startDate":      None,
                "endDate":        None,
                "role":           None,
                "technologies":   p.get("technologies", []),
                "description":    p.get("description", ""),
                "projectIndustry": None,
                "duration":       None,
                "projectUrl":     None,
                "projectImages":  [],
            }
            for p in projects if isinstance(p, dict) and p.get("name")
        ]
    except Exception as e:
        print(f"[WARN] _extract_projects_via_llm failed: {e}")
        return []
    
def _clean_project_names(projects: list) -> list:
    if not projects:
        return projects
    try:
        cleaned = []
        for p in projects:
            if not isinstance(p, dict):
                cleaned.append(p)
                continue
            name = p.get("projectName", "") or ""
            if re.match(r"^Language\s*:", name, re.IGNORECASE):
                desc = p.get("description", "") or ""
                real_name_match = re.match(
                    r"(?:Description\s*:\s*)?([A-Z][A-Za-z0-9\s\(\)\-]{2,40}?)(?:\s+is\s+|\s+allows|\s+was)",
                    desc
                )
                if real_name_match:
                    p["projectName"] = real_name_match.group(1).strip()
                    tech_str = re.sub(r"^Language\s*:\s*", "", name, flags=re.IGNORECASE)
                    p["technologies"] = [t.strip() for t in tech_str.split(",") if t.strip()]
                else:
                    continue
            cleaned.append(p)
        return cleaned
    except Exception as e:
        print(f"[WARN] _clean_project_names failed: {e}")
        return projects  


def _valid_github(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url.strip())
    return "github.com" in (p.netloc or "") and len(p.path.strip("/")) > 0


def _valid_linkedin(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url.strip())
    return "linkedin.com" in (p.netloc or "") and "/in/" in p.path


def process_attachments_for_email(email_record, attachments: list, provider: str, db) -> int:

    saved = 0
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")

    for att in attachments:
        filename  = att.filename or ""
        file_path = att.file_path or ""

        if not _is_resume_file(filename):
            continue
        if not file_path or not os.path.exists(file_path):
            print(f"[SKIP] File not found on disk: {file_path}")
            continue

        try:
            wrapper = _FileWrapper(filename, file_path)
            if filename.lower().endswith(".pdf"):
                text, pdf_links = extract_text_and_links(wrapper)
            else:
                text      = extract_text(wrapper)
                pdf_links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
            wrapper.close()

            if not text or not text.strip():
                print(f"[SKIP] Empty text from: {filename}")
                continue

            parsed   = parse_resume_text(text)
            llm_data = parse_with_llm(text)

            name  = parsed.get("name")  or llm_data.get("name")
            email = parsed.get("email") or llm_data.get("email")
            phone = parsed.get("phone") or llm_data.get("phone")

            _pdf = pdf_links if isinstance(pdf_links, dict) else {}

            github = (
                _pdf.get("github")
                or parsed.get("github")
                or llm_data.get("github")
                or ""
            )
            linkedin = (
                _pdf.get("linkedin")
                or parsed.get("linkedin")
                or llm_data.get("linkedin")
                or None
            )
            print(f"[LINKS] {filename}: github={github!r} linkedin={linkedin!r} raw_pdf={_pdf}")

            _seen_skills = set()
            skills = []
            for s in (parsed.get("skills") or []) + (llm_data.get("skills") or []):
                key = str(s)
                if key not in _seen_skills:
                    _seen_skills.add(key)
                    skills.append(s)

            llm_certs = [c for c in (llm_data.get("certifications") or []) if isinstance(c, dict)]
            if llm_certs:
                certifications = llm_certs
            else:
                _cert_keywords = (
                    "certified", "certification", "certificate", "associate",
                    "professional", "credential", "course", "nanodegree",
                )
                certifications = [
                    c for c in (parsed.get("certifications") or [])
                    if isinstance(c, str)
                    and any(kw in c.lower() for kw in _cert_keywords)
                ]

            
            llm_exp = llm_data.get("experience") or []
            if llm_exp and isinstance(llm_exp[0], dict):
                work_experiences = _build_work_experiences(llm_exp)
            else:
                work_experiences = parsed.get("work_experiences") or \
                                   parse_work_experiences(parsed.get("experience") or [])

            llm_edu = llm_data.get("education") or []
            if llm_edu and isinstance(llm_edu[0], dict) and llm_edu[0].get("institution"):
                educations = _build_educations(llm_edu)
            else:
                educations = parse_education_items(parsed.get("education") or [])

            llm_proj = llm_data.get("projects") or []
            if llm_proj and isinstance(llm_proj[0], dict) and llm_proj[0].get("name"):
                candidate_projects = [
                    {
                        "projectId":    None,
                        "candidateId":    None, 
                        "projectName":  p.get("name", ""),
                        "technologies": p.get("technologies", []),
                        "description":  p.get("description", ""),
                        "startDate":    None,
                        "endDate":      None,
                        "role":           None, 
                        "client":       None,
                        "projectIndustry": None,      
                        "duration":       None,  
                        "projectUrl":   None,
                        "projectImages": [],
                    }
                    for p in llm_proj if isinstance(p, dict)
                ]
            else:
                candidate_projects = _extract_projects_from_experience(
                    llm_data.get("experience") or []
                )
                if not candidate_projects:
                    candidate_projects = _extract_projects_via_llm(text)
                if not candidate_projects:
                    candidate_projects = parse_projects(
                        parsed.get("projects") or text.splitlines()
                    )

            resume_url = None
            try:
                wrapper_s3 = _FileWrapper(filename, file_path)
                resume_url = upload_file_to_s3(wrapper_s3)
                wrapper_s3.close()
            except Exception as e:
                print(f"[S3 WARN] Could not upload {filename}: {e}")

            existing = db.query(Candidate).filter_by(
                email_id        = email_record.email_id,
                attachment_name = filename,
                source          = "email_sync",
            ).first()
            if existing:
                continue

            candidate_projects = _clean_project_names(candidate_projects)

            record = Candidate(
                source          = "email_sync",
                email_id        = email_record.email_id,
                email_date      = str(email_record.date or ""),
                email_subject   = email_record.subject or "",
                sender_email    = email_record.candidate_email or "",
                provider        = provider,
                attachment_name = filename,
                name            = name,
                email           = email,
                phone           = phone,
                github          = github,
                linkedin        = linkedin,
                skills          = skills,
                experience      = work_experiences,
                education       = educations,
                projects        = candidate_projects,
                certifications  = certifications,
                resume_url      = resume_url,
                raw_text        = sanitize_text(text),
                created_at      = now_str,
            )

            db.add(record)
            db.commit()
            saved += 1
            print(f"[SAVED] EmailCandidate: {name} | {filename}")

        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed processing attachment {filename}: {e}")
            continue

    return saved