# schemas/email_schema.py
from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional, List


# ── HR Auth ──
class HRRegisterRequest(BaseModel):
    name:  str
    email: EmailStr

class HRLoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    hr_id:        int
    name:         str
    email:        str
    provider:     str


class AttachmentSchema(BaseModel):
    id:        int
    filename:  str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    is_viewed: bool = False
    viewed_at: Optional[datetime] = None
    view_count: int = 0

    class Config:
        from_attributes = True


class EmailSchema(BaseModel):
    id:              int
    email_id:        str
    provider:        str
    candidate_name:  Optional[str] = None
    candidate_email: Optional[str] = None
    subject:         Optional[str] = None
    body:            Optional[str] = None
    date:            Optional[str] = None
    has_attachments: bool
    attachments:     List[AttachmentSchema] = []

    class Config:
        from_attributes = True


class EmailListResponse(BaseModel):
    provider:  str
    total:     int
    page:      int
    page_size: int
    emails:    List[EmailSchema]


class MonitorStatus(BaseModel):
    provider:      str
    is_running:    bool
    interval_mins: int
    last_check:    Optional[str] = None



class MessageResponse(BaseModel):
    message: str


class MultipleDownloadRequest(BaseModel):
    attachment_ids: List[int]         