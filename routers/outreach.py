import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from models.hr_user import HRUser
from routers.auth import get_current_user
from schemas.email_schema import OutreachSendRequest, OutreachSendResponse
from services.outreach_service import resolve_recipient_emails, deliver_outreach_message
import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc

router = APIRouter(prefix="/outreach", tags=["Outreach"])

PROVIDER_AUTH = {
    "gmail": gmail_svc,
    "outlook": outlook_svc,
}


@router.post("/send", response_model=OutreachSendResponse)
def send_outreach(
    payload: OutreachSendRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: HRUser = Depends(get_current_user),
):
    provider_svc = PROVIDER_AUTH.get(current_user.provider)
    if not provider_svc:
        raise HTTPException(status_code=400, detail="Unsupported email provider.")

    if not provider_svc.is_authenticated(current_user):
        raise HTTPException(status_code=401, detail=f"{current_user.provider.capitalize()} not connected.")

    try:
        recipient_emails = resolve_recipient_emails(
            db=db,
            current_user=current_user,
            mode=payload.mode.value,
            candidate_ids=payload.candidate_ids,
            filters=payload.filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    batch_id = str(uuid.uuid4())
    background_tasks.add_task(
        deliver_outreach_message,
        current_user.id,
        payload.mode.value,
        payload.subject,
        payload.body,
        recipient_emails,
        payload.is_html,
    )

    return {
        "batch_id": batch_id,
        "status": "queued",
        "provider": current_user.provider,
        "queued_count": len(recipient_emails),
        "message": "Outreach email queued for delivery",
    }
