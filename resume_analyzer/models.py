from sqlalchemy import Column, Integer, String, Float, Text
from sqlalchemy.dialects.postgresql import JSONB
from database.db import Base


class ResumeAnalysis(Base):
    __tablename__ = "resume_analysis"

    id = Column(Integer, primary_key=True, index=True)

    candidate_name  = Column(Text,        nullable=True)
    candidate_email = Column(Text,        nullable=True)

    domain  = Column(String(120), nullable=False)
    skills  = Column(JSONB,       nullable=True)   
    level   = Column(String(50),  nullable=True)   
    score   = Column(Float,       nullable=True)   
    summary = Column(Text,        nullable=True)   

    filename      = Column(Text, nullable=True)    
    folder_path   = Column(Text, nullable=True)    
    drive_link    = Column(Text, nullable=True)    
    drive_file_id = Column(Text, nullable=True)    

    source   = Column(String(50), nullable=True)  
    provider = Column(String(50), nullable=True)  

    created_at = Column(Text, nullable=True)       
    def __repr__(self):
        return (
            f"<ResumeAnalysis id={self.id} "
            f"name={self.candidate_name!r} "
            f"domain={self.domain!r} "
            f"score={self.score}>"
        )