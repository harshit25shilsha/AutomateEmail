# routers/outlook.py
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
from celery_worker.tasks import monitor_outlook
import services.outlook_service as outlook_svc
import io

router       = APIRouter(prefix="/outlook", tags=["Outlook"])
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


# ── Status ────────────────────────────────────────────────────
@router.get("/status", response_model=MessageResponse)
def status(current_user: HRUser = Depends(get_current_user)):
    connected = outlook_svc.is_authenticated(current_user)
    return {"message": "connected" if connected else "not_connected"}


# ── Fetch Emails ──────────────────────────────────────────────
@router.get("/emails", response_model=EmailListResponse)
def get_emails(
    page:      int     = Query(default=1, ge=1),
    page_size: int     = Query(default=20, le=100),
    search:    str     = Query(default=None),
    db:        Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user)
):
    if not outlook_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail="Outlook not connected.")

    query = db.query(Email).filter(Email.provider == "outlook")

    if search:
        query = query.filter(
            or_(
                Email.candidate_name.ilike(f"%{search}%"),
                Email.subject.ilike(f"%{search}%"),
                Email.candidate_email.ilike(f"%{search}%")
            )
        )

    total  = query.count()
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
            "has_attachments": email.has_attachments,
            "attachments":     [{"id": a.id, "filename": a.filename,
                                 "file_type": a.file_type,
                                 "file_size": a.file_size} for a in atts]
        })

    return {
        "provider":  "outlook",
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "emails":    result
    }


# ── Single Email ──────────────────────────────────────────────
@router.get("/emails/{email_id}")
def get_email(
    email_id:     int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    email = db.query(Email).filter_by(id=email_id, provider="outlook").first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    atts  = db.query(Attachment).filter_by(email_id=email.id).all()
    return {
        "id":              email.id,
        "candidate_name":  email.candidate_name,
        "candidate_email": email.candidate_email,
        "subject":         email.subject,
        "body":            email.body,
        "date":            email.date,
        "attachments":     [{"id": a.id, "filename": a.filename,
                             "file_type": a.file_type,
                             "file_size": a.file_size} for a in atts]
    }


# ── View Attachment ───────────────────────────────────────────
@router.get("/attachments/{att_id}/view")
def view_attachment(
    att_id:       int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.file_path, filename=att.filename)


# ── Download Single ───────────────────────────────────────────
@router.get("/attachments/{att_id}/download")
def download_attachment(
    att_id:       int,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        att.file_path,
        filename=att.filename,
        media_type="application/octet-stream"
    )


# ── Download Multiple ─────────────────────────────────────────
@router.post("/attachments/download/multiple")
def download_multiple(
    data:         MultipleDownloadRequest,
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
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
@router.get("/attachments/download/all")
def download_all(
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    atts = db.query(Attachment)\
             .join(Email, Email.id == Attachment.email_id)\
             .filter(Email.provider == "outlook").all()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for att in atts:
            if os.path.exists(att.file_path):
                zf.write(att.file_path, att.filename)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_attachments.zip"}
    )


# ── Monitor ───────────────────────────────────────────────────
@router.post("/monitor/start", response_model=MessageResponse)
def start_monitor(
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    if not outlook_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail="Outlook not connected.")
    if redis_client.get(f"monitor:outlook:{current_user.id}"):
        return {"message": "Monitor already running"}
    redis_client.set(f"monitor:outlook:{current_user.id}", "running")
    monitor_outlook.apply_async(args=[current_user.id])
    return {"message": " Outlook monitor started — checking every 10 minutes"}


@router.post("/monitor/stop", response_model=MessageResponse)
def stop_monitor(current_user: HRUser = Depends(get_current_user)):
    redis_client.delete(f"monitor:outlook:{current_user.id}")
    return {"message": " Outlook monitor stopped"}


@router.get("/monitor/status", response_model=MonitorStatus)
def monitor_status(current_user: HRUser = Depends(get_current_user)):
    is_running = redis_client.get(f"monitor:outlook:{current_user.id}") is not None
    data       = redis_client.get(f"last_run:outlook:{current_user.id}")
    last_check = json.loads(data)["last_run"] if data else None
    return {
        "provider":      "outlook",
        "is_running":    is_running,
        "interval_mins": 10,
        "last_check":    last_check
    }


# ── Manual Sync ───────────────────────────────────────────────
@router.post("/sync", response_model=MessageResponse)
def manual_sync(
    db:           Session = Depends(get_db),
    current_user: HRUser  = Depends(get_current_user)
):
    if not outlook_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail="Outlook not connected.")
    count = outlook_svc.fetch_and_store_emails(current_user, db)
    return {"message": f"Synced {count} new emails"}