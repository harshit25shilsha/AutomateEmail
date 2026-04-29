import os
import io

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES           = ["https://www.googleapis.com/auth/drive"]
OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN", "token.json")


def _get_oauth_service():
    creds = Credentials.from_authorized_user_file(OAUTH_TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(OAUTH_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, folder_name: str, parent_id: str = None) -> str:
    query = (
        f"name='{folder_name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    files = service.files().list(
        q=query, fields="files(id, name)", spaces="drive"
    ).execute().get("files", [])

    if files:
        return files[0]["id"]

    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    print(f"[DRIVE] Created folder: {folder_name} (id={folder['id']})")
    return folder["id"]


def ensure_folder_path(folder_path: str) -> str:
    service        = _get_oauth_service()
    root_folder_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    parts          = [p for p in folder_path.strip("/").split("/") if p]

    if root_folder_id:
        parent_id     = root_folder_id
        parts_to_walk = parts[1:]  
    else:
        parent_id     = None
        parts_to_walk = parts

    for part in parts_to_walk:
        parent_id = _get_or_create_folder(service, part, parent_id)

    return parent_id


def upload_resume(
    file_bytes:  bytes,
    filename:    str,
    folder_path: str,
    mime_type:   str = "application/pdf",
) -> dict:
    service   = _get_oauth_service()
    folder_id = ensure_folder_path(folder_path)

    existing = service.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id, webViewLink)",
        spaces="drive",
    ).execute().get("files", [])

    if existing:
        print(f"[DRIVE] Already exists, skipping: {filename}")
        return {
            "file_id":    existing[0]["id"],
            "drive_link": existing[0].get("webViewLink", ""),
        }

    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)

    uploaded = service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()

    service.permissions().create(
        fileId=uploaded["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    print(f"[DRIVE] ✓ Uploaded: {filename} → {folder_path} (id={uploaded['id']})")
    return {
        "file_id":    uploaded["id"],
        "drive_link": uploaded.get("webViewLink", ""),
    }


def get_mime_type(filename: str) -> str:
    ext = filename.lower()
    if ext.endswith(".pdf"):
        return "application/pdf"
    if ext.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"