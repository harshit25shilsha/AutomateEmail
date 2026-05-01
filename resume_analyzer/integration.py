import os
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
 
from resume_analyzer.analyzer_service import analyze_resume
from resume_analyzer.drive_service import upload_resume, get_mime_type
from resume_analyzer.models import ResumeAnalysis


def run_resume_analyzer(
    candidate,        
    file_path:  str,   
    filename:   str,   
    provider:   str,   
    db:         Session,
) -> None:

    try:
        project_names = []
        if isinstance(candidate.projects, list):
            project_names = [
                p.get("projectName", "") if isinstance(p, dict) else str(p)
                for p in candidate.projects
            ]

        parsed_resume = {
            "name":           candidate.name or "Unknown",
            "email":          candidate.email or "",
            "phone":          candidate.phone or "",
            "skills":         candidate.skills or [],
            "experience":     candidate.experience or [], 
            "work_experiences": candidate.work_experiences or [],  
            "education":      candidate.education or [],
            "projects":       project_names,
            "certifications": candidate.certifications or [],
            "raw_text":       candidate.raw_text or "",
        }

        analysis = analyze_resume(parsed_resume)

        drive_result = {"file_id": "", "drive_link": ""}
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                drive_result = upload_resume(
                    file_bytes=file_bytes,
                    filename=analysis["filename"],
                    folder_path=analysis["folder"],
                    mime_type=get_mime_type(filename),
                )
            except Exception as drive_err:
                print(f"[DRIVE WARN] Could not upload {filename}: {drive_err}")
        else:
            print(f"[ANALYZER WARN] File not on disk, skipping Drive upload: {file_path}")

        record = ResumeAnalysis(
            candidate_name  = candidate.name or "Unknown",
            candidate_email = candidate.email,
            domain          = analysis["domain"],
            skills          = analysis.get("skills", []),
            level           = analysis["level"],
            score           = analysis["score"],
            summary         = analysis["summary"],
            filename        = analysis["filename"],
            folder_path     = analysis["folder"],
            drive_link      = drive_result["drive_link"],
            drive_file_id   = drive_result["file_id"],
            source          = "email_sync",
            provider        = provider,
            created_at      = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.add(record)
        db.commit()

        print(
            f"[ANALYZER] ✓ {candidate.name} → {analysis['domain']} | "
            f"Score: {analysis['score']} | {analysis['level']} | "
            f"Drive: {'✓' if drive_result['drive_link'] else '✗ (skipped)'}"
        )

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[ANALYZER ERROR] Failed for {filename}: {e}")