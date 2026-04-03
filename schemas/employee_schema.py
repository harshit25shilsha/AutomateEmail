from pydantic import BaseModel, EmailStr, field_validator, model_validator
from enum import Enum
from typing import Optional

class GenderEnum(str, Enum):
    male   = "male"
    female = "female"
    other  = "other"

class UserTypeEnum(str, Enum):
    employee = "employee"
    manager  = "manager"
    admin    = "admin"
    hr = "hr"

class EmployeeRegister(BaseModel):
    name:      str
    email:     EmailStr
    password:  str
    mobile:    str
    gender:    GenderEnum
    user_type: UserTypeEnum

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if not v.isdigit():
            raise ValueError("Mobile number must contain digits only")
        if len(v) != 10:
            raise ValueError("Mobile number must be exactly 10 digits")
        return v


class EmployeeLogin(BaseModel):
    email:    Optional[EmailStr] = None
    mobile:   Optional[str]     = None
    password: str

    @model_validator(mode="after")
    def check_email_or_mobile(self):
        if not self.email and not self.mobile:
            raise ValueError("Provide either email or mobile to login")
        return self

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if v is None:
            return v
        if not v.isdigit():
            raise ValueError("Mobile number must contain digits only")
        if len(v) != 10:
            raise ValueError("Mobile number must be exactly 10 digits")
        return v
    
  
class EmployeeLoginResponse(BaseModel):
    access_token: str
    token_type:   str
    user_id:      int
    email:        str
    name:         str
    user_type:    str         