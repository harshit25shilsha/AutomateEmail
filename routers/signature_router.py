from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.db import get_db
from models.signature import Signature
from schemas.signature_schema import(
    SignatureCreateRequest,
    SignatureUpdateRequest,
    SignatureResponse,
    SignatureListResponse,
    SignatureDeleteResponse,
)
from utils.security import get_current_employee

router = APIRouter(prefix="/signatures",tags=["Signatures"])

# Create Signature
@router.post("/",response_model=SignatureResponse,status_code=201)
def create_signature(
    payload: SignatureCreateRequest,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int(current_employee["sub"])

    signature = Signature(
        employee_id=employee_id,
        signature_name=payload.signature_name,
        signature_data=payload.signature_data,
    )
    db.add(signature)
    db.commit()
    db.refresh(signature)

    return signature

# GEt all Signatures

@router.get("/",response_model=SignatureListResponse,status_code=200)
def get_signatures(
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int (current_employee["sub"])
    signatures = (
        db.query(Signature)
        .filter(Signature.employee_id == employee_id)
        .order_by(Signature.created_at.desc(), Signature.id.desc())
        .all()
    )
    return {
            "total": len(signatures),
            "signatures": signatures,
    }

# Update Signature

@router.put("/{signature_id}", response_model=SignatureResponse)
def update_signature(
    signature_id: int,
    payload: SignatureUpdateRequest,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int(current_employee["sub"])

    signature = (
        db.query(Signature)
        .filter(
            Signature.id == signature_id,
            Signature.employee_id == employee_id,
        )
        .first()
    )

    if not signature:
        raise HTTPException(status_code=404, detail="Signature not found")

    if payload.signature_name is not None:
        signature.signature_name = payload.signature_name.strip()

    if payload.signature_data is not None:
        signature.signature_data = payload.signature_data

    db.commit()
    db.refresh(signature)

    return signature
# Delete Signature
@router.delete("/{signature_id}",response_model=SignatureDeleteResponse)
def delete_signature(
    signature_id: int,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int(current_employee["sub"])

    signature = (
        db.query(Signature)
        .filter(
            Signature.id == signature_id,
            Signature.employee_id == employee_id,
        )
        .first()
    )

    if not signature:
        raise HTTPException(status_code=404, detail="Signature not Found")
    
    db.delete(signature)
    db.commit()

    return {
        "message": "Signature deleted successfully",
        "signature_id": signature_id,
    }