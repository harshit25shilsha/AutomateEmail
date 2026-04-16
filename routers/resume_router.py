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
    parse_work_experiences,
    sanitize_text,
    split_name,
    BASIC_PHONE_REGEX,
    upload_file_to_s3,
)
from dateutil import parser as date_parser

router = APIRouter(prefix="/resume", tags=["Resume"])

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

    educations = parse_education_items(parsed.get("education") or [])
    work_experiences = parsed.get("work_experiences") or []  
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
            skypeId=parsed.get("skypeId"),
            gender=parsed.get("gender"),
            aadharCardNumber=parsed.get("aadharCardNumber"),
            panCardNumber=parsed.get("panCardNumber"),
            skills=parsed.get("skills") or [],
            experience=work_experiences or [],
            education=educations or [],
            projects=candidate_projects or [],
            certifications=parsed.get("certifications") or [],
            raw_text=parsed.get("raw_text"),
            resume_url=resume_file_url,
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": "DB insert failed"}, status_code=500)

    candidateId = str(candidate.id)
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

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    createdAt_ms = int(now.timestamp() * 1000)
    updatedAt_ms = createdAt_ms
    last_login_str = now.strftime("%d-%m-%Y %H:%M:%S IST")

    data = {
        "candidateId": candidateId,
        "firstName": firstName or "",
        "lastName": lastName or "",
        "keyExperience": keyExperience,
        "keyExperienceInMonth": keyExperienceInMonth,
        "address": None,
        "skypeId": parsed.get("skypeId"),
        "linkedIn": parsed.get("linkedin"),
        "whatsapp": whatsapp,
        "whatsappCountryCode": whatsapp_cc,
        "country": country,
        "state": None,
        "district": None,
        "city": None,
        "email": parsed.get("email"),
        "mobile": mobile_out,
        "countryCode": countryCode,
        "availableForWork": True,
        "profileImageUrl": None,
        "pincode": None,
        "activeStatus": True,
        "currentDesignation": None,
        "overview": "Reduce Time & Cost: Cut hiring time by up to 70% and avoid the costs of bad hires with data-backed decision-making.",
        "currentlyWorkingCompanyName": None,
        "userType": "CANDIDATE",
        "createdAt": createdAt_ms,
        "updatedAt": updatedAt_ms,
        "reportingManager": None,
        "vendorId": None,
        "workExperiences": work_experiences,
        "educations": educations,
        "skillList": skill_list,
        "resumeFileName": file.filename,
        "resumeFileUrl": resume_file_url,
        "aadharCardNumber": parsed.get("aadharCardNumber"),
        "panCardNumber": parsed.get("panCardNumber"),
        "gender": parsed.get("gender"),
        "department": None,
        "candidatePrice": {
            "id": None, "perMonth": None, "perDay": None,
            "perWeek": None, "perHour": None, "currency": None,
            "openForNegotiation": None,
        },
        "candidateAvailabilityStatus": "ACTIVE",
        "customCandidateInfo": None,
        "aadhaarCardUrl": None,
        "panCardUrl": None,
        "candidateProjects": candidate_projects,
        "videoUrl": None,
        "candidateEmpId": None,
        "candidateCertificate": [],
        "candidateSkills": [
            {"candidateSkillsId": i + 1, "skills": s, "experience": None,
             "rating": None, "candidateId": candidateId}
            for i, s in enumerate(skill_list)
        ],
        "lastLogin": last_login_str,
        "profileCompleteness": "COMPLETE" if (parsed.get("skills") or parsed.get("experience")) else "INCOMPLETE",
        "userSubscription": None,
        "isRejected": None,
        "rejectionReason": None,
        "isBillable": None,
    }

    return JSONResponse(content={
        "status": {"httpCode": "200", "success": True, "message": "Success"},
        "data": data,
        "parsability": parsability,
    })