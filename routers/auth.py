# routers/auth.py
import os, json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.db import get_db
from models.employee import TokenBlacklist
from models.hr_user import HRUser
from schemas.email_schema import HRLoginResponse, MessageResponse
from utils.security import (
    encrypt_token, decrypt_token,
    create_access_token, decode_token,
    get_current_employee
)
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from msal import PublicClientApplication, SerializableTokenCache
from dotenv import load_dotenv
import requests as http_requests

load_dotenv()

router        = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = HTTPBearer()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]
CREDENTIALS_FILE  = 'credentials.json'
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID")
OUTLOOK_TENANT    = "common"
OUTLOOK_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadBasic",
    "https://graph.microsoft.com/Mail.Send",
    "User.Read",
]


def resolve_employee_hr_user(
    db: Session,
    current_employee: dict,
    provider: str | None = None,
    hr_user_id: int | None = None,
    include_inactive: bool = False,
) -> HRUser:
    employee_id = int(current_employee["sub"])
    query = db.query(HRUser).filter(HRUser.employee_id == employee_id)

    if not include_inactive:
        query = query.filter(HRUser.is_active.is_(True))

    if provider:
        query = query.filter(HRUser.provider == provider)

    if hr_user_id is not None:
        hr_user = query.filter(HRUser.id == hr_user_id).first()
        if not hr_user:
            raise HTTPException(status_code=404, detail="Connected email account not found")
        return hr_user

    hr_users = query.order_by(HRUser.created_at.desc(), HRUser.id.desc()).all()
    if not hr_users:
        raise HTTPException(status_code=404, detail="No connected email account found")
    if len(hr_users) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple connected accounts found. Pass hr_user_id to choose one.",
        )
    return hr_users[0]


# ── Gmail Login/Register
@router.post("/gmail/connect", response_model=HRLoginResponse)
def gmail_connect(
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
):
    try:
        # Step 1 — OAuth login
        flow  = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE, GMAIL_SCOPES
        )
        creds = flow.run_local_server(port=0, prompt='consent')

        # Step 2 — Get HR profile from Google
        resp     = http_requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"}
        )
        profile  = resp.json()
        name     = profile.get("name", "HR User")
        email    = profile.get("email", "")
        employee_id = int(current_employee["sub"])

        # Step 3 — Find or create HR user for the logged-in employee
        hr_user  = (
            db.query(HRUser)
            .filter_by(employee_id=employee_id, email=email, provider="gmail")
            .first()
        )
        if not hr_user:
            hr_user = HRUser(
                employee_id = employee_id,
                name     = name,
                email    = email,
                provider = "gmail"
            )
            db.add(hr_user)
            db.flush()

        # Step 4 — Save encrypted Gmail token
        hr_user.access_token = encrypt_token(creds.to_json())
        hr_user.provider     = "gmail"
        hr_user.is_active    = True
        hr_user.last_login   = func.now()
        db.commit()
        db.refresh(hr_user)

        return {
            "access_token": credentials.credentials,
            "token_type":   "bearer",
            "hr_id":        hr_user.id,
            "employee_id":  employee_id,
            "name":         hr_user.name,
            "email":        hr_user.email,
            "provider":     "gmail"
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Outlook Login/Register
@router.post("/outlook/connect", response_model=HRLoginResponse)
def outlook_connect(
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
):
    try:
        # Step 1 — OAuth login
        cache = SerializableTokenCache()
        app   = PublicClientApplication(
            OUTLOOK_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{OUTLOOK_TENANT}",
            token_cache=cache
        )
        result = app.acquire_token_interactive(
            scopes=OUTLOOK_SCOPES,
            prompt="select_account"
        )

        if "access_token" not in result:
            raise Exception(result.get("error_description", "Auth failed"))

        # Step 2 — Get HR profile from Microsoft
        resp    = http_requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {result['access_token']}"}
        )
        profile = resp.json()
        name    = profile.get("displayName", "HR User")
        email   = profile.get("mail") or profile.get("userPrincipalName", "")
        employee_id = int(current_employee["sub"])

        # Step 3 — Find or create HR user for the logged-in employee
        hr_user = (
            db.query(HRUser)
            .filter_by(employee_id=employee_id, email=email, provider="outlook")
            .first()
        )
        if not hr_user:
            hr_user = HRUser(
                employee_id = employee_id,
                name     = name,
                email    = email,
                provider = "outlook"
            )
            db.add(hr_user)
            db.flush()

        # Step 4 — Save encrypted Outlook token
        hr_user.access_token = encrypt_token(cache.serialize())
        hr_user.provider     = "outlook"
        hr_user.is_active    = True
        hr_user.last_login   = func.now()
        db.commit()
        db.refresh(hr_user)

        return {
            "access_token": credentials.credentials,
            "token_type":   "bearer",
            "hr_id":        hr_user.id,
            "employee_id":  employee_id,
            "name":         hr_user.name,
            "email":        hr_user.email,
            "provider":     "outlook"
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
#Fixed JWT access token not generating — debugged .env loading issue and confirmed SECRET_KEY, ALGORITHM, EXPIRE_MINUTES all loading correctly.

# ── Get Current HR User (Dependency)
def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> HRUser:
    payload = decode_token(token.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    hr_user = db.query(HRUser).filter_by(id=int(payload.get("sub"))).first()
    if not hr_user:
        raise HTTPException(status_code=401, detail="User not found")
    if not hr_user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    return hr_user


# ── Get Profile 
@router.get("/me")
def get_profile(
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
    provider: str | None = None,
    hr_user_id: int | None = None,
):
    hr_user = resolve_employee_hr_user(
        db=db,
        current_employee=current_employee,
        provider=provider,
        hr_user_id=hr_user_id,
    )
    return {
        "employee_id": current_employee.get("employee_id"),
        "employee_email": current_employee.get("employee_email"),
        "name": current_employee.get("name"),
        "role": current_employee.get("role"),
        "session_id": current_employee.get("session_id"),
        "login_at": current_employee.get("login_at"),
        "hr_user_id": hr_user.id,
        "hr_user_email": hr_user.email,
        "hr_user_provider": hr_user.provider,
    }


# ── Logout
@router.post("/logout", response_model=MessageResponse)
def logout(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    current_employee: dict = Depends(get_current_employee),
    provider: str | None = None,
    hr_user_id: int | None = None,
):
    if provider or hr_user_id is not None:
        hr_user = resolve_employee_hr_user(
            db=db,
            current_employee=current_employee,
            provider=provider,
            hr_user_id=hr_user_id,
            include_inactive=True,
        )
        hr_user.access_token = None
        hr_user.is_active = False
        db.commit()
        return {
            "message": f"{hr_user.provider.capitalize()} account disconnected successfully",
            "hr_user_id": hr_user.id,
            "employee_id": int(current_employee.get("employee_id") or 0),
            "provider": hr_user.provider,
        }

    if db.query(TokenBlacklist).filter_by(token=credentials.credentials).first():
        raise HTTPException(status_code=400, detail="Already logged out")

    db.add(TokenBlacklist(token=credentials.credentials))
    db.commit()
    # JWT is stateless — frontend just deletes token
    return {
        "message": f"{current_employee.get('name')} logged out successfully",
        "employee_id": int(current_employee.get("employee_id") or 0),
    }


