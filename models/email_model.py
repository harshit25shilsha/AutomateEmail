from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from database.db import Base

class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("hr_user_id", "email_id", name="uix_email_hr_user_email_id"),
    )

    id               = Column(Integer, primary_key=True, index=True)
    hr_user_id       = Column(Integer, ForeignKey("hr_users.id"), nullable=True, index=True)
    email_id         = Column(String, nullable=False, index=True)
    provider         = Column(String, nullable=False)
    candidate_name   = Column(String, nullable=True)
    candidate_email  = Column(String, nullable=True, index=True)
    subject          = Column(String, nullable=True)
    body             = Column(Text, nullable=True)
    date             = Column(String, nullable=True)
    received_at      = Column(DateTime(timezone=True), nullable=True, index=True)
    has_attachments  = Column(Boolean, default=False)
    is_read          = Column(Boolean, default=False)
    is_job_application = Column(Boolean, default=False, nullable=True)
    job_position       = Column(String, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
