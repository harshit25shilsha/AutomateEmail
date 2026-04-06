# routers/email_router.py
import os, json, zipfile, redis
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database.db import get_db
from routers.auth import get_current_user
from models.hr_user          import HRUser
from models.email_model      import Email
from models.attachment_model import Attachment
from schemas.email_schema    import (
    EmailListResponse, MessageResponse,
    MonitorStatus, MultipleDownloadRequest
)
from celery_worker.tasks import monitor_gmail, monitor_outlook
import services.gmail_service   as gmail_svc
import services.outlook_service as outlook_svc
from services.extractor import extract_job_position
import io

router       = APIRouter(prefix="/email", tags=["Email"])
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

PROVIDERS = {
    "gmail":   gmail_svc,
    "outlook": outlook_svc,
}

MONITOR_TASKS = {
    "gmail":   monitor_gmail,
    "outlook": monitor_outlook,
}


def get_provider_svc(provider: str):
    svc = PROVIDERS.get(provider)
    if not svc:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: '{provider}'. Use 'gmail' or 'outlook'.")
    return svc


# ── Status ────────────────────────────────────────────────────
@router.get("/{provider}/status", response_model=MessageResponse)
def status(
    provider:     str,
    current_user: HRUser = Depends(get_current_user)
):
    svc = get_provider_svc(provider)
    connected = svc.is_authenticated(current_user)
    return {"message": "connected" if connected else "not_connected"}


# ── Fetch Emails ──────────────────────────────────────────────
@router.get("/{provider}/emails", response_model=EmailListResponse)
def get_emails(
    provider:  str,
    page:      int     = Query(default=1, ge=1),
    page_size: int     = Query(default=100, le=1000),
    search:    str     = Query(default=None),
    get_all:   bool    = Query(default=False),
    db:        Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user)
):
    svc = get_provider_svc(provider)
    if not svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail=f"{provider.capitalize()} not connected.")

    query = db.query(Email).filter(Email.provider == provider)

    if search:
        query = query.filter(
            or_(
                Email.candidate_name.ilike(f"%{search}%"),
                Email.subject.ilike(f"%{search}%"),
                Email.candidate_email.ilike(f"%{search}%")
            )
        )

    total = query.count()

    if get_all:
        emails = query.order_by(Email.id.desc()).all()
        page = 1
        page_size = total
    else:
        emails = query.order_by(Email.id.desc())\
                      .offset((page - 1) * page_size)\
                      .limit(page_size).all()

    result = []
    for email in emails:
        atts = db.query(Attachment).filter_by(email_id=email.id).all()
        result.append({
            "id":              email.id,
            "email_id":        email.email_id,
            "provider":        email.provider,
            "candidate_name":  email.candidate_name,
            "candidate_email": email.candidate_email,
            "subject":         email.subject,
            "body":            email.body,
            "date":            email.date,
            "job_position": email.job_position,
            "has_attachments": email.has_attachments,
            "attachments":     [{"id": a.id, "filename": a.filename,
                                 "file_type": a.file_type,
                                 "file_size": a.file_size} for a in atts]
        })

    return {
        "provider":  provider,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "emails":    result
    }


# ── Single Email ──────────────────────────────────────────────
@router.get("/{provider}/emails/{email_id}")
def get_email(
    provider:     str,
    email_id:     int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)
    email = db.query(Email).filter_by(id=email_id, provider=provider).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    atts = db.query(Attachment).filter_by(email_id=email.id).all()
    
    return {
        "id":              email.id,
        "candidate_name":  email.candidate_name,
        "candidate_email": email.candidate_email,
        "subject":         email.subject,
        "job_role": email.job_position or extract_job_position(email.subject, email.body or ""),        
        "date":            email.date,
        "attachments": [
            {
                "id":           a.id,
                "filename":     a.filename,
                "file_type":    a.file_type,
                "file_size":    a.file_size,
                "view_url":     f"/email/{provider}/attachments/{a.id}/view",
                "download_url": f"/email/{provider}/attachments/{a.id}/download"
            }
            for a in atts
        ]
    }

# ── View Attachment ───────────────────────────────────────────
@router.get("/{provider}/attachments/{att_id}/view")
def view_attachment(
    provider:     str,
    att_id:       int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.file_path, filename=att.filename)


# ── Download Single ───────────────────────────────────────────
@router.get("/{provider}/attachments/{att_id}/download")
def download_attachment(
    provider:     str,
    att_id:       int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        att.file_path,
        filename=att.filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"inline; filename={att.filename}"}  # ← add this
    )


# ── Download Multiple ─────────────────────────────────────────
@router.post("/{provider}/attachments/download/multiple")
def download_multiple(
    provider:     str,
    data:         MultipleDownloadRequest,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for att_id in data.attachment_ids:
            att = db.query(Attachment).filter_by(id=att_id).first()
            if att and os.path.exists(att.file_path):
                zf.write(att.file_path, att.filename)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=selected.zip"}
    )


# ── Download All ──────────────────────────────────────────────
@router.get("/{provider}/attachments/download/all")
def download_all(
    provider:     str,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    atts = db.query(Attachment)\
             .join(Email, Email.id == Attachment.email_id)\
             .filter(Email.provider == provider).all()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for att in atts:
            if os.path.exists(att.file_path):
                zf.write(att.file_path, att.filename)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={provider}_all_attachments.zip"}
    )


# ── Monitor Start ─────────────────────────────────────────────
@router.post("/{provider}/monitor/start", response_model=MessageResponse)
def start_monitor(
    provider:     str,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    svc = get_provider_svc(provider)
    if not svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail=f"{provider.capitalize()} not connected.")
    if redis_client.get(f"monitor:{provider}:{current_user.id}"):
        return {"message": "Monitor already running"}
    redis_client.set(f"monitor:{provider}:{current_user.id}", "running")
    MONITOR_TASKS[provider].apply_async(args=[current_user.id])
    return {"message": f"{provider.capitalize()} monitor started — checking every 10 minutes"}


# ── Monitor Stop ──────────────────────────────────────────────
@router.post("/{provider}/monitor/stop", response_model=MessageResponse)
def stop_monitor(
    provider:     str,
    current_user: HRUser = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    redis_client.delete(f"monitor:{provider}:{current_user.id}")
    return {"message": f"{provider.capitalize()} monitor stopped"}


# ── Monitor Status ────────────────────────────────────────────
@router.get("/{provider}/monitor/status", response_model=MonitorStatus)
def monitor_status(
    provider:     str,
    current_user: HRUser = Depends(get_current_user)
):
    get_provider_svc(provider)  # validate provider
    is_running = redis_client.get(f"monitor:{provider}:{current_user.id}") is not None
    data       = redis_client.get(f"last_run:{provider}:{current_user.id}")
    last_check = json.loads(data)["last_run"] if data else None
    return {
        "provider":      provider,
        "is_running":    is_running,
        "interval_mins": 10,
        "last_check":    last_check
    }


# ── Manual Sync ───────────────────────────────────────────────
@router.post("/{provider}/sync", response_model=MessageResponse)
def manual_sync(
    provider:     str,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    svc = get_provider_svc(provider)
    if not svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail=f"{provider.capitalize()} not connected.")
    count = svc.fetch_and_store_emails(current_user, db)
    return {"message": f"Synced {count} new emails"}