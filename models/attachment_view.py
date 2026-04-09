from sqlalchemy import Column, Integer,DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from database.db import Base
class AttachmentView(Base):
    __tablename__ ="attachment_views"
    id  = Column(Integer, primary_key= True, index=True)
    attachment_id = Column(Integer, ForeignKey("attachments.id"), nullable=False, index=True)
    hr_user_id = Column(Integer, ForeignKey("hr_users.id"), nullable=False, index=True)
    viewed_at = Column(DateTime(timezone = True), default=func.now())

    __table_args__ = (UniqueConstraint("attachment_id", "hr_user_id", name="uix_attachment_hr_user"),)