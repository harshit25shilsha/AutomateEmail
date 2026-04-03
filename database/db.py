from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
load_dotenv()

DATABASE_URL  = os.getenv("DATABASE_URL")
engine        = create_engine(DATABASE_URL)
SessionLocal  = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base          = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    from models.hr_user import HRUser
    from models.email_model      import Email
    from models.attachment_model import Attachment
    from models.employee import Employee
    Base.metadata.create_all(bind=engine)