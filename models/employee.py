# models/employee.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database.db import Base
from datetime import datetime


class Employee(Base):
    __tablename__ = "employees"

    id        = Column(Integer, primary_key=True, index=True)
    name      = Column(String, nullable=False)
    email     = Column(String, unique=True, index=True, nullable=False)
    password  = Column(String, nullable=False)
    mobile    = Column(String, unique=True, index=True, nullable=False)
    gender    = Column(String, nullable=True)
    user_type = Column(String, default="employee")
    is_active = Column(Boolean, default=True)


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id             = Column(Integer, primary_key=True, index=True)
    token          = Column(String, unique=True, index=True, nullable=False)
    blacklisted_at = Column(DateTime, default=datetime.utcnow)