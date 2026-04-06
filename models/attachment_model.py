# models/attachment_model.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from database.db import Base

class Attachment(Base):
    __tablename__ = "attachments"

    id          = Column(Integer, primary_key=True, index=True)
    email_id    = Column(Integer, ForeignKey("emails.id"), nullable=False)
    filename    = Column(String, nullable=False)
    file_path   = Column(String, nullable=False)
    file_size   = Column(Integer, nullable=True)
    file_type   = Column(String,  nullable=True)   # pdf, docx, xlsx
    created_at = Column(DateTime(timezone=True), server_default=func.now())