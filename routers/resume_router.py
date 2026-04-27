import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, UploadFile, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database.db import get_db
from models.candidate import Candidate
from models.employee import Employee
from routers.employee_auth import get_current_employee
from services.resume_service import (
    calculate_parsability_score,
    extract_phone_numbers,
    extract_text,
    extract_text_and_links,
    extract_profile_urls,
    parse_education_items,
    parse_projects,
    parse_resume_text,
    parse_with_llm,
    parse_work_experiences,
    sanitize_text,
    split_name,
    normalize_date,
    BASIC_PHONE_REGEX,
    upload_file_to_s3,
    build_certifications_from_llm,
    parse_certifications_from_text,
    extract_projects_from_experience,
    _clean_work_experience,  
    _split_role_company,
)
from dateutil import parser as date_parser

router = APIRouter(prefix="/resume", tags=["Resume"])

def _merge(primary, fallback):
    return primary if primary else fallback


def _merge_list(primary: list, fallback: list) -> list:
    
    seen = set()
    result = []
    for item in (primary or []) + (fallback or []):
        if isinstance(item, dict):
            key = (
                item.get("name") or
                item.get("projectName") or
                str(item)
            )
        else:
            key = str(item)
        key = key.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _normalise_llm_url(url) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip().rstrip('/')
    if not url:
        return None
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url


def _build_work_experiences_from_llm(llm_experiences, candidateId=None):
    result = []
    for exp in llm_experiences:
        if not isinstance(exp, dict):
            continue
        end_date_raw = (exp.get("endDate", "") or "").strip()
        is_current = end_date_raw.lower() in ("present", "current")
        
        entry = {
            "candidateId":      candidateId,
            "workExperienceId": None,
            "role":             exp.get("role", ""),
            "companyName":      exp.get("company", ""),
            "startDate":        normalize_date(exp.get("startDate", "")),
            "endDate":          None if is_current else normalize_date(end_date_raw) if end_date_raw else None,
            "isCurrentlyWorking": is_current,
        }
        entry = _split_role_company(entry)
        entry = _clean_work_experience(entry)
        result.append(entry)
    return result


def _build_educations_from_llm(llm_educations):
    edu_list = []
    degree_type_map = {
        "master":           "POST_GRADUATION",
        "mba":              "POST_GRADUATION",
        "mca":              "POST_GRADUATION",
        "m.tech":           "POST_GRADUATION",
        "m.sc":             "POST_GRADUATION",
        "ph.d":             "DOCTORATE",
        "doctorate":        "DOCTORATE",
        "10th":             "SCHOOLING",
        "12th":             "SCHOOLING",
        "intermediate":     "SCHOOLING",
        "senior secondary": "SCHOOLING",
        "high school":      "SCHOOLING",
        "ssc":              "SCHOOLING",
        "hsc":              "SCHOOLING",
    }
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")

    for edu in llm_educations:
        if not isinstance(edu, dict):
            continue
        degree      = edu.get("degree", "")      or ""
        institution = edu.get("institution", "") or ""
        year        = edu.get("year", "")        or ""
        board       = edu.get("board", "")       or ""

        edu_type     = "GRADUATION"
        lower_degree = degree.lower()
        for keyword, etype in degree_type_map.items():
            if keyword in lower_degree:
                edu_type = etype
                break

        edu_list.append({
            "educationId":     None,
            "type":            edu_type,
            "institutionName": institution,
            "passingYear":     year,
            "degreeName":      degree,
            "board":           board,
            "percentage":      edu.get("percentage", ""),
            "university":      institution,
            "createdAt":       now_str,
            "updatedAt":       now_str,
            "educationStatus": "COMPLETED",
        })
    return edu_list


def _build_projects_from_llm(llm_projects, candidateId=None):
    result = []
    for p in llm_projects:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        result.append({
            "candidateId":     candidateId,
            "projectId":       None,
            "projectName":     p.get("name", ""),
            "client":          None,
            "startDate":       None,
            "endDate":         None,
            "role":            None,
            "technologies":    p.get("technologies") or [],
            "description":     p.get("description", ""),
            "projectIndustry": None,
            "duration":        None,
            "projectUrl":      None,
            "projectImages":   [],
        })
    return result


@router.post("/upload-single")
async def upload_single_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_employee: Employee = Depends(get_current_employee),
):
    try:
        text, pdf_links = extract_text_and_links(file)
        if not text.strip():
            return JSONResponse(
                status_code=400,
                content={
                    "status": {"httpCode": "400", "success": False,
                               "message": "The file is corrupted. Please upload another resume."},
                    "data": {},
                },
            )
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "status": {"httpCode": "400", "success": False,
                           "message": f"Uploaded resume '{file.filename}' is corrupted or cannot be parsed."},
                "data": {},
            },
        )

    parsability = calculate_parsability_score(text)
    if not parsability["parsable"]:
        return JSONResponse(
            status_code=422,
            content={
                "status": {"httpCode": "422", "success": False,
                           "message": f"Resume not parsable enough (score {parsability['score']})"},
                "data": {"parsability": parsability},
            },
        )

    parsed = parse_resume_text(text)
    parsed["raw_text"] = sanitize_text(parsed["raw_text"])

    llm_data = parse_with_llm(text)

    name   = _merge(parsed.get("name"),   llm_data.get("name"))
    email  = _merge(parsed.get("email"),  llm_data.get("email"))
    phone  = _merge(parsed.get("phone"),  llm_data.get("phone"))


    linkedin  = _merge(
        pdf_links.get("linkedin"),
        _merge(parsed.get("linkedin"),  _normalise_llm_url(llm_data.get("linkedin")))
    )
    github    = _merge(
        pdf_links.get("github"),
        _merge(parsed.get("github"),    _normalise_llm_url(llm_data.get("github")))
    )
    portfolio = _merge(
        pdf_links.get("portfolio"),
        _merge(parsed.get("portfolio"), _normalise_llm_url(llm_data.get("portfolio")))
    )

    skills = list(dict.fromkeys(
        (parsed.get("skills") or []) + (llm_data.get("skills") or [])
    ))

    llm_experiences = llm_data.get("experience") or []
    if llm_experiences and isinstance(llm_experiences[0], dict):
        work_experiences = _build_work_experiences_from_llm(llm_experiences)
    else:
        work_experiences = parsed.get("work_experiences") or parse_work_experiences(
            parsed.get("experience") or []
        )

    llm_educations = llm_data.get("education") or []
    if llm_educations and isinstance(llm_educations[0], dict) and llm_educations[0].get("institution"):
        educations = _build_educations_from_llm(llm_educations)
    else:
        educations = parse_education_items(parsed.get("education") or [])


    llm_projects = llm_data.get("projects") or []
    if llm_projects and isinstance(llm_projects[0], dict) and llm_projects[0].get("name"):
        base_projects = _build_projects_from_llm(llm_projects)
    else:
        base_projects = parse_projects(
            parsed.get("projects") or parsed["raw_text"].splitlines(),
            candidateId=None,
        )

    experience_projects  = extract_projects_from_experience(llm_experiences)
    exp_proj_structured  = _build_projects_from_llm(experience_projects)

    candidate_projects = _merge_list(base_projects, exp_proj_structured)

    llm_certs = llm_data.get("certifications") or []
    if llm_certs and isinstance(llm_certs[0], dict) and llm_certs[0].get("name"):
        llm_cert_list = build_certifications_from_llm(llm_certs)
    else:
        llm_cert_list = []

    regex_cert_lines = parsed.get("certifications") or []
    regex_cert_list  = parse_certifications_from_text(regex_cert_lines)

    certifications = _merge_list(llm_cert_list, regex_cert_list)

    resume_file_url = upload_file_to_s3(file)
    if not resume_file_url:
        return JSONResponse({"error": "Failed to upload resume to cloud"}, status_code=500)

    try:
        candidate = Candidate(
            name=name,
            email=email,
            phone=phone,
            linkedin=linkedin,
            skills=skills,
            experience=work_experiences or [],
            education=educations or [],
            projects=candidate_projects or [],
            certifications=certifications or [],
            raw_text=parsed.get("raw_text"),
            resume_url=resume_file_url,
            github=github or "",
            portfolio=portfolio or "",
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": "DB insert failed"}, status_code=500)

    candidateId = str(candidate.id)
    for w in work_experiences:
        w["candidateId"] = candidateId
    for p in candidate_projects:
        p["candidateId"] = candidateId

    mobile_out = whatsapp = whatsapp_cc = countryCode = country = None
    if phone:
        digits = re.sub(r'\D', '', phone)
        if len(digits) >= 10:
            mobile_out  = digits[-10:]
            cc          = digits[:-10]
            countryCode = cc if cc else "91"
            whatsapp    = mobile_out
            whatsapp_cc = countryCode
            country     = "India" if countryCode in ("91", "+91", "") else None

    total_months = 0
    for w in work_experiences:
        sd = w.get("startDate")
        ed = w.get("endDate")
        if not sd:
            continue
        try:
            start = date_parser.parse(sd)
            end   = (
                date_parser.parse(ed)
                if ed and ed.lower() not in ("present", "current")
                else datetime.now(ZoneInfo("Asia/Kolkata"))
            )
            diff = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(0, diff)
        except Exception:
            continue

    years  = total_months // 12
    keyExperience = f"{years} Year"

    current_job         = next((w for w in work_experiences if w.get("isCurrentlyWorking")), None)
    current_designation = current_job.get("role")        if current_job else None
    current_company     = current_job.get("companyName") if current_job else None

    firstName, lastName = split_name(name)

    data = {
        "firstName":                   firstName or "",
        "lastName":                    lastName  or "",
        "Experience":                  keyExperience,
        "address":                     None,
        "github":                      github    or "",
        "portfolio":                   portfolio or "",
        "linkedIn":                    linkedin,
        "email":                       email,
        "mobile":                      mobile_out,
        "countryCode":                 countryCode,
        "currentDesignation":          current_designation,
        "currentlyWorkingCompanyName": current_company,
        "workExperiences":             work_experiences,
        "educations":                  educations,
        "skillList":                   skills,
        "resumeFileUrl":               resume_file_url,
        "candidateProjects":           candidate_projects,
        "candidateCertificate":        certifications,
        "candidateSkills": [
            {
                "candidateSkillsId": i + 1,
                "skills":            s,
                "experience":        None,
                "rating":            None,
                "candidateId":       candidateId,
            }
            for i, s in enumerate(skills)
        ],
    }

    return JSONResponse(content={
        "status":      {"httpCode": "200", "success": True, "message": "Success"},
        "data":        data,
        "parsability": parsability,
    })