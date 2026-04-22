import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, UploadFile, Depends
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
)
from dateutil import parser as date_parser

router = APIRouter(prefix="/resume", tags=["Resume"])


def _build_work_experiences_from_llm(llm_experiences, candidateId=None):
    result = []
    for exp in llm_experiences:
        if not isinstance(exp, dict):
            continue
        end_date_raw = exp.get("endDate", "") or ""
        is_current = end_date_raw.lower() in ("present", "current", "")
        result.append({
            "candidateId": candidateId,
            "workExperienceId": None,
            "role": exp.get("role", ""),
            "companyName": exp.get("company", ""),
            "startDate": normalize_date(exp.get("startDate", "")),
            "endDate": None if is_current else normalize_date(end_date_raw),
            "isCurrentlyWorking": is_current,
        })
    return result

def _build_educations_from_llm(llm_educations):
    edu_list = []
    degree_type_map = {
        "master": "POST_GRADUATION",
        "mba": "POST_GRADUATION",
        "mca": "POST_GRADUATION",
        "m.tech": "POST_GRADUATION",
        "m.sc": "POST_GRADUATION",
        "ph.d": "DOCTORATE",
        "doctorate": "DOCTORATE",
        "10th": "SCHOOLING",
        "12th": "SCHOOLING",
        "intermediate": "SCHOOLING",
        "senior secondary": "SCHOOLING",
        "high school": "SCHOOLING",
        "ssc": "SCHOOLING",
        "hsc": "SCHOOLING",
    }
    
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    
    for edu in llm_educations:
        if not isinstance(edu, dict):
            continue
            
        degree = edu.get("degree", "") or ""
        institution = edu.get("institution", "") or ""
        year = edu.get("year", "") or ""
        board = edu.get("board", "") or "" 

        edu_type = "GRADUATION"
        lower_degree = degree.lower()
        
        for keyword, etype in degree_type_map.items():
            if keyword in lower_degree:
                edu_type = etype
                break

        edu_list.append({
            "educationId": None,
            "type": edu_type,
            "institutionName": institution,
            "passingYear": year,
            "degreeName": degree,
            "board": board, 
            "percentage": edu.get("percentage", ""), 
            "university": institution,
            "createdAt": now_str,
            "updatedAt": now_str,
            "educationStatus": "COMPLETED",
        })
    return edu_list


@router.post("/upload-single")
async def upload_single_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_employee: Employee = Depends(get_current_employee),
):
    try:
        text = extract_text(file)
        if not text.strip():
            return JSONResponse(
                status_code=400,
                content={
                    "status": {"httpCode": "400", "success": False,
                               "message": "The file is corrupted. Please upload another resume."},
                    "data": {},
                },
            )
    except Exception as e:
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

    def merge_field(primary, fallback):
        return primary if primary else fallback

    parsed["name"]  = merge_field(parsed.get("name"),  llm_data.get("name"))
    parsed["email"] = merge_field(parsed.get("email"), llm_data.get("email"))
    parsed["phone"] = merge_field(parsed.get("phone"), llm_data.get("phone"))

    parsed["skills"] = list(set(
        (parsed.get("skills") or []) + (llm_data.get("skills") or [])
    ))

    llm_experiences = llm_data.get("experience") or []
    if llm_experiences and isinstance(llm_experiences[0], dict) and llm_experiences[0].get("role"):
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
        now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
        candidate_projects = [
            {
                "candidateId": None,
                "projectId": None,
                "projectName": p.get("name", ""),
                "client": None,
                "startDate": None,
                "endDate": None,
                "role": None,
                "technologies": p.get("technologies", []),
                "description": p.get("description", ""),
                "projectIndustry": None,
                "duration": None,
                "projectUrl": None,
                "projectImages": [],
                # "createdAt": now_str,
                # "updatedAt": now_str,
                # "teamSize": None,
                # "locationMode": None,
                # "clientLocation": None,
            }
            for p in llm_projects if isinstance(p, dict)
        ]
    else:
        candidate_projects = parse_projects(
            parsed.get("projects") or parsed["raw_text"].splitlines(),
            candidateId=None,
        )

    resume_file_url = upload_file_to_s3(file)
    if not resume_file_url:
        return JSONResponse({"error": "Failed to upload resume to cloud"}, status_code=500)

    try:
        candidate = Candidate(
            name=parsed.get("name"),
            email=parsed.get("email"),
            phone=parsed.get("phone"),
            linkedin=parsed.get("linkedin"),
            gender=parsed.get("gender"),
            skills=parsed.get("skills") or [],
            experience=work_experiences or [],
            education=educations or [],
            projects=candidate_projects or [],
            certifications=parsed.get("certifications") or [],
            raw_text=parsed.get("raw_text"),
            resume_url=resume_file_url,
            # github="",
            # skypeId=parsed.get("skypeId"),
            # aadharCardNumber=parsed.get("aadharCardNumber"),
            # panCardNumber=parsed.get("panCardNumber"),
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

    firstName, lastName = split_name(parsed.get("name"))
    skill_list = parsed.get("skills") or []

    raw_phone = parsed.get("phone")
    whatsapp = whatsapp_cc = country = countryCode = mobile_out = None
    if raw_phone:
        digits = re.sub(r'\D', '', raw_phone)
        if len(digits) >= 10:
            mobile_out = digits[-10:]
            cc = digits[:-10]
            countryCode = cc if cc else "91"
            whatsapp = mobile_out
            whatsapp_cc = countryCode
            country = "India" if countryCode in ("91", "+91", "") else None

    total_months = 0
    for w in work_experiences:
        sd = w.get("startDate")
        ed = w.get("endDate")
        if not sd:
            continue
        try:
            start = date_parser.parse(sd)
            end = date_parser.parse(ed) if ed and ed.lower() not in ("present", "current") \
                  else datetime.now(ZoneInfo("Asia/Kolkata"))
            diff = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(0, diff)
        except Exception:
            continue

    years = total_months // 12
    months = total_months % 12
    keyExperience = f"{years} Year"
    keyExperienceInMonth = f"{months} Month"

    current_job = next(
        (w for w in work_experiences if w.get("isCurrentlyWorking")),
        None
    )
    current_designation = current_job.get("role") if current_job else None
    current_company = current_job.get("companyName") if current_job else None


    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    createdAt_ms = int(now.timestamp() * 1000)
    updatedAt_ms = createdAt_ms
    last_login_str = now.strftime("%d-%m-%Y %H:%M:%S IST")

    data = {
        "firstName": firstName or "",
        "lastName": lastName or "",
        "Experience": keyExperience,
        "address": None,
        "github":"",
        "linkedIn": parsed.get("linkedin"),
        "email": parsed.get("email"),
        "mobile": mobile_out,
        "countryCode": countryCode,
        "currentDesignation": current_designation,
        "currentlyWorkingCompanyName": current_company,
        "workExperiences": work_experiences,
        "educations": educations,
        "skillList": skill_list,
        "resumeFileUrl": resume_file_url,
        "gender": parsed.get("gender"),
        "candidateProjects": candidate_projects,
        "candidateCertificate": [],
        "candidateSkills": [
            {"candidateSkillsId": i + 1, "skills": s, "experience": None,
             "rating": None, "candidateId": candidateId}
            for i, s in enumerate(skill_list)
        ],
        # "lastLogin": last_login_str,
        # "profileCompleteness": "COMPLETE" if (parsed.get("skills") or parsed.get("experience")) else "INCOMPLETE",
        # "userSubscription": None,
        # "isRejected": None,
        # "ExperienceInMonth": keyExperienceInMonth,
        # "rejectionReason": None,
        # "isBillable": None,
        # "candidateId": candidateId,
        # "videoUrl": None,
        # "candidateEmpId": None,
        # "skypeId": parsed.get("skypeId"),
        # "department": None,
        # "candidatePrice": {
        #     "id": None, "perMonth": None, "perDay": None,
        #     "perWeek": None, "perHour": None, "currency": None,
        #     "openForNegotiation": None,
        # },
        # "candidateAvailabilityStatus": "ACTIVE",
        # "customCandidateInfo": None,
        # "aadhaarCardUrl": None,
        # "panCardUrl": None,
        # "aadharCardNumber": parsed.get("aadharCardNumber"),
        # "panCardNumber": parsed.get("panCardNumber"),
        # "resumeFileName": file.filename,
        # "userType": "CANDIDATE",
        # "createdAt": createdAt_ms,
        # "updatedAt": updatedAt_ms,
        # "reportingManager": None,
        # "vendorId": None,
        # "overview": "Reduce Time & Cost: Cut hiring time by up to 70% and avoid the costs of bad hires with data-backed decision-making.",
         # "availableForWork": True,
        # "profileImageUrl": None,
        # "pincode": None,
        # "activeStatus": True,
        # "whatsapp": whatsapp,
        # "whatsappCountryCode": whatsapp_cc,
        # "country": country,
        # "state": None,
        # "district": None,
        # "city": None,
    }

    return JSONResponse(content={
        "status": {"httpCode": "200", "success": True, "message": "Success"},
        "data": data,
        "parsability": parsability,
    })