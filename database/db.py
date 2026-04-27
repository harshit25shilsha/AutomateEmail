from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    from models.hr_user import HRUser
    from models.email_model import Email
    from models.attachment_model import Attachment
    from models.attachment_activity import AttachmentActivity
    from models.employee import Employee
    from models.candidate import Candidate
    

    Base.metadata.create_all(bind=engine)
    ensure_email_received_at_column()
    ensure_email_owner_column()


def ensure_email_received_at_column():
    from models.email_model import Email
    from utils.date_utils import parse_email_datetime

    inspector = inspect(engine)
    if "emails" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("emails")}
    with engine.begin() as connection:
        if "received_at" not in column_names:
            connection.execute(
                text("ALTER TABLE emails ADD COLUMN received_at TIMESTAMP WITH TIME ZONE")
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_emails_received_at ON emails (received_at)")
            )

    db = SessionLocal()
    try:
        emails = (
            db.query(Email)
            .filter(Email.received_at.is_(None), Email.date.isnot(None))
            .all()
        )
        for email in emails:
            parsed = parse_email_datetime(email.date)
            if parsed is not None:
                email.received_at = parsed
        db.commit()
    finally:
        db.close()


def ensure_email_owner_column():
    inspector = inspect(engine)
    if "emails" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("emails")}
    with engine.begin() as connection:
        if "hr_user_id" not in column_names:
            connection.execute(
                text("ALTER TABLE emails ADD COLUMN hr_user_id INTEGER")
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_emails_hr_user_id ON emails (hr_user_id)")
            )
            connection.execute(
                text(
                    "ALTER TABLE emails "
                    "ADD CONSTRAINT fk_emails_hr_user_id "
                    "FOREIGN KEY (hr_user_id) REFERENCES hr_users(id)"
                )
            )

        unique_constraints = inspector.get_unique_constraints("emails")
        for constraint in unique_constraints:
            if constraint.get("column_names") == ["email_id"]:
                constraint_name = constraint.get("name")
                if constraint_name:
                    connection.execute(
                        text(f'ALTER TABLE emails DROP CONSTRAINT IF EXISTS "{constraint_name}"')
                    )

    refreshed_inspector = inspect(engine)
    has_composite_unique = any(
        constraint.get("column_names") == ["hr_user_id", "email_id"]
        for constraint in refreshed_inspector.get_unique_constraints("emails")
    )

    if not has_composite_unique:
        with engine.begin() as connection:
            connection.execute(
                text(
                    'ALTER TABLE emails ADD CONSTRAINT "uix_email_hr_user_email_id" '
                    "UNIQUE (hr_user_id, email_id)"
                )
            )
