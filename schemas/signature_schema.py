from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel , Field

class SignatureCreateRequest(BaseModel):
    signature_name : str = Field(min_length = 1)
    signature_data : str = Field(min_length = 1)


class SignatureUpdateRequest(BaseModel):
    signature_name : Optional[str] = Field(default=None, min_length = 1)
    signature_data : Optional[str] = Field(default=None, min_length = 1)


class SignatureResponse(BaseModel):
    id : int
    employee_id: int
    signature_name: str
    signature_data: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attribute = True


class SignatureListResponse(BaseModel):
    total: int
    signatures: List[SignatureResponse]

class SignatureDeleteResponse(BaseModel):
    message: str
    signature_id: int

