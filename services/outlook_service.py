# services/outlook_service.py
import os, json, requests, base64, re
from msal import PublicClientApplication, SerializableTokenCache
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from models.email_model      import Email
from models.attachment_model import Attachment
from models.hr_user          import HRUser
from utils.security          import encrypt_token, decrypt_token
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID      = os.getenv("OUTLOOK_CLIENT_ID")
TENANT_ID      = "consumers"
SCOPES         = ["https://graph.microsoft.com/Mail.Read",
                  "https://graph.microsoft.com/Mail.ReadBasic"]
ATTACHMENT_DIR = "attachments/outlook"


# ── Get Token From DB 
def get_access_token(hr_user: HRUser, db: Session):
    if not hr_user.access_token:
        raise Exception("Outlook not connected. Please login again.")

    cache = SerializableTokenCache()
    cache.deserialize(decrypt_token(hr_user.access_token))

    app    = PublicClientApplication(
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

    # Save refreshed token back to DB
    if cache.has_state_changed:
        hr_user.access_token = encrypt_token(cache.serialize())
        db.commit()

    return result["access_token"]

def is_authenticated(hr_user: HRUser) -> bool:
    return hr_user.provider == "outlook" and hr_user.access_token is not None


# ── Helpers 
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


# ── Fetch & Store Emails 
def fetch_and_store_emails(
    hr_user:     HRUser,
    db:          Session,
    max_results: int = 50,
    after_date:  str = None
):
    token      = get_access_token(hr_user, db)
    headers    = {"Authorization": f"Bearer {token}"}
    filter_str = f"&$filter=receivedDateTime gt {after_date}" if after_date else ""

    url = (
        f"https://graph.microsoft.com/v1.0/me/messages"
        f"?$top={max_results}"
        f"&$orderby=receivedDateTime desc"
        f"&$select=subject,from,receivedDateTime,body,hasAttachments,id"
        f"{filter_str}"
    )

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch: {response.text}")

    emails    = response.json().get("value", [])
    new_count = 0

    for email_data in emails:
        msg_id = email_data.get("id", "")

        exists = db.query(Email).filter_by(email_id=msg_id).first()
        if exists:
            continue

        # Only store emails with attachments
        if not email_data.get("hasAttachments"):
            continue

        candidate_name, candidate_email = _extract_name_email(
            email_data.get("from", {})
        )

        email_record = Email(
            email_id        = msg_id,
            provider        = "outlook",
            candidate_name  = candidate_name,
            candidate_email = candidate_email,
            subject         = email_data.get("subject", ""),
            body            = _get_body(email_data),
            date            = email_data.get("receivedDateTime", ""),
            has_attachments = False
        )
        db.add(email_record)
        db.flush()

        att_list = _save_attachment(token, msg_id)
        for att_data in att_list:
            db.add(Attachment(
                email_id  = email_record.id,
                filename  = att_data["filename"],
                file_path = att_data["file_path"],
                file_size = att_data["file_size"],
                file_type = att_data["file_type"]
            ))
            email_record.has_attachments = True

        db.commit()
        new_count += 1

    return new_count