import io
import os
import zipfile
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc
from database.db import get_db
from models.attachment_model import Attachment
from models.attachment_view import AttachmentView
from models.email_model import Email
from models.hr_user import HRUser
from routers.auth import get_current_user
from schemas.email_schema import (
    EmailListResponse,
    MessageResponse,
    MultipleDownloadRequest,
)
from services.extractor import extract_job_position
from utils.date_utils import format_email_datetime

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


def get_provider_svc(provider: str):
    svc = PROVIDERS.get(provider)
    if not svc:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: '{provider}'. Use 'gmail' or 'outlook'.",
        )
    return svc


def get_email_ordering():
    return (
        Email.received_at.is_(None),
        Email.received_at.desc(),
        Email.id.desc(),
    )


def load_attachment_view_metadata(
    db: Session,
    attachment_ids: list[int],
    current_user_id: int,
) -> tuple[dict[int, object], dict[int, int]]:
    if not attachment_ids:
        return {}, {}

    user_views = (
        db.query(AttachmentView)
        .filter(
            AttachmentView.hr_user_id == current_user_id,
            AttachmentView.attachment_id.in_(attachment_ids),
        )
        .all()
    )
    user_view_map = {view.attachment_id: view.viewed_at for view in user_views}

    view_counts_rows = (
        db.query(
            AttachmentView.attachment_id,
            func.count(AttachmentView.id).label("view_count"),
        )
        .filter(AttachmentView.attachment_id.in_(attachment_ids))
        .group_by(AttachmentView.attachment_id)
        .all()
    )
    view_count_map = {
        row.attachment_id: row.view_count
        for row in view_counts_rows
    }

    return user_view_map, view_count_map


def build_attachment_payload(
    attachment: Attachment,
    user_view_map: dict[int, object],
    view_count_map: dict[int, int],
):
    viewed_at = user_view_map.get(attachment.id)
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "file_type": attachment.file_type,
        "file_size": attachment.file_size,
        "is_viewed": viewed_at is not None,
        "viewed_at": viewed_at,
        "view_count": view_count_map.get(attachment.id, 0),
    }


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
    ordering = get_email_ordering()

    if get_all:
        emails = query.order_by(*ordering).all()
        page = 1
        page_size = total
    else:
        emails = (
            query.order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    email_ids = [email.id for email in emails]
    attachments = []
    if email_ids:
        attachments = db.query(Attachment).filter(Attachment.email_id.in_(email_ids)).all()

    attachments_by_email = {}
    for att in attachments:
        attachments_by_email.setdefault(att.email_id, []).append(att)

    attachment_ids = [att.id for att in attachments]
    user_view_map, view_count_map = load_attachment_view_metadata(
        db,
        attachment_ids,
        current_user.id,
    )

    result = []
    for email in emails:
        atts = attachments_by_email.get(email.id, [])
        formatted = format_email_datetime(email.received_at, email.date)
        result.append(
            {
                "id": email.id,
                "email_id": email.email_id,
                "provider": email.provider,
                "candidate_name": email.candidate_name,
                "candidate_email": email.candidate_email,
                "subject": email.subject,
                "body": email.body,
                "date": formatted["date"],
                "job_position": email.job_position,
                "has_attachments": email.has_attachments,
                "attachments": [
                    build_attachment_payload(a, user_view_map, view_count_map)
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, le=1000),
    search: str = Query(default=None),
    get_all: bool = Query(default=False),
    is_job_application: bool = Query(default=None),
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

    if is_job_application is not None:
        query = query.filter(Email.is_job_application == is_job_application)

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

    email_ids = [email.id for email in emails]
    attachments = []
    if email_ids:
        attachments = db.query(Attachment).filter(Attachment.email_id.in_(email_ids)).all()

    attachments_by_email = {}
    for att in attachments:
        attachments_by_email.setdefault(att.email_id, []).append(att)

    attachment_ids = [att.id for att in attachments]
    user_view_map, view_count_map = load_attachment_view_metadata(
        db,
        attachment_ids,
        current_user.id,
    )

    result = []
    for email in emails:
        atts = attachments_by_email.get(email.id, [])
        formatted = format_email_datetime(email.received_at, email.date)
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
                    build_attachment_payload(a, user_view_map, view_count_map)
                    for a in atts
                ],
            }
        )

    return {
        "provider": provider_value,
        "total": len(result),
        "page": page,
        "page_size": page_size,
        "emails": result,
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
    attachment_ids = [att.id for att in atts]
    user_view_map, view_count_map = load_attachment_view_metadata(
        db,
        attachment_ids,
        current_user.id,
    )

    formatted = format_email_datetime(email.received_at, email.date)

    return {
        "id": email.id,
        "candidate_name": email.candidate_name,
        "candidate_email": email.candidate_email,
        "subject": email.subject,
        "job_role": email.job_position or extract_job_position(email.subject, email.body or ""),
        "date": formatted["date"],
        "attachments": [
            {
                **build_attachment_payload(a, user_view_map, view_count_map),
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

    att = (
        db.query(Attachment)
        .join(Email, Email.id == Attachment.email_id)
        .filter(
            Attachment.id == att_id,
            Email.provider == provider_value,
        )
        .first()
    )

    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")

    existing_view = (
        db.query(AttachmentView)
        .filter(
            AttachmentView.attachment_id == att.id,
            AttachmentView.hr_user_id == current_user.id,
        )
        .first()
    )

    if not existing_view:
        db.add(
            AttachmentView(
                attachment_id=att.id,
                hr_user_id=current_user.id,
            )
        )
        db.commit()

    return FileResponse(att.file_path, filename=att.filename)


@router.get(
    "/{provider}/attachments/{att_id}/download",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                "application/octet-stream": {},
            },
            "description": "Download a single attachment.",
        }
    },
)
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

    att = (
        db.query(Attachment)
        .join(Email, Email.id == Attachment.email_id)
        .filter(
            Attachment.id == att_id,
            Email.provider == provider_value,
        )
        .first()
    )
    if not att or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="Attachment not found")

    return FileResponse(
        att.file_path,
        filename=att.filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{att.filename}"'},
    )


@router.post(
    "/{provider}/attachments/download/multiple",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {},
            },
            "description": "Download selected attachments as a zip file.",
        }
    },
)
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
            att = (
                db.query(Attachment)
                .join(Email, Email.id == Attachment.email_id)
                .filter(
                    Attachment.id == att_id,
                    Email.provider == provider_value,
                )
                .first()
            )
            if att and os.path.exists(att.file_path):
                zf.write(att.file_path, att.filename)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=selected.zip"},
    )


@router.get(
    "/{provider}/attachments/download/all",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {},
            },
            "description": "Download all attachments as a zip file.",
        }
    },
)
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
