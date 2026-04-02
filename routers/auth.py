# routers/auth.py
import os, json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database.db import get_db
from models.hr_user import HRUser
from schemas.email_schema import HRLoginResponse, MessageResponse
from utils.security import (
    encrypt_token, decrypt_token,
    create_access_token, decode_token
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

GMAIL_SCOPES      = ['https://www.googleapis.com/auth/gmail.readonly',
                     'https://www.googleapis.com/auth/userinfo.email',
                     'https://www.googleapis.com/auth/userinfo.profile',
                     'openid']
CREDENTIALS_FILE  = 'credentials.json'
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID")
OUTLOOK_TENANT    = "consumers"
OUTLOOK_SCOPES    = ["https://graph.microsoft.com/Mail.Read",
                     "https://graph.microsoft.com/Mail.ReadBasic",
                     "User.Read"]


# ── Gmail Login/Register
@router.post("/gmail/connect", response_model=HRLoginResponse)
def gmail_connect(db: Session = Depends(get_db)):
    try:
        # Step 1 — OAuth login
        flow  = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE, GMAIL_SCOPES
        )
        creds = flow.run_local_server(port=8080, prompt='consent')

        # Step 2 — Get HR profile from Google
        resp     = http_requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"}
        )
        profile  = resp.json()
        name     = profile.get("name", "HR User")
        email    = profile.get("email", "")

        # Step 3 — Find or create HR user
        hr_user  = db.query(HRUser).filter_by(email=email).first()
        if not hr_user:
            hr_user = HRUser(
                name     = name,
                email    = email,
                provider = "gmail"
            )
            db.add(hr_user)
            db.flush()

        # Step 4 — Save encrypted Gmail token
        hr_user.access_token = encrypt_token(creds.to_json())
        hr_user.provider     = "gmail"
        db.commit()
        db.refresh(hr_user)

        # Step 5 — Create tool JWT token
        tool_token = create_access_token({
            "sub":      str(hr_user.id),
            "email":    hr_user.email,
            "provider": "gmail"
        })

        return {
            "access_token": tool_token,
            "token_type":   "bearer",
            "hr_id":        hr_user.id,
            "name":         hr_user.name,
            "email":        hr_user.email,
            "provider":     "gmail"
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Outlook Login/Register
@router.post("/outlook/connect", response_model=HRLoginResponse)
def outlook_connect(db: Session = Depends(get_db)):
    try:
        # Step 1 — OAuth login
        cache = SerializableTokenCache()
        app   = PublicClientApplication(
            OUTLOOK_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{OUTLOOK_TENANT}",
            token_cache=cache
        )
        result = app.acquire_token_interactive(scopes=OUTLOOK_SCOPES)

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

        # Step 3 — Find or create HR user
        hr_user = db.query(HRUser).filter_by(email=email).first()
        if not hr_user:
            hr_user = HRUser(
                name     = name,
                email    = email,
                provider = "outlook"
            )
            db.add(hr_user)
            db.flush()

        # Step 4 — Save encrypted Outlook token
        hr_user.access_token = encrypt_token(cache.serialize())
        hr_user.provider     = "outlook"
        db.commit()
        db.refresh(hr_user)

        # Step 5 — Create tool JWT token
        tool_token = create_access_token({
            "sub":      str(hr_user.id),
            "email":    hr_user.email,
            "provider": "outlook"
        })

        return {
            "access_token": tool_token,
            "token_type":   "bearer",
            "hr_id":        hr_user.id,
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
def get_profile(current_user: HRUser = Depends(get_current_user)):
    return {
        "hr_id":    current_user.id,
        "name":     current_user.name,
        "email":    current_user.email,
        "provider": current_user.provider
    }


# ── Logout
@router.post("/logout", response_model=MessageResponse)
def logout(current_user: HRUser = Depends(get_current_user)):
    # JWT is stateless — frontend just deletes token
    return {"message": f"✅ {current_user.name} logged out successfully"}