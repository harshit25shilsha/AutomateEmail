from __future__ import annotations

import re
from datetime import datetime, timedelta
from email.utils import parseaddr

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.db import SessionLocal
from models.email_model import Email
from models.hr_user import HRUser
import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc

PROVIDER_SENDERS = {
    "gmail": gmail_svc.send_email,
    "outlook": outlook_svc.send_email,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_sender_fn(hr_user: HRUser):
    sender = PROVIDER_SENDERS.get(hr_user.provider)
    if not sender:
        raise ValueError(f"Unsupported provider: {hr_user.provider}")
    return sender


def _normalize_email(value: str | None) -> str:
    if not value:
        return ""
    _, email = parseaddr(value)
    normalized = (email or value).strip().lower()
    return normalized


def _is_valid_email(value: str) -> bool:
    return bool(value) and bool(EMAIL_RE.match(value))


def _apply_filters(query, filters):
    if not filters:
        return query

    if getattr(filters, "search", None):
        search = f"%{filters.search}%"
        query = query.filter(
            or_(
                Email.candidate_name.ilike(search),
                Email.candidate_email.ilike(search),
                Email.subject.ilike(search),
            )
        )

    if getattr(filters, "job_position", None):
        query = query.filter(Email.job_position == filters.job_position)

    if getattr(filters, "is_job_application", None) is not None:
        query = query.filter(Email.is_job_application == filters.is_job_application)

    if getattr(filters, "has_attachments", None) is not None:
        query = query.filter(Email.has_attachments == filters.has_attachments)

    if getattr(filters, "date_from", None):
        try:
            date_from_dt = datetime.strptime(filters.date_from, "%d/%m/%Y")
            query = query.filter(Email.received_at >= date_from_dt)
        except ValueError as exc:
            raise ValueError("Invalid date_from format. Use DD/MM/YYYY") from exc

    if getattr(filters, "date_to", None):
        try:
            date_to_dt = datetime.strptime(filters.date_to, "%d/%m/%Y") + timedelta(days=1)
            query = query.filter(Email.received_at < date_to_dt)
        except ValueError as exc:
            raise ValueError("Invalid date_to format. Use DD/MM/YYYY") from exc

    return query


def resolve_recipient_emails(
    db: Session,
    current_user: HRUser,
    mode: str,
    candidate_ids: list[int],
    filters=None,
) -> list[str]:
    query = db.query(Email).filter(
        Email.provider == current_user.provider,
        Email.candidate_email.isnot(None),
        Email.candidate_email != "",
    )

    if mode == "single":
        if len(candidate_ids) != 1:
            raise ValueError("Single mode requires exactly one candidate_id.")
        query = query.filter(Email.id == candidate_ids[0])
    elif mode == "multiple":
        if not candidate_ids:
            raise ValueError("Multiple mode requires at least one candidate_id.")
        query = query.filter(Email.id.in_(candidate_ids))
    elif mode == "all":
        query = _apply_filters(query, filters)
    else:
        raise ValueError("Unsupported outreach mode.")

    rows = query.all()
    recipients: list[str] = []
    seen: set[str] = set()

    for row in rows:
        email = _normalize_email(row.candidate_email)
        if not _is_valid_email(email) or email in seen:
            continue
        seen.add(email)
        recipients.append(email)

    if not recipients:
        raise ValueError("No valid recipients found.")

    if mode == "single" and len(recipients) != 1:
        raise ValueError("Single mode must resolve to exactly one recipient.")

    return recipients


def deliver_outreach_message(
    hr_user_id: int,
    delivery_mode: str,
    subject: str,
    body: str,
    recipient_emails: list[str],
    is_html: bool = False,
) -> dict:
    db = SessionLocal()
    try:
        hr_user = db.query(HRUser).filter(HRUser.id == hr_user_id).first()
        if not hr_user:
            raise ValueError("HR user not found.")

        sender_fn = _get_sender_fn(hr_user)

        unique_recipients = list(dict.fromkeys(recipient_emails))
        if not unique_recipients:
            raise ValueError("No recipients provided.")

        if delivery_mode == "single":
            sender_fn(
                hr_user=hr_user,
                db=db,
                subject=subject,
                body=body,
                to_email=unique_recipients[0],
                bcc_emails=None,
                is_html=is_html,
            )
        else:
            sender_fn(
                hr_user=hr_user,
                db=db,
                subject=subject,
                body=body,
                to_email=hr_user.email,
                bcc_emails=unique_recipients,
                is_html=is_html,
            )

        return {
            "status": "sent",
            "provider": hr_user.provider,
            "queued_count": len(unique_recipients),
        }
    finally:
        db.close()
