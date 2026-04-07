# routers/email_router.py
import io
import os
import zipfile
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc
from database.db import get_db
from models.attachment_model import Attachment
from models.email_model import Email
from models.hr_user import HRUser
from routers.auth import get_current_user
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from schemas.email_schema import (
    EmailListResponse,
    MessageResponse,
    MultipleDownloadRequest,
)
from services.extractor import extract_job_position

router = APIRouter(prefix="/email", tags=["Email"])


class ProviderEnum(str, Enum):
    gmail = "gmail"
    outlook = "outlook"


ProviderParam = Annotated[
    ProviderEnum,
    Path(description="Email provider to use. Allowed values: `gmail` or `outlook`."),
]

PROVIDERS = {
    "gmail": gmail_svc,
    "outlook": outlook_svc,
}

IST_OFFSET = timedelta(hours=5, minutes=30)

def format_date(date_str: str):
    if not date_str:
        return {"date": None, "time": None}

    try:
        dt = parsedate_to_datetime(date_str)
        dt_ist = dt.astimezone(timezone(IST_OFFSET))
        return {
            "date": dt_ist.strftime("%d/%m/%Y"),
            "time": dt_ist.strftime("%H:%M")
        }
    except Exception:
        pass

    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return {"date": dt.strftime("%d/%m/%Y"), "time": dt.strftime("%H:%M")}
    except Exception:
        pass

    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return {"date": dt.strftime("%d/%m/%Y"), "time": None}
    except Exception:
        pass

    return {"date": date_str, "time": None}


def get_provider_svc(provider: str):
    svc = PROVIDERS.get(provider)
    if not svc:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: '{provider}'. Use 'gmail' or 'outlook'.",
        )
    return svc


@router.get("/{provider}/status", response_model=MessageResponse)
def status(
    provider: ProviderParam,
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    connected = svc.is_authenticated(current_user)
    return {"message": "connected" if connected else "not_connected"}


@router.get("/{provider}/emails", response_model=EmailListResponse)
def get_emails(
    provider: ProviderParam,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, le=1000),
    search: str = Query(default=None),
    get_all: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

    query = db.query(Email).filter(Email.provider == provider_value)

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
                "job_position": email.job_position,
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
        "provider": provider_value,
        "total": total,
        "page": page,
        "page_size": page_size,
        "emails": result,
    }



@router.get("/{provider}/emails/all-details")
def get_all_emails_with_details(
    provider: ProviderParam,
    page:               int  = Query(default=1, ge=1),
    page_size:          int  = Query(default=100, le=1000),
    search:             str  = Query(default=None),
    get_all:            bool = Query(default=False),
    is_job_application: bool = Query(default=None),
    db:                 Session = Depends(get_db),
    current_user:       HRUser  = Depends(get_current_user)
):
    get_provider_svc(provider)

    query = db.query(Email).filter(Email.provider == provider)

    if search:
        query = query.filter(
            or_(
                Email.candidate_name.ilike(f"%{search}%"),
                Email.subject.ilike(f"%{search}%"),
                Email.candidate_email.ilike(f"%{search}%")
            )
        )

    if is_job_application is not None:
        query = query.filter(Email.is_job_application == is_job_application)

    total = query.count()

    if get_all:
        emails    = query.order_by(Email.id.desc()).all()
        page      = 1
        page_size = total
    else:
        emails = query.order_by(Email.id.desc()) \
                      .offset((page - 1) * page_size) \
                      .limit(page_size).all()

    result = []
    for email in emails:
        atts = db.query(Attachment).filter_by(email_id=email.id).all()
        formatted = format_date(email.date)   # ← add this line
        result.append(
            {
                "id": email.id,
                "email_id": email.email_id,
                "provider": email.provider,
                "candidate_name": email.candidate_name,
                "candidate_email": email.candidate_email,
                "subject": email.subject,
                "date": formatted["date"],     
                "time": formatted["time"],    
                "job_position": email.job_position,
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
        "provider":  provider,
        "total":     len(result),
        "page":      page,
        "page_size": page_size,
        "emails":    result
    }

@router.get("/{provider}/emails/{email_id}")
def get_email(
    provider: ProviderParam,
    email_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

    email = db.query(Email).filter_by(id=email_id, provider=provider_value).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    atts = db.query(Attachment).filter_by(email_id=email.id).all()

    return {
        "id": email.id,
        "candidate_name": email.candidate_name,
        "candidate_email": email.candidate_email,
        "subject": email.subject,
        "job_role": email.job_position or extract_job_position(email.subject, email.body or ""),
        "date": email.date,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "file_type": a.file_type,
                "file_size": a.file_size,
                "view_url": f"/email/{provider_value}/attachments/{a.id}/view",
                "download_url": f"/email/{provider_value}/attachments/{a.id}/download",
            }
            for a in atts
        ],
    }


@router.get("/{provider}/attachments/{att_id}/view")
def view_attachment(
    provider: ProviderParam,
    att_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.file_path, filename=att.filename)


@router.get("/{provider}/attachments/{att_id}/download")
def download_attachment(
    provider: ProviderParam,
    att_id: int,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

    att = db.query(Attachment).filter_by(id=att_id).first()
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        att.file_path,
        filename=att.filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"inline; filename={att.filename}"},
    )


@router.post("/{provider}/attachments/download/multiple")
def download_multiple(
    provider: ProviderParam,
    data: MultipleDownloadRequest,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

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


@router.get("/{provider}/attachments/download/all")
def download_all(
    provider: ProviderParam,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )

    atts = (
        db.query(Attachment)
        .join(Email, Email.id == Attachment.email_id)
        .filter(Email.provider == provider_value)
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
        headers={"Content-Disposition": f"attachment; filename={provider_value}_all_attachments.zip"},
    )


@router.post("/{provider}/sync", response_model=MessageResponse)
def manual_sync(
    provider: ProviderParam,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_value = provider.value
    svc = get_provider_svc(provider_value)
    if not svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{provider_value.capitalize()} not connected.",
        )
    count = svc.fetch_and_store_emails(current_user, db)
    return {"message": f"Synced {count} new emails"}
