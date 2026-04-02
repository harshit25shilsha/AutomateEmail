# services/gmail_service.py
import os, base64, json, re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.header import decode_header
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from models.email_model      import Email
from models.attachment_model import Attachment
from models.hr_user          import HRUser
from utils.security          import decrypt_token

SCOPES         = ['https://www.googleapis.com/auth/gmail.readonly']
ATTACHMENT_DIR = 'attachments/gmail'


# ── Get Service From DB Token 
def get_service(hr_user: HRUser, db: Session):
    if not hr_user.access_token:
        raise Exception("Gmail not connected. Please login again.")

    token_json = decrypt_token(hr_user.access_token)
    creds      = Credentials.from_authorized_user_info(
        json.loads(token_json), SCOPES
    )

    # Auto refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token back to DB
        from utils.security import encrypt_token
        hr_user.access_token = encrypt_token(creds.to_json())
        db.commit()

    return build('gmail', 'v1', credentials=creds)

def is_authenticated(hr_user: HRUser) -> bool:
    return hr_user.provider == "gmail" and hr_user.access_token is not None


# ── Helpers 
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


# ── Fetch & Store Emails 
def fetch_and_store_emails(hr_user: HRUser, db: Session) -> int:
    service = get_service(hr_user, db)
    count = 0
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
            exists = db.query(Email).filter_by(email_id=msg_ref['id']).first()
            if exists:
                continue

            msg     = service.users().messages().get(
                userId='me', id=msg_ref['id'], format='full'
            ).execute()
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}

            from_header     = headers.get("From", "")
            candidate_name, candidate_email = _extract_name_email(from_header)

            email_record = Email(
                email_id        = msg['id'],
                provider        = "gmail",
                candidate_name  = candidate_name,
                candidate_email = candidate_email,
                subject         = _decode_str(headers.get("Subject", "")),
                body            = _get_body(msg['payload']),
                date            = headers.get("Date", ""),
                has_attachments = False
            )
            db.add(email_record)
            db.flush()

            parts = msg['payload'].get("parts", [])
            for part in parts:
                if part.get("filename"):
                    att_data = _save_attachment(service, msg['id'], part)
                    if att_data:
                        db.add(Attachment(
                            email_id  = email_record.id,
                            filename  = att_data["filename"],
                            file_path = att_data["file_path"],
                            file_size = att_data["file_size"],
                            file_type = att_data["file_type"]
                        ))
                        email_record.has_attachments = True

            db.commit()
            count += 1
        
        page_token = results.get('nextPageToken')
        if not page_token:
            break
    
    return count