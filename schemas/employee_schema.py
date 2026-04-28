import re
from pydantic import BaseModel, EmailStr, field_validator, model_validator
from enum import Enum
from datetime import datetime
from typing import Optional, List

class GenderEnum(str, Enum):
    male   = "male"
    female = "female"
    other  = "other"

class UserTypeEnum(str, Enum):
    employee = "employee"
    manager  = "manager"
    admin    = "admin"
    hr = "hr"

def validate_password_strength(password:str)-> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase character")
    if not re.search(r"\d",password):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[^A-Za-z0-9]",password):
        raise ValueError("Password must contain at least one special character")
    return password
class EmployeeRegister(BaseModel):
    name:      str
    email:     EmailStr
    password:  str
    mobile:    str
    gender:    GenderEnum
    user_type: UserTypeEnum

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return validate_password_strength(v)

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

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return validate_password_strength(v)

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


# ── Response Schemas

class EmployeeLoginResponse(BaseModel):     
    access_token: str
    token_type:   str
    user_id:      int
    email:        str
    name:         str
    user_type:    str


class ConnectedEmailAccount(BaseModel):
    id: int
    name: str
    email: str
    provider: str
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None


class EmployeeConnectedAccountsResponse(BaseModel):
    employee_id: int
    employee_email: str
    total_connected_accounts: int
    gmail_count: int
    outlook_count: int
    gmail_accounts: List[ConnectedEmailAccount]
    outlook_accounts: List[ConnectedEmailAccount]


class EmployeeSummary(BaseModel):
    id: int
    name: str
    email: str
    mobile: str
    gender: Optional[str] = None
    user_type: str
    is_active: bool


class EmployeesListResponse(BaseModel):
    total: int
    employees: List[EmployeeSummary]


class ConnectedMailAccountDetail(BaseModel):
    hr_user_id: int
    name: str
    email: str
    provider: str
    is_active: bool
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None


class ConnectedMailAccountsResponse(BaseModel):
    employee_id: int
    employee_email: str
    total_connected_accounts: int
    accounts: List[ConnectedMailAccountDetail]


class RegisterData(BaseModel):
    user_id:   int
    user_type: str

class RegisterResponse(BaseModel):
    success: bool
    status_code: int
    message: str
    data:    RegisterData


class LoginData(BaseModel):
    access_token: str
    token_type:   str
    user_id:      int
    email:        str
    name:         str
    user_type:    str

class LoginResponse(BaseModel):
    success: bool
    status_code: int
    message: str
    data:    LoginData
