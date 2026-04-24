from sqlalchemy import Column, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from database.db import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(Text, nullable=True)
    email           = Column(Text, nullable=True)
    phone           = Column(Text, nullable=True)
    linkedin        = Column(Text, nullable=True)
    github          = Column(Text, nullable=True)  

    skills          = Column(JSONB, nullable=True)
    experience      = Column(JSONB, nullable=True)
    education       = Column(JSONB, nullable=True)
    projects        = Column(JSONB, nullable=True)
    certifications  = Column(JSONB, nullable=True)

    source          = Column(Text, nullable=True)   
    email_id        = Column(Text, nullable=True)  
    email_date      = Column(Text, nullable=True)  
    email_subject   = Column(Text, nullable=True)  
    sender_email    = Column(Text, nullable=True)  
    provider        = Column(Text, nullable=True)  
    attachment_name = Column(Text, nullable=True)   

    raw_text        = Column(Text, nullable=True)
    resume_url      = Column(Text, nullable=True)
    created_at      = Column(Text, nullable=True)