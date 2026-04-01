# models/hr_user.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from database.db import Base

class HRUser(Base):
    __tablename__ = "hr_users"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    email         = Column(String, unique=True, nullable=False, index=True)
    provider      = Column(String, nullable=False)   # "gmail" or "outlook"
    access_token  = Column(Text, nullable=True)      # encrypted OAuth token
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    last_login    = Column(DateTime(timezone=True), onupdate=func.now())