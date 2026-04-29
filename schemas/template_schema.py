from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class TemplateCreateRequest(BaseModel):
    template_name: str = Field(min_length=1)
    template_data: str = Field(min_length=1)
    subject: Optional[str] = None

class TemplateUpdateRequest(BaseModel):
    template_name: Optional[str] = Field(None, min_length=1)
    template_data: Optional[str] = None
    subject: Optional[str] = None

class TemplateResponse(BaseModel):
    id: int
    employee_id: int
    template_name:str
    template_data: str
    subject: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attribute = True  # allow schema to read object.property values.

class TemplateListResponse(BaseModel):
    total: int
    templates: List[TemplateResponse]

class TemplateDeleteResponse(BaseModel):
    message: str
    template_id: int
