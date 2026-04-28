from typing import List, Optional, Any
from pydantic import BaseModel, Field

class ResumeAnalysisResult(BaseModel):
    domain: str = Field(
        description="Detected job domain e.g. Python Developer, React Developer"
    )
    skills: List[str] = Field(
        description="Top 5-8 relevant technical skills found in the resume"
    )
    level: str = Field(
        description="Experience level: Fresher, Mid-Level, or Senior"
    )
    score: float = Field(
        description="Resume score out of 100 based on skills, experience, education, quality"
    )
    summary: str = Field(
        description="One concise professional summary sentence"
    )
    filename: str = Field(
        description="Generated professional filename e.g. John_Doe_Python_Developer_3Yrs.pdf"
    )
    folder: str = Field(
        description="Google Drive folder path e.g. Candidates/Python_Developer/"
    )



class ResumeAnalysisRecord(BaseModel):
    id:              int
    candidate_name:  Optional[str]
    candidate_email: Optional[str]
    domain:          str
    skills:          Optional[Any]
    level:           Optional[str]
    score:           Optional[float]
    summary:         Optional[str]
    filename:        Optional[str]
    folder_path:     Optional[str]
    drive_link:      Optional[str]
    drive_file_id:   Optional[str]
    source:          Optional[str]
    provider:        Optional[str]
    created_at:      Optional[str]

    class Config:
        from_attributes = True



class StatusWrapper(BaseModel):
    httpCode: str
    success:  bool
    message:  str