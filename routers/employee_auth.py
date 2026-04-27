from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database.db import get_db
from models.employee import Employee, TokenBlacklist
from models.hr_user import HRUser
from schemas.employee_schema import (
    EmployeeRegister, EmployeeLogin,
    RegisterResponse, LoginResponse,
    EmployeeConnectedAccountsResponse,
    ConnectedEmailAccount,
    EmployeeSummary,
    EmployeesListResponse,
    ConnectedMailAccountDetail,
    ConnectedMailAccountsResponse,
)
from fastapi.security import HTTPAuthorizationCredentials
from utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_employee,
    bearer_scheme
)
from datetime import datetime, timezone
import uuid

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

    session_id = str(uuid.uuid4())
    login_at = datetime.now(timezone.utc).isoformat()
    token = create_access_token({
        "sub":            str(employee.id),
        "employee_id":    employee.id,
        "employee_email":  employee.email,
        "name":           employee.name,
        "role":           employee.user_type,
        "session_id":     session_id,
        "login_at":       login_at,
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


@router.get("/me/connected-accounts", response_model=EmployeeConnectedAccountsResponse)
def get_connected_accounts(
    current_employee: dict = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    employee_id = int(current_employee["sub"])
    employee = db.query(Employee).filter_by(id=employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    accounts = (
        db.query(HRUser)
        .filter(
            HRUser.employee_id == employee_id,
            HRUser.is_active.is_(True),
        )
        .order_by(HRUser.provider.asc(), HRUser.created_at.desc())
        .all()
    )

    gmail_accounts = [
        ConnectedEmailAccount(
            id=account.id,
            name=account.name,
            email=account.email,
            provider=account.provider,
            created_at=account.created_at,
            last_login=account.last_login,
        )
        for account in accounts
        if account.provider == "gmail"
    ]
    outlook_accounts = [
        ConnectedEmailAccount(
            id=account.id,
            name=account.name,
            email=account.email,
            provider=account.provider,
            created_at=account.created_at,
            last_login=account.last_login,
        )
        for account in accounts
        if account.provider == "outlook"
    ]

    return {
        "employee_id": employee.id,
        "employee_email": employee.email,
        "total_connected_accounts": len(accounts),
        "gmail_count": len(gmail_accounts),
        "outlook_count": len(outlook_accounts),
        "gmail_accounts": gmail_accounts,
        "outlook_accounts": outlook_accounts,
    }


@router.get("/getallconnectedmails", response_model=ConnectedMailAccountsResponse)
def get_all_connected_mails(
    current_employee: dict = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    employee_id = int(current_employee["sub"])
    employee = db.query(Employee).filter_by(id=employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    accounts = (
        db.query(HRUser)
        .filter(HRUser.employee_id == employee_id)
        .order_by(HRUser.provider.asc(), HRUser.created_at.desc(), HRUser.id.desc())
        .all()
    )

    return {
        "employee_id": employee.id,
        "employee_email": employee.email,
        "total_connected_accounts": len(accounts),
        "accounts": [
            ConnectedMailAccountDetail(
                hr_user_id=account.id,
                name=account.name,
                email=account.email,
                provider=account.provider,
                is_active=account.is_active,
                created_at=account.created_at,
                last_login=account.last_login,
            )
            for account in accounts
        ],
    }


@router.get("/all", response_model=EmployeesListResponse)
def get_all_employees(
    current_employee: dict = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).order_by(Employee.id.asc()).all()
    return {
        "total": len(employees),
        "employees": [
            EmployeeSummary(
                id=employee.id,
                name=employee.name,
                email=employee.email,
                mobile=employee.mobile,
                gender=employee.gender,
                user_type=employee.user_type,
                is_active=employee.is_active,
            )
            for employee in employees
        ],
    }
