from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database.db import get_db
from models.employee import Employee
from schemas.employee_schema import EmployeeRegister, EmployeeLogin, EmployeeLoginResponse
from utils.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/employee", tags=["Employee Auth"])


# ── Register
@router.post("/register", status_code=201)
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
        "message":   "Employee registered successfully",
        "user_id":   employee.id,
        "user_type": employee.user_type
    }


# ── Login

@router.post("/login", response_model=EmployeeLoginResponse)
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
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      employee.id,
        "email":        employee.email,
        "name":         employee.name,
        "user_type":    employee.user_type
    }