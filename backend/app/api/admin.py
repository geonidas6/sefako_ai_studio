from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.database import get_db
from app.models.llm_config import LLMConfig
from app.core.security import get_current_admin
from app.core.llm_router import (
    LLMRouter,
    PROVIDERS,
    encrypt_api_key,
    decrypt_api_key,
    DEFAULT_ASSIGNMENTS,
)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class ProviderConfigIn(BaseModel):
    is_enabled: bool = False
    active_model: Optional[str] = None
    api_key: Optional[str] = None  # plain text, will be encrypted


class ProviderConfigOut(BaseModel):
    provider: str
    name: str
    is_enabled: bool
    active_model: Optional[str]
    has_api_key: bool
    models: list[str]
    tokens_used: int


class AssignmentIn(BaseModel):
    agent: str
    provider: str


class TestConnectionIn(BaseModel):
    provider: str
    api_key: str
    model: str


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("/llm-config", response_model=list[ProviderConfigOut])
async def get_llm_configs(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """List all provider configurations."""
    result = await db.execute(select(LLMConfig))
    configs = {c.provider: c for c in result.scalars().all()}

    providers_out = []
    for key, info in PROVIDERS.items():
        if key == "mock":
            continue
        cfg = configs.get(key)
        providers_out.append(
            ProviderConfigOut(
                provider=key,
                name=info["name"],
                is_enabled=cfg.is_enabled if cfg else False,
                active_model=cfg.active_model if cfg else info["default_model"],
                has_api_key=bool(cfg and cfg.api_key_encrypted),
                models=info["models"],
                tokens_used=cfg.total_tokens_used if cfg else 0,
            )
        )
    return providers_out


@router.put("/llm-config/{provider}")
async def update_llm_config(
    provider: str,
    body: ProviderConfigIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Create or update a provider configuration."""
    if provider not in PROVIDERS or provider == "mock":
        raise HTTPException(status_code=400, detail=f"Provider inconnu: {provider}")

    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == provider))
    cfg = result.scalar_one_or_none()

    if cfg is None:
        cfg = LLMConfig(provider=provider)
        db.add(cfg)

    cfg.is_enabled = body.is_enabled
    if body.active_model:
        cfg.active_model = body.active_model
    if body.api_key:
        cfg.api_key_encrypted = encrypt_api_key(body.api_key)
    cfg.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return {"success": True, "provider": provider}


@router.get("/llm-config/assignments")
async def get_assignments(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Get current agent-to-provider assignments."""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.provider.like("assign_%"))
    )
    db_assignments = {c.provider.replace("assign_", ""): c.value for c in result.scalars().all()}

    # Merge with defaults
    merged = {**DEFAULT_ASSIGNMENTS, **db_assignments}
    return merged


@router.put("/llm-config/assignments")
async def update_assignment(
    body: AssignmentIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Assign a specific LLM provider to an agent department."""
    valid_agents = ["strategy", "ux", "engineering", "devops", "orchestrator"]
    if body.agent not in valid_agents:
        raise HTTPException(status_code=400, detail=f"Agent inconnu: {body.agent}")
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider inconnu: {body.provider}")

    key = f"assign_{body.agent}"
    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == key))
    cfg = result.scalar_one_or_none()

    if cfg is None:
        cfg = LLMConfig(provider=key)
        db.add(cfg)

    cfg.value = body.provider
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"success": True, "agent": body.agent, "provider": body.provider}


@router.post("/llm-config/test")
async def test_connection(
    body: TestConnectionIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Test if a provider API key is valid."""
    router_instance = LLMRouter(db)
    result = await router_instance.test_connection(body.provider, body.api_key, body.model)
    return result


@router.get("/llm-config/costs")
async def get_cost_summary(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Get token usage per provider."""
    result = await db.execute(select(LLMConfig).where(~LLMConfig.provider.like("assign_%")))
    configs = result.scalars().all()
    return [
        {
            "provider": c.provider,
            "name": PROVIDERS.get(c.provider, {}).get("name", c.provider),
            "tokens_used": c.total_tokens_used,
        }
        for c in configs
    ]
