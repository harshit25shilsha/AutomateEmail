from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.db import get_db
from models.email_template import EmailTemplate
from schemas.template_schema import (
    TemplateCreateRequest,
    TemplateUpdateRequest,
    TemplateResponse,
    TemplateListResponse,
    TemplateDeleteResponse,
)

from utils.security import get_current_employee

router = APIRouter(prefix="/templates", tags=["Templates"])

# Create Email Template
@router.post("", response_model=TemplateResponse,status_code=201)
def create_template(
    payload: TemplateCreateRequest,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int (current_employee["sub"])
    template = EmailTemplate(
        employee_id = employee_id,
        template_name = payload.template_name,
        template_data = payload.template_data,
        subject = payload.subject,
    )
    
    db.add(template)
    db.commit()
    db.refresh(template)

    return template


# get all templates for the current employee

@router.get("",response_model=TemplateListResponse)
def get_all_templates(
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int (current_employee["sub"])

    templates = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.employee_id == employee_id)
        .order_by(EmailTemplate.created_at.desc(), EmailTemplate.id.desc())
        .all()
    )
    return {
        "total": len(templates),
        "templates": templates
    }

# Update Templates

@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    payload: TemplateUpdateRequest,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int(current_employee["sub"])

    template = (
        db.query(EmailTemplate)
        .filter(
            EmailTemplate.id == template_id,
            EmailTemplate.employee_id == employee_id,
        )
        .first()
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if payload.template_name is not None:
        template.template_name = payload.template_name.strip()

    if payload.template_data is not None:
        template.template_data = payload.template_data

    if payload.subject is not None:
        template.subject = payload.subject

    db.commit()
    db.refresh(template)

    return template


# Delete Templates

@router.delete("/{template_id}", response_model=TemplateDeleteResponse)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_employee: dict = Depends(get_current_employee),
):
    employee_id = int(current_employee["sub"])

    template = (
        db.query(EmailTemplate)
        .filter(
            EmailTemplate.id == template_id,
            EmailTemplate.employee_id == employee_id,
        )
        .first()
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.delete(template)
    db.commit()

    return {
        "message": "Template deleted successfully",
        "template_id": template_id,
    }
