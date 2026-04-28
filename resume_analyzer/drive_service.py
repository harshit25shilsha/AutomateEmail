import os
import io
from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES               = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "drive_credentials.json")



@lru_cache(maxsize=1)
def _get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)



def _get_or_create_folder(service, folder_name: str, parent_id: str = None) -> str:

    query = (
        f"name='{folder_name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = (
        service.files()
        .list(q=query, fields="files(id, name)", spaces="drive")
        .execute()
    )
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    print(f"[DRIVE] Created folder: {folder_name} (id={folder['id']})")
    return folder["id"]


def ensure_folder_path(folder_path: str) -> str:
    service = _get_drive_service()
    parts   = [p for p in folder_path.strip("/").split("/") if p]

    parent_id = None
    for part in parts:
        parent_id = _get_or_create_folder(service, part, parent_id)

    return parent_id



def upload_resume(
    file_bytes: bytes,
    filename:   str,
    folder_path: str,
    mime_type:  str = "application/pdf",
) -> dict:
    service   = _get_drive_service()
    folder_id = ensure_folder_path(folder_path)

    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)

    uploaded = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, webViewLink")
        .execute()
    )

    service.permissions().create(
        fileId=uploaded["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    result = {
        "file_id":    uploaded["id"],
        "drive_link": uploaded.get("webViewLink", ""),
    }
    print(f"[DRIVE] ✓ Uploaded: {filename} → {folder_path}")
    return result


def get_mime_type(filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        return "application/pdf"
    if filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"