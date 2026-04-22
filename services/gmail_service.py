# services/gmail_service.py
import os, base64, json, re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from models.email_model      import Email
from models.attachment_model import Attachment
from models.hr_user          import HRUser
from utils.date_utils        import parse_email_datetime
from utils.security          import decrypt_token
from services.extractor         import extract_email_data       
from services.attachment_reader import process_attachment      


SCOPES         = ['https://www.googleapis.com/auth/gmail.readonly',
                  'https://www.googleapis.com/auth/gmail.send']
ATTACHMENT_DIR = 'attachments/gmail'


# ── Get Service From DB Token ─────────────────────────────────
def get_service(hr_user: HRUser, db: Session):
    if not hr_user.access_token:
        raise Exception("Gmail not connected. Please login again.")

    token_json = decrypt_token(hr_user.access_token)
    creds      = Credentials.from_authorized_user_info(
        json.loads(token_json), SCOPES
    )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        from utils.security import encrypt_token
        hr_user.access_token = encrypt_token(creds.to_json())
        db.commit()

    return build('gmail', 'v1', credentials=creds)

def is_authenticated(hr_user: HRUser) -> bool:
    return hr_user.provider == "gmail" and hr_user.access_token is not None


# ── Helpers ───────────────────────────────────────────────────
def _decode_str(value):
    if not value:
        return ""
    decoded, charset = decode_header(value)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(charset or 'utf-8', errors='ignore')
    return decoded

def _extract_name_email(from_header: str):
    match = re.match(r'^(.*?)\s*<([^>]+)>', from_header)
    if match:
        return match.group(1).strip().strip('"'), match.group(2).strip()
    if '@' in from_header:
        return from_header.strip(), from_header.strip()
    return from_header.strip(), ""

def _get_body(payload):
    body_text = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if mime == "text/plain" and data:
                body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                break
            elif mime == "text/html" and data:
                html      = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                body_text = BeautifulSoup(html, "html.parser").get_text()
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return body_text.strip()

def _normalize_plain_text_body(body: str) -> str:
    """
    Normalize line endings before building the MIME message so plain-text
    emails keep their paragraph and line-break structure consistently.
    """
    return (body or "").replace("\r\n", "\n").replace("\r", "\n")

def _save_attachment(service, msg_id, part):
    filename = _decode_str(part.get("filename", ""))
    if not filename:
        return None
    att_id = part["body"].get("attachmentId")
    if not att_id:
        return None

    att  = service.users().messages().attachments().get(
        userId="me", messageId=msg_id, id=att_id
    ).execute()
    data = base64.urlsafe_b64decode(att["data"])

    os.makedirs(ATTACHMENT_DIR, exist_ok=True)
    save_path = os.path.join(ATTACHMENT_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(data)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    return {
        "filename":  filename,
        "file_path": save_path,
        "file_size": len(data),
        "file_type": ext
    }


# Gmail Send Helper
def send_email(
        hr_user: HRUser,db: Session, subject: str,
        body: str, to_email: str,
        bcc_emails : list[str] | None = None,
        is_html: bool = False,
        attachments: list[dict] | None = None,
):
    service = get_service(hr_user, db)
    msg = MIMEMultipart()
    if bcc_emails:
        msg["to"] = "Undisclosed recipients:;"
        msg["bcc"] = ", ".join(sorted(set(bcc_emails)))

    else:
        msg["to"] = to_email

    msg["subject"] = subject

    subtype = "html" if is_html else "plain"
    normalized_body = body if is_html else _normalize_plain_text_body(body)
    msg.attach(MIMEText(normalized_body, subtype, "utf-8"))
    _add_attachments(msg, attachments)

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    return service.users().messages().send(
        userId="me",
        body={"raw": raw_message}
    ).execute()


def _add_attachments(msg, attachments: list[dict] | None = None):
    if not attachments:
        return
    for item in attachments:
        filename = item["filename"]
        file_path = item.get("file_path")
        file_bytes = item.get("file_bytes")
        content_type = item.get("content_type", "application/octet-stream")

        if file_bytes is None and file_path:
            file_bytes = Path(file_path).read_bytes()

        if file_bytes is None:
            continue

        maintype, subtype = (
            content_type.split("/", 1)
            if "/" in content_type
            else ("application", "octet-stream")
        )

        part = MIMEBase(maintype, subtype)
        part.set_payload(file_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)



# ── Fetch & Store Emails ──────────────────────────────────────
def fetch_and_store_emails(hr_user: HRUser, db: Session) -> int:
    service    = get_service(hr_user, db)
    count      = 0
    page_token = None

    while True:
        results = service.users().messages().list(
            userId='me',
            maxResults=500,
            pageToken=page_token
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            break

        for msg_ref in messages:
            exists = (
                db.query(Email)
                .filter_by(email_id=msg_ref["id"], hr_user_id=hr_user.id)
                .first()
            )
            if exists:
                continue

            msg     = service.users().messages().get(
                userId='me', id=msg_ref['id'], format='full'
            ).execute()
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}

            from_header                      = headers.get("From", "")
            candidate_name, candidate_email  = _extract_name_email(from_header)
            subject                          = _decode_str(headers.get("Subject", ""))
            body                             = _get_body(msg['payload'])
            date                             = headers.get("Date", "")

            # ── Collect attachment filenames for extractor ────
            att_names = []
            parts     = msg['payload'].get("parts", [])
            for part in parts:
                fname = _decode_str(part.get("filename", ""))
                if fname:
                    att_names.append(fname)

            # ── Extract job position + is_job_application ─────
            extracted = extract_email_data(
                sender           = from_header,
                subject          = subject,
                raw_body         = body,
                date             = date,
                attachment_names = att_names
            )

            # Use extractor name only if Gmail header name is empty
            final_name = candidate_name or extracted["candidate_name"]

            email_record = Email(
                hr_user_id      = hr_user.id,
                email_id        = msg['id'],
                provider        = "gmail",
                candidate_name  = final_name,
                candidate_email = candidate_email,
                subject         = subject,
                body            = body,
                date            = date,
                received_at     = parse_email_datetime(date),
                has_attachments = False,
                # ── New fields from extractor ─────────────────
                is_job_application = extracted["is_job_application"],
                job_position       = extracted["job_position"],
            )
            db.add(email_record)
            db.flush()

            # ── Save attachments + read content ───────────────
            for part in parts:
                if part.get("filename"):
                    att_data = _save_attachment(service, msg['id'], part)
                    if att_data:
                        # Read resume/CV content for extra info
                        att_info = process_attachment(att_data["file_path"])

                        db.add(Attachment(
                            email_id  = email_record.id,
                            filename  = att_data["filename"],
                            file_path = att_data["file_path"],
                            file_size = att_data["file_size"],
                            file_type = att_data["file_type"],
                            # ── Extra info from resume ────────
                            phone    = att_info.get("phone"),
                            linkedin = att_info.get("linkedin"),
                            github   = att_info.get("github"),
                            skills   = json.dumps(att_info.get("skills", [])),
                            experience = att_info.get("experience"),
                        ))
                        email_record.has_attachments = True

            db.commit()
            count += 1

        page_token = results.get('nextPageToken')
        if not page_token:
            break

    return count
