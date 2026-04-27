import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database.db import get_db
from models.hr_user import HRUser
from routers.auth import resolve_employee_hr_user
from schemas.email_schema import OutreachFilters, OutreachMode, OutreachSendRequest, OutreachSendResponse
from services.outreach_service import resolve_recipient_targets, deliver_outreach_message
import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc
from utils.security import get_current_employee

router = APIRouter(prefix="/outreach", tags=["Outreach"])

PROVIDER_AUTH = {
    "gmail": gmail_svc,
    "outlook": outlook_svc,
}


def _run_outreach_send(
    payload: OutreachSendRequest,
    db: Session,
    current_user: HRUser,
    attachments: list[dict] | None = None,
):
    provider_svc = PROVIDER_AUTH.get(current_user.provider)
    if not provider_svc:
        raise HTTPException(status_code=400, detail="Unsupported email provider.")

    if not provider_svc.is_authenticated(current_user):
        raise HTTPException(
            status_code=401,
            detail=f"{current_user.provider.capitalize()} not connected.",
        )

    try:
        recipient_targets = resolve_recipient_targets(
            db=db,
            current_user=current_user,
            mode=payload.mode.value,
            candidate_ids=payload.candidate_ids,
            filters=payload.filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    batch_id = str(uuid.uuid4())

    try:
        delivery_summary = deliver_outreach_message(
            db=db,
            hr_user=current_user,
            delivery_mode=payload.mode.value,
            subject=payload.subject,
            body=payload.body,
            recipient_targets=recipient_targets,
            is_html=payload.is_html,
            attachments=attachments,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    delivery_summary.update(
        {
            "batch_id": batch_id,
            "message": (
                "Outreach email sent successfully"
                if delivery_summary["failed_count"] == 0
                else "Outreach email sent with some failures"
                if delivery_summary["sent_count"] > 0
                else "Outreach email delivery failed"
            ),
        }
    )
    return delivery_summary


@router.post(
    "/send",
    response_model=OutreachSendResponse,
    description="Send outreach emails to candidates based on specified mode and filters., Modes: single (specific candidates), multiple (filtered candidates), all (all candidates).",
)
async def send_outreach(
    mode: OutreachMode = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    candidate_ids: list[int] = Form(default=[]),
    search: str | None = Form(default=None),
    job_position: str | None = Form(default=None),
    is_job_application: bool | None = Form(default=None),
    has_attachments: bool | None = Form(default=None),
    date_from: str | None = Form(default=None),
    date_to: str | None = Form(default=None),
    is_html: bool = Form(default=False),
    hr_user_id: int | None = Form(default=None),
    attachments: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    try:
        filters = None
        if any(
            value is not None
            for value in (search, job_position, is_job_application, has_attachments, date_from, date_to)
        ):
            filters = OutreachFilters(
                search=search,
                job_position=job_position,
                is_job_application=is_job_application,
                has_attachments=has_attachments,
                date_from=date_from,
                date_to=date_to,
            )

        payload = OutreachSendRequest(
            mode=mode,
            subject=subject,
            body=body,
            candidate_ids=candidate_ids,
            filters=filters,
            is_html=is_html,
        )

        attachment_payloads: list[dict] = []
        for file in attachments:
            attachment_payloads.append(
                {
                    "filename": file.filename,
                    "file_bytes": await file.read(),
                    "content_type": file.content_type or "application/octet-stream",
                }
            )

    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    current_user = resolve_employee_hr_user(
        db=db,
        current_employee=current_employee,
        hr_user_id=hr_user_id,
    )

    return _run_outreach_send(payload, db, current_user, attachments=attachment_payloads)
