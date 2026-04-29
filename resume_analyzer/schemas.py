from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field



class ResumeAnalysisResult(BaseModel):
    domain: str = Field(
        description="Detected job domain – must exactly match one entry from the valid_domains list."
    )
    skills: List[str] = Field(description="Top 8-10 skills extracted from the resume.")
    level: str = Field(description="Fresher | Mid-Level | Senior")
    score: float = Field(description="Score out of 100: skills(30) + experience(30) + education(20) + projects/certs(20).")
    summary: str = Field(description="One professional sentence. E.g. 'React developer with 3 years of Redux and API experience.'")
    filename: str = Field(description="FirstName_LastName_DomainSlug_NYrs.pdf  – no spaces, underscores only.")
    folder: str = Field(description="Candidates/DomainSlug/  e.g. Candidates/React_Developer/")



class AnalyzeResumeRequest(BaseModel):
    parsed_resume: Dict[str, Any]
    file_bytes_b64: Optional[str] = None       
    original_filename: Optional[str] = None


class DriveUploadResult(BaseModel):
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    folder_id: Optional[str] = None
    error: Optional[str] = None


class AnalyzeResumeResponse(BaseModel):
    name: str
    email: Optional[str] = None
    domain: str
    skills: List[str]
    level: str
    score: float
    summary: str
    filename: str
    folder: str
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    folder_id: Optional[str] = None
    drive_error: Optional[str] = None
    record_id: Optional[int] = None


class CandidateOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    domain: str
    skills: List[str]
    level: str
    score: float
    summary: str
    filename: str
    folder: str
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True