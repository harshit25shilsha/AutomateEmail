# routers/outlook.py
import io
import os
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

import services.outlook_service as outlook_svc
from database.db import get_db
from models.attachment_model import Attachment
from models.email_model import Email
from models.hr_user import HRUser
from routers.auth import get_current_user
from schemas.email_schema import (
    EmailListResponse,
    MessageResponse,
    MultipleDownloadRequest,
)

router = APIRouter(prefix="/outlook", tags=["Outlook"])


@router.get("/status", response_model=MessageResponse)
def status(current_user: HRUser = Depends(get_current_user)):
    connected = outlook_svc.is_authenticated(current_user)
    return {"message": "connected" if connected else "not_connected"}


@router.get("/emails", response_model=EmailListResponse)
def get_emails(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, le=1000),
    search: str = Query(default=None),
    get_all: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    if not outlook_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail="Outlook not connected.")

    query = db.query(Email).filter(Email.provider == "outlook")

    if search:
        query = query.filter(
            or_(
                Email.candidate_name.ilike(f"%{search}%"),
                Email.subject.ilike(f"%{search}%"),
                Email.candidate_email.ilike(f"%{search}%"),
            )
        )

    total = query.count()

    if get_all:
        emails = query.order_by(Email.id.desc()).all()
        page = 1
        page_size = total
    else:
        emails = (
            query.order_by(Email.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    result = []
    for email in emails:
        atts = db.query(Attachment).filter_by(email_id=email.id).all()
        result.append(
            {
                "id": email.id,
                "email_id": email.email_id,
                "provider": email.provider,
                "candidate_name": email.candidate_name,
                "candidate_email": email.candidate_email,
                "subject": email.subject,
                "body": email.body,
                "date": email.date,
                "has_attachments": email.has_attachments,
                "attachments": [
                    {
                        "id": a.id,
                        "filename": a.filename,
                        "file_type": a.file_type,
                        "file_size": a.file_size,
                    }
                    for a in atts
                ],
            }
        )

    return {
        "provider": "outlook",
        "total": total,
        "page": page,
        "page_size": page_size,
        "emails": result,
    }


@router.get("/emails/{email_id}")
def get_email(
    email_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    email = db.query(Email).filter_by(id=email_id, provider="outlook").first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    atts = db.query(Attachment).filter_by(email_id=email.id).all()
    return {
        "id": email.id,
        "candidate_name": email.candidate_name,
        "candidate_email": email.candidate_email,
        "subject": email.subject,
        "body": email.body,
        "date": email.date,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "file_type": a.file_type,
                "file_size": a.file_size,
            }
            for a in atts
        ],
    }


@router.get("/attachments/{att_id}/view")
def view_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.file_path, filename=att.filename)


@router.get("/attachments/{att_id}/download")
def download_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        att.file_path,
        filename=att.filename,
        media_type="application/octet-stream",
    )


@router.post("/attachments/download/multiple")
def download_multiple(
    data: MultipleDownloadRequest,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
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
        headers={"Content-Disposition": "attachment; filename=selected.zip"},
    )


@router.get("/attachments/download/all")
def download_all(
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    atts = (
        db.query(Attachment)
        .join(Email, Email.id == Attachment.email_id)
        .filter(Email.provider == "outlook")
        .all()
    )
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for att in atts:
            if os.path.exists(att.file_path):
                zf.write(att.file_path, att.filename)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_attachments.zip"},
    )


@router.post("/sync", response_model=MessageResponse)
def manual_sync(
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    if not outlook_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail="Outlook not connected.")
    count = outlook_svc.fetch_and_store_emails(current_user, db)
    return {"message": f"Synced {count} new emails"}