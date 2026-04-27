# models/hr_user.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database.db import Base

class HRUser(Base):
    __tablename__ = "hr_users"
    __table_args__ = (
        UniqueConstraint("employee_id", "provider", "email", name="uix_hr_user_employee_provider_email"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    employee_id   = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    name          = Column(String, nullable=False)
    email         = Column(String, nullable=False, index=True)
    provider      = Column(String, nullable=False)   # "gmail" or "outlook"
    access_token  = Column(Text, nullable=True)      # encrypted OAuth token
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    last_login    = Column(DateTime(timezone=True), onupdate=func.now())

    employee = relationship("Employee", backref="connected_accounts")
