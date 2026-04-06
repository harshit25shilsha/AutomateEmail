# services/outlook_service.py
import os, json, requests, base64, re
from msal import PublicClientApplication, SerializableTokenCache
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from models.email_model      import Email
from models.attachment_model import Attachment
from models.hr_user          import HRUser
from utils.security          import encrypt_token, decrypt_token
from services.extractor         import extract_email_data        # ← added
from services.attachment_reader import process_attachment         # ← added
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID      = os.getenv("OUTLOOK_CLIENT_ID")
TENANT_ID      = "consumers"
SCOPES         = ["https://graph.microsoft.com/Mail.Read",
                  "https://graph.microsoft.com/Mail.ReadBasic"]
ATTACHMENT_DIR = "attachments/outlook"


# ── Get Token From DB ─────────────────────────────────────────
def get_access_token(hr_user: HRUser, db: Session):
    if not hr_user.access_token:
        raise Exception("Outlook not connected. Please login again.")

    cache = SerializableTokenCache()
    cache.deserialize(decrypt_token(hr_user.access_token))

    app = PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache
    )

    accounts = app.get_accounts()
    result   = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result or "access_token" not in result:
        raise Exception("Outlook token expired. Please login again.")

    if cache.has_state_changed:
        hr_user.access_token = encrypt_token(cache.serialize())
        db.commit()

    return result["access_token"]

def is_authenticated(hr_user: HRUser) -> bool:
    return hr_user.provider == "outlook" and hr_user.access_token is not None


# ── Helpers ───────────────────────────────────────────────────
def _extract_name_email(sender_obj: dict):
    email_obj = sender_obj.get("emailAddress", {})
    return email_obj.get("name", "").strip(), email_obj.get("address", "").strip()

def _get_body(email_data):
    body         = email_data.get("body", {})
    content_type = body.get("contentType", "text")
    content      = body.get("content", "")
    if content_type == "html":
        return BeautifulSoup(content, "html.parser").get_text(separator="\n").strip()
    return content.strip()

def _save_attachment(token, message_id):
    headers     = {"Authorization": f"Bearer {token}"}
    url         = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments"
    response    = requests.get(url, headers=headers)
    attachments = []
    if response.status_code != 200:
        return attachments
    for att in response.json().get("value", []):
        filename = att.get("name", "unknown")
        att_type = att.get("@odata.type", "")
        if "#microsoft.graph.fileAttachment" in att_type:
            content   = base64.b64decode(att.get("contentBytes", ""))
            os.makedirs(ATTACHMENT_DIR, exist_ok=True)
            save_path = os.path.join(ATTACHMENT_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(content)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
            attachments.append({
                "filename":  filename,
                "file_path": save_path,
                "file_size": len(content),
                "file_type": ext
            })
    return attachments


# ── Fetch & Store Emails ──────────────────────────────────────
def fetch_and_store_emails(hr_user: HRUser, db: Session):
    token     = get_access_token(hr_user, db)
    headers   = {"Authorization": f"Bearer {token}"}
    skip      = 0
    new_count = 0

    while True:
        url = (
            f"https://graph.microsoft.com/v1.0/me/messages"
            f"?$top=50"
            f"&$skip={skip}"
            f"&$orderby=receivedDateTime desc"
            f"&$select=subject,from,receivedDateTime,body,hasAttachments,id"
        )

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch: {response.text}")

        emails = response.json().get("value", [])
        if not emails:
            break

        for email_data in emails:
            msg_id = email_data.get("id", "")

            exists = db.query(Email).filter_by(email_id=msg_id).first()
            if exists:
                continue

            candidate_name, candidate_email = _extract_name_email(
                email_data.get("from", {})
            )
            subject = email_data.get("subject", "")
            body    = _get_body(email_data)
            date    = email_data.get("receivedDateTime", "")

            # ── Save attachments first to get filenames ───────
            att_list  = _save_attachment(token, msg_id)
            att_names = [a["filename"] for a in att_list]

            # ── Extract job position + is_job_application ─────
            # Build sender string same format as Gmail "Name <email>"
            sender_str = f"{candidate_name} <{candidate_email}>"
            extracted  = extract_email_data(
                sender           = sender_str,
                subject          = subject,
                raw_body         = body,
                date             = date,
                attachment_names = att_names
            )

            email_record = Email(
                email_id        = msg_id,
                provider        = "outlook",
                candidate_name  = candidate_name or extracted["candidate_name"],
                candidate_email = candidate_email,
                subject         = subject,
                body            = body,
                date            = date,
                has_attachments = False,
                # ── New fields from extractor ─────────────────
                is_job_application = extracted["is_job_application"],
                job_position       = extracted["job_position"],
            )
            db.add(email_record)
            db.flush()

            # ── Save attachments + read content ───────────────
            for att_data in att_list:
                # Read resume/CV content for extra info
                att_info = process_attachment(att_data["file_path"])

                db.add(Attachment(
                    email_id  = email_record.id,
                    filename  = att_data["filename"],
                    file_path = att_data["file_path"],
                    file_size = att_data["file_size"],
                    file_type = att_data["file_type"],
                    # ── Extra info from resume ────────────────
                    phone      = att_info.get("phone"),
                    linkedin   = att_info.get("linkedin"),
                    github     = att_info.get("github"),
                    skills     = json.dumps(att_info.get("skills", [])),
                    experience = att_info.get("experience"),
                ))
                email_record.has_attachments = True

            db.commit()
            new_count += 1

        skip += 50
        if len(emails) < 50:
            break

    return new_count
