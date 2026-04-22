# schemas/email_schema.py
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from enum import Enum

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
    is_downloaded: bool = False
    downloaded_at: Optional[datetime] = None
    download_count: int = 0

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



# Request and Response models for email Sending 

class OutreachMode(str, Enum):
    single = "single"
    multiple = "multiple"
    all = "all"

class OutreachFilters(BaseModel):
    search: Optional[str] = None
    job_position: Optional[str] = None
    is_job_application: Optional[bool] = None
    has_attachments: Optional[bool] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None

class OutreachSendRequest(BaseModel):
    mode: OutreachMode
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    # Selected Email.id values from the inbox table
    candidate_ids: List[int] = Field(default_factory=list)
    filters: Optional[OutreachFilters] = None
    is_html: bool = False

class OutreachRecipient(BaseModel):
    candidate_id: int
    email: EmailStr

class OutreachSendResult(BaseModel):
    email_id: int
    recipient_email: EmailStr
    candidate_name: str
    job_role: str
    status: str
    error: Optional[str] = None

class OutreachSendResponse(BaseModel):
    batch_id: str
    status: str
    provider: str
    total_selected: int
    sent_count: int
    failed_count: int
    message: str
    results: List[OutreachSendResult] = Field(default_factory=list)
