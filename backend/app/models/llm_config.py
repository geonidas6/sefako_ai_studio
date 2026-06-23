import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class LLMConfig(Base):
    """
    Stores per-provider LLM configuration set by the admin.
    One row per provider (gemini, anthropic, openai, openrouter, nvidia, grok, groq, mistral, qwen).
    Also stores agent-to-provider assignments as rows with provider='assign_<agent>'.
    """
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # provider key: gemini | anthropic | openai | openrouter | nvidia | grok | groq | mistral | qwen | assign_strategy | assign_ux | ...
    provider: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For assignment rows: stores the provider name (e.g. "gemini")
    value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_tokens_used: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
