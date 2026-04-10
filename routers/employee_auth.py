from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database.db import get_db
from models.employee import Employee, TokenBlacklist
from schemas.employee_schema import (
    EmployeeRegister, EmployeeLogin,
    RegisterResponse, LoginResponse
)
from utils.security import hash_password, verify_password, create_access_token
from fastapi.security import HTTPAuthorizationCredentials
from utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_employee,
    bearer_scheme
    )

router = APIRouter(prefix="/employee", tags=["Employee Auth"])

# ── Register
@router.post("/register", status_code=201, response_model=RegisterResponse)
def register(payload: EmployeeRegister, db: Session = Depends(get_db)):

    if db.query(Employee).filter_by(email=payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if db.query(Employee).filter_by(mobile=payload.mobile).first():
        raise HTTPException(status_code=400, detail="Mobile number already registered")

    employee = Employee(
        name      = payload.name,
        email     = payload.email,
        password  = hash_password(payload.password),
        mobile    = payload.mobile,
        gender    = payload.gender,
        user_type = payload.user_type
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    return {
        "success": True,
        "status_code": 201,
        "message": "Employee registered successfully",
        "data": {
            "user_id":   employee.id,
            "user_type": employee.user_type
        }
    }


# ── Login
@router.post("/login", status_code=200, response_model=LoginResponse)
def login(payload: EmployeeLogin, db: Session = Depends(get_db)):

    if payload.email:
        employee = db.query(Employee).filter_by(email=payload.email).first()
    elif payload.mobile:
        employee = db.query(Employee).filter_by(mobile=payload.mobile).first()
    else:
        raise HTTPException(status_code=400, detail="Provide email or mobile to login")

    if not employee or not verify_password(payload.password, employee.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not employee.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token({
        "sub":   str(employee.id),
        "email": employee.email,
        "role":  employee.user_type
    })

    return {
        "success": True,
        "status_code": 200,
        "message": "Login successful",
        "data": {
            "access_token": token,
            "token_type":   "bearer",
            "user_id":      employee.id,
            "email":        employee.email,
            "name":         employee.name,
            "user_type":    employee.user_type
        }
    }


@router.post("/logout")
def logout(
    current_employee: dict = Depends(get_current_employee),  
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    
    if db.query(TokenBlacklist).filter_by(token=token).first():
        raise HTTPException(status_code=400, detail="Already logged out")
    
    blacklisted = TokenBlacklist(token=token)
    db.add(blacklisted)
    db.commit()
    return {"message": "Logged out successfully"}