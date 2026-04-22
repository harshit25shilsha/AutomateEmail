from __future__ import annotations

import re
from datetime import datetime, timedelta
from email.utils import parseaddr

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.candidate import Candidate
from models.email_model import Email
from models.hr_user import HRUser
import services.gmail_service as gmail_svc
import services.outlook_service as outlook_svc

PROVIDER_SENDERS = {
    "gmail": gmail_svc.send_email,
    "outlook": outlook_svc.send_email,
}

OutlookSendError = getattr(outlook_svc, "OutlookSendError", Exception)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


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


def _order_email_rows(rows: list[Email], preserve_request_order: bool) -> list[Email]:
    """
    When preserve_request_order is True, the last occurrence for a recipient
    wins because the request order is the source of truth.
    When False, the rows should already be sorted from newest to oldest, so the
    first occurrence for a recipient wins.
    """
    chosen: dict[str, tuple[int, Email]] = {}

    for index, row in enumerate(rows):
        email = _normalize_email(row.candidate_email)
        if not _is_valid_email(email):
            continue

        if preserve_request_order:
            chosen[email] = (index, row)
        else:
            chosen.setdefault(email, (index, row))

    ordered = sorted(chosen.values(), key=lambda item: item[0])
    return [row for _, row in ordered]


def _load_candidate_for_email(db: Session, email_address: str) -> Candidate | None:
    normalized = _normalize_email(email_address)
    if not normalized:
        return None

    return (
        db.query(Candidate)
        .filter(func.lower(Candidate.email) == normalized)
        .order_by(Candidate.id.desc())
        .first()
    )


def _build_personalization_context(db: Session, email_row: Email) -> dict:
    candidate = _load_candidate_for_email(db, email_row.candidate_email or "")

    candidate_name = (
        (candidate.name.strip() if candidate and candidate.name else "")
        or (email_row.candidate_name or "").strip()
        or "Candidate"
    )
    job_role = (email_row.job_position or "").strip() or "Applied Role"

    return {
        "email_id": email_row.id,
        "recipient_email": _normalize_email(email_row.candidate_email),
        "candidate_name": candidate_name,
        "job_role": job_role,
    }


def _render_template(template: str, context: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        if key in {"name", "candidate_name"}:
            return context["candidate_name"]
        if key in {"job_role", "job_position", "role"}:
            return context["job_role"]
        return match.group(0)

    return PLACEHOLDER_RE.sub(replace, template)


def resolve_recipient_targets(
    db: Session,
    current_user: HRUser,
    mode: str,
    candidate_ids: list[int],
    filters=None,
) -> list[dict]:
    query = db.query(Email).filter(
        Email.provider == current_user.provider,
        Email.hr_user_id == current_user.id,
        Email.candidate_email.isnot(None),
        Email.candidate_email != "",
    )

    if mode == "single":
        if len(candidate_ids) != 1:
            raise ValueError("Single mode requires exactly one candidate_id.")
        query = query.filter(Email.id == candidate_ids[0])
        rows = query.all()
        rows = _order_email_rows(rows, preserve_request_order=True)
    elif mode == "multiple":
        if not candidate_ids:
            raise ValueError("Multiple mode requires at least one candidate_id.")
        query = query.filter(Email.id.in_(candidate_ids))
        rows_by_id = {row.id: row for row in query.all()}
        ordered_rows = [rows_by_id[candidate_id] for candidate_id in candidate_ids if candidate_id in rows_by_id]
        rows = _order_email_rows(ordered_rows, preserve_request_order=True)
    elif mode == "all":
        query = _apply_filters(query, filters)
        rows = query.order_by(
            Email.received_at.is_(None),
            Email.received_at.desc(),
            Email.id.desc(),
        ).all()
        rows = _order_email_rows(rows, preserve_request_order=False)
    else:
        raise ValueError("Unsupported outreach mode.")

    if not rows:
        raise ValueError("No valid recipients found.")

    targets = []
    for row in rows:
        context = _build_personalization_context(db, row)
        if not context["recipient_email"] or not _is_valid_email(context["recipient_email"]):
            continue
        targets.append(
            {
                **context,
                "subject": row.subject or "",
                "body": row.body or "",
            }
        )

    if not targets:
        raise ValueError("No valid recipients found.")

    return targets


def resolve_recipient_emails(
    db: Session,
    current_user: HRUser,
    mode: str,
    candidate_ids: list[int],
    filters=None,
) -> list[str]:
    targets = resolve_recipient_targets(
        db=db,
        current_user=current_user,
        mode=mode,
        candidate_ids=candidate_ids,
        filters=filters,
    )
    return [target["recipient_email"] for target in targets]


def deliver_outreach_message(
    db: Session,
    hr_user: HRUser,
    delivery_mode: str,
    subject: str,
    body: str,
    recipient_targets: list[dict],
    is_html: bool = False,
    attachments: list[dict] | None = None,
) -> dict:
    sender_fn = _get_sender_fn(hr_user)

    if not recipient_targets:
        raise ValueError("No recipients provided.")

    results = []
    sent_count = 0
    failed_count = 0

    for target in recipient_targets:
        rendered_subject = _render_template(subject, target)
        rendered_body = _render_template(body, target)

        try:
            sender_fn(
                hr_user=hr_user,
                db=db,
                subject=rendered_subject,
                body=rendered_body,
                to_email=target["recipient_email"],
                bcc_emails=None,
                is_html=is_html,
                attachments=attachments,
            )
            sent_count += 1
            results.append(
                {
                    "email_id": target["email_id"],
                    "recipient_email": target["recipient_email"],
                    "candidate_name": target["candidate_name"],
                    "job_role": target["job_role"],
                    "status": "sent",
                    "error": None,
                }
            )
        except Exception as exc:
            failed_count += 1
            results.append(
                {
                    "email_id": target["email_id"],
                    "recipient_email": target["recipient_email"],
                    "candidate_name": target["candidate_name"],
                    "job_role": target["job_role"],
                    "status": "failed",
                    "error": getattr(exc, "user_message", str(exc)),
                }
            )

    overall_status = "sent" if failed_count == 0 else "partial_success" if sent_count > 0 else "failed"

    return {
        "status": overall_status,
        "provider": hr_user.provider,
        "total_selected": len(recipient_targets),
        "sent_count": sent_count,
        "failed_count": failed_count,
        "results": results,
    }
