from __future__ import annotations

from typing import List

from sqlalchemy import JSON, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.db import Base

class ResumeAnalysis(Base):
    __tablename__ = "resume_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_name: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    domain: Mapped[str] = mapped_column(String(100), nullable=False)
    skills: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_path: Mapped[str] = mapped_column(String(255), nullable=False)

    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_link: Mapped[str | None] = mapped_column(String(512), nullable=True)

    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)