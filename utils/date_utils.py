from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_email_datetime(value: str | datetime | None) -> datetime | None:
    if not value:
        return None

    if isinstance(value, datetime):
        return _ensure_aware_utc(value)

    text = value.strip()
    if not text:
        return None

    try:
        return _ensure_aware_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass

    try:
        return _ensure_aware_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass

    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return _ensure_aware_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue

    return None


def format_email_datetime(
    received_at: datetime | None,
    raw_value: str | None = None,
    tz: timezone = IST,
) -> dict[str, str | None]:
    dt = parse_email_datetime(received_at) or parse_email_datetime(raw_value)
    if not dt:
        return {"date": raw_value or None, "time": None}

    display_dt = dt.astimezone(tz)
    return {
        "date": display_dt.strftime("%d/%m/%Y"),
        "time": display_dt.strftime("%H:%M"),
    }
