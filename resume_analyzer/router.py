import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.db import get_db
from resume_analyzer.analyzer_service import analyze_resume
from resume_analyzer.drive_service import upload_resume, get_mime_type
from resume_analyzer.models import ResumeAnalysis

router = APIRouter(prefix="/resume-analyzer", tags=["Resume Analyzer"])

_NOW_IST = lambda: datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


def _extract_and_parse(file: UploadFile) -> dict:

    from services.resume_service import (
        extract_text,
        extract_text_and_links,
        parse_resume_text,
        parse_with_llm,
        sanitize_text,
    )

    if file.filename.lower().endswith(".pdf"):
        text, _ = extract_text_and_links(file)
    else:
        text = extract_text(file)

    if not text or not text.strip():
        return {}

    parsed   = parse_resume_text(text)
    llm_data = parse_with_llm(text)

    skills = list(dict.fromkeys(
        (parsed.get("skills") or []) + (llm_data.get("skills") or [])
    ))

    return {
        "name":           parsed.get("name") or llm_data.get("name") or "Unknown",
        "email":          parsed.get("email") or llm_data.get("email") or "",
        "skills":         skills,
        "experience":     llm_data.get("experience") or parsed.get("work_experiences") or [],
        "education":      llm_data.get("education") or parsed.get("education") or [],
        "projects":       llm_data.get("projects") or parsed.get("projects") or [],
        "certifications": llm_data.get("certifications") or parsed.get("certifications") or [],
        "raw_text":       sanitize_text(text),
    }


def _record_to_dict(r: ResumeAnalysis) -> dict:
    return {
        "id":             r.id,
        "candidate_name":  r.candidate_name,
        "candidate_email": r.candidate_email,
        "domain":          r.domain,
        "skills":          r.skills,
        "level":           r.level,
        "score":           r.score,
        "summary":         r.summary,
        "filename":        r.filename,
        "folder_path":     r.folder_path,
        "drive_link":      r.drive_link,
        "drive_file_id":   r.drive_file_id,
        "source":          r.source,
        "provider":        r.provider,
        "created_at":      r.created_at,
    }


@router.post("/analyze")
async def analyze_only(file: UploadFile = File(...)):

    parsed_resume = _extract_and_parse(file)
    if not parsed_resume:
        return JSONResponse(
            status_code=400,
            content={
                "status": {"httpCode": "400", "success": False,
                           "message": "Could not extract text from the uploaded file."},
                "data": {},
            },
        )

    analysis = analyze_resume(parsed_resume)

    return JSONResponse(content={
        "status": {"httpCode": "200", "success": True, "message": "Analysis complete"},
        "data":   analysis,
    })


@router.post("/analyze-and-upload")
async def analyze_and_upload(
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db),
):

    parsed_resume = _extract_and_parse(file)
    if not parsed_resume:
        return JSONResponse(
            status_code=400,
            content={
                "status": {"httpCode": "400", "success": False,
                           "message": "Could not extract text from the uploaded file."},
                "data": {},
            },
        )

    analysis = analyze_resume(parsed_resume)

    drive_result = {"file_id": "", "drive_link": ""}
    try:
        await file.seek(0)
        file_bytes   = await file.read()
        drive_result = upload_resume(
            file_bytes=file_bytes,
            filename=analysis["filename"],
            folder_path=analysis["folder"],
            mime_type=get_mime_type(file.filename),
        )
    except Exception as e:
        print(f"[DRIVE WARN] Upload failed: {e}")

    record = ResumeAnalysis(
        candidate_name  = parsed_resume.get("name", "Unknown"),
        candidate_email = parsed_resume.get("email"),
        domain          = analysis["domain"],
        skills          = analysis.get("skills", []),
        level           = analysis["level"],
        score           = analysis["score"],
        summary         = analysis["summary"],
        filename        = analysis["filename"],
        folder_path     = analysis["folder"],
        drive_link      = drive_result["drive_link"],
        drive_file_id   = drive_result["file_id"],
        source          = "upload",
        created_at      = _NOW_IST(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return JSONResponse(content={
        "status": {
            "httpCode": "200", "success": True,
            "message": "Resume analyzed, uploaded to Drive, and saved successfully.",
        },
        "data": {
            "analysis":      analysis,
            "drive_link":    drive_result["drive_link"],
            "drive_file_id": drive_result["file_id"],
            "db_id":         record.id,
        },
    })


@router.get("/history")
def get_history(
    skip:   int          = Query(default=0,  ge=0),
    limit:  int          = Query(default=20, le=100),
    domain: str          = Query(default=None, description="Filter by domain"),
    level:  str          = Query(default=None, description="Fresher / Mid-Level / Senior"),
    db:     Session      = Depends(get_db),
):
    query = db.query(ResumeAnalysis)

    if domain:
        query = query.filter(ResumeAnalysis.domain.ilike(f"%{domain}%"))
    if level:
        query = query.filter(ResumeAnalysis.level == level)

    total   = query.count()
    records = (
        query.order_by(ResumeAnalysis.id.desc())
        .offset(skip).limit(limit).all()
    )

    return JSONResponse(content={
        "status":   {"httpCode": "200", "success": True, "message": "Success"},
        "total":    total,
        "skip":     skip,
        "limit":    limit,
        "data":     [_record_to_dict(r) for r in records],
    })



@router.get("/history/{record_id}")
def get_history_by_id(record_id: int, db: Session = Depends(get_db)):
    """Fetch a single resume analysis record by DB id."""
    record = db.query(ResumeAnalysis).filter(ResumeAnalysis.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")

    return JSONResponse(content={
        "status": {"httpCode": "200", "success": True, "message": "Success"},
        "data":   _record_to_dict(record),
    })



@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(ResumeAnalysis.id)).scalar() or 0

    by_domain = (
        db.query(ResumeAnalysis.domain, func.count(ResumeAnalysis.id))
        .group_by(ResumeAnalysis.domain)
        .order_by(func.count(ResumeAnalysis.id).desc())
        .all()
    )
    by_level = (
        db.query(ResumeAnalysis.level, func.count(ResumeAnalysis.id))
        .group_by(ResumeAnalysis.level).all()
    )
    avg_score = db.query(func.avg(ResumeAnalysis.score)).scalar()

    return JSONResponse(content={
        "status": {"httpCode": "200", "success": True, "message": "Success"},
        "data": {
            "total_analyzed": total,
            "average_score":  round(float(avg_score), 2) if avg_score else 0,
            "by_domain": [{"domain": d, "count": c} for d, c in by_domain],
            "by_level":  [{"level": l,  "count": c} for l, c in by_level],
        },
    })