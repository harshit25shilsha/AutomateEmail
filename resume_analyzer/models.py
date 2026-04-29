from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import JSON, DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    domain: Mapped[str] = mapped_column(String(100), nullable=False)
    skills: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    folder: Mapped[str] = mapped_column(String(255), nullable=False)

    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )