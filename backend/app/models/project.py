import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Status: pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), default="pending")

    # Agent outputs per round
    strategy_r1: Mapped[str | None] = mapped_column(Text, nullable=True)
    ux_r1: Mapped[str | None] = mapped_column(Text, nullable=True)
    engineering_r1: Mapped[str | None] = mapped_column(Text, nullable=True)
    devops_r1: Mapped[str | None] = mapped_column(Text, nullable=True)

    critiques: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_deliverables: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
