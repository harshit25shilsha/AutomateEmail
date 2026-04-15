from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from database.db import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    linkedin = Column(Text, nullable=True)
    skypeId = Column(Text, nullable=True)
    gender = Column(Text, nullable=True)
    aadharCardNumber = Column(Text, nullable=True)
    panCardNumber = Column(Text, nullable=True)
    skills = Column(JSONB, nullable=True)
    experience = Column(JSONB, nullable=True)
    education = Column(JSONB, nullable=True)
    projects = Column(JSONB, nullable=True)
    certifications = Column(JSONB, nullable=True)
    raw_text = Column(Text, nullable=True)
    resume_url = Column(Text, nullable=True)