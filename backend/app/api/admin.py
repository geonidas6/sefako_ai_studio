import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from app.db.database import get_db
from app.models.llm_config import LLMConfig
from app.models.department import Department, Employee
from app.core.security import get_current_admin
from app.core.agency import get_agency_departments, seed_default_agency
from app.core.llm_router import (
    LLMRouter,
    PROVIDERS,
    encrypt_api_key,
    decrypt_api_key,
    DEFAULT_ASSIGNMENTS,
    get_default_requests_per_minute,
    get_qwen_auth_method,
    qwen_cli_is_authenticated,
)

router = APIRouter()


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class ProviderConfigIn(BaseModel):
    is_enabled: bool = False
    active_model: Optional[str] = None
    api_key: Optional[str] = None  # plain text, will be encrypted
    requests_per_minute: Optional[int] = None


class ProviderConfigOut(BaseModel):
    provider: str
    name: str
    is_enabled: bool
    active_model: Optional[str]
    has_api_key: bool
    models: list[str]
    tokens_used: int
    requests_per_minute: int


class AssignmentIn(BaseModel):
    agent: str
    provider: str


class TestConnectionIn(BaseModel):
    provider: str
    api_key: str
    model: str


class ProviderModelIn(BaseModel):
    model: str


class QwenAuthKeyIn(BaseModel):
    api_key: str


class EmployeeIn(BaseModel):
    id: Optional[str] = None
    name: str
    role: str
    avatar: str
    briefing: Optional[str] = None
    sort_order: int = 0
    is_enabled: bool = True


class DepartmentIn(BaseModel):
    id: Optional[str] = None
    key: str
    label: str
    description: Optional[str] = None
    mission: Optional[str] = None
    sort_order: int = 0
    is_enabled: bool = True
    employees: list[EmployeeIn] = Field(default_factory=list)


class AgencyDepartmentsIn(BaseModel):
    departments: list[DepartmentIn]


class WorkflowSettingsIn(BaseModel):
    debate_rounds: int = 1


class WorkflowSettingsOut(BaseModel):
    debate_rounds: int
    max_debate_rounds: int = 3


WORKFLOW_DEBATE_ROUNDS_KEY = "workflow_debate_rounds"
QWEN_CONFIG_DIR = Path(os.environ.get("QWEN_CONFIG_DIR") or Path.home() / ".qwen")
QWEN_SETTINGS_FILE = QWEN_CONFIG_DIR / "settings.json"


def clamp_debate_rounds(value: int | str | None) -> int:
    try:
        parsed = int(value or 1)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 3))


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("/workflow-settings", response_model=WorkflowSettingsOut)
async def get_workflow_settings(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == WORKFLOW_DEBATE_ROUNDS_KEY))
    cfg = result.scalar_one_or_none()
    return WorkflowSettingsOut(debate_rounds=clamp_debate_rounds(cfg.value if cfg else None))


@router.put("/workflow-settings", response_model=WorkflowSettingsOut)
async def update_workflow_settings(
    body: WorkflowSettingsIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    debate_rounds = clamp_debate_rounds(body.debate_rounds)
    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == WORKFLOW_DEBATE_ROUNDS_KEY))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = LLMConfig(provider=WORKFLOW_DEBATE_ROUNDS_KEY)
        db.add(cfg)
    cfg.value = str(debate_rounds)
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return WorkflowSettingsOut(debate_rounds=debate_rounds)



@router.get("/departments")
async def get_departments(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """List departments and employees managed by the admin."""
    return await get_agency_departments(db, include_disabled=True)


@router.put("/departments")
async def update_departments(
    body: AgencyDepartmentsIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Replace the admin-managed department/employee structure."""
    if not body.departments:
        raise HTTPException(status_code=400, detail="Au moins un département est requis")

    allowed_keys = {"strategy", "ux", "engineering", "devops", "orchestrator"}
    seen_keys: set[str] = set()

    await seed_default_agency(db)
    result = await db.execute(select(Department).options(selectinload(Department.employees)))
    existing = {department.key: department for department in result.scalars().all()}

    for index, item in enumerate(body.departments):
        key = item.key.strip().lower()
        if key not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Département inconnu: {item.key}")
        if key in seen_keys:
            raise HTTPException(status_code=400, detail=f"Département dupliqué: {item.key}")
        seen_keys.add(key)

        label = item.label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Le libellé du département est requis")

        enabled_employees = [employee for employee in item.employees if employee.is_enabled]
        if item.is_enabled and not enabled_employees:
            raise HTTPException(status_code=400, detail=f"Le département {label} doit avoir au moins un employé actif")

        department = existing.get(key)
        if department is None:
            department = Department(key=key)
            db.add(department)

        department.label = label[:120]
        department.description = (item.description or "").strip()[:2000]
        department.mission = (item.mission or "").strip()[:4000]
        department.sort_order = item.sort_order if item.sort_order else (index + 1) * 10
        department.is_enabled = item.is_enabled
        department.updated_at = datetime.now(timezone.utc)

        department.employees.clear()
        for employee_index, employee_item in enumerate(item.employees):
            name = employee_item.name.strip()
            role = employee_item.role.strip()
            avatar = employee_item.avatar.strip().upper()[:4]
            if not name or not role:
                raise HTTPException(status_code=400, detail=f"Employé incomplet dans {label}")
            department.employees.append(Employee(
                name=name[:120],
                role=role[:160],
                avatar=avatar or name[:2].upper(),
                briefing=(employee_item.briefing or "").strip()[:4000],
                sort_order=employee_item.sort_order if employee_item.sort_order else (employee_index + 1) * 10,
                is_enabled=employee_item.is_enabled,
            ))

    await db.commit()
    return {"success": True, "departments": await get_agency_departments(db, include_disabled=True)}


@router.get("/qwen-auth/status")
async def get_qwen_auth_status(
    _: object = Depends(get_current_admin),
):
    return {
        "authenticated": qwen_cli_is_authenticated(),
        "method": get_qwen_auth_method(),
        "config_dir": str(QWEN_CONFIG_DIR),
    }


@router.post("/qwen-auth/start")
async def start_qwen_auth(
    _: object = Depends(get_current_admin),
):
    async def run_qwen_auth_command(*args: str) -> tuple[str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                "qwen",
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "FORCE_COLOR": "0"},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail="CLI Qwen non installé dans le backend. Reconstruisez l'image backend.") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=18)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return "", "Timeout pendant le démarrage de l'authentification Qwen."

        return stdout.decode(errors="ignore"), stderr.decode(errors="ignore")

    stdout, stderr = await run_qwen_auth_command("auth", "qwen-oauth")
    collected = f"{stdout}\n{stderr}"

    if "qwen auth has been removed" in collected.lower():
        stdout2, stderr2 = await run_qwen_auth_command("--auth-type", "qwen-oauth")
        collected = f"{collected}\n{stdout2}\n{stderr2}"

    lower = collected.lower()
    if "discontinued" in lower or "oauth free tier" in lower:
        raise HTTPException(
            status_code=410,
            detail=(
                "Qwen OAuth n'est plus disponible avec la version actuelle du CLI "
                "(free tier arrêté le 2026-04-15). Utilisez une clé API DashScope dans le champ Clé API, "
                "puis cliquez sur 'Utiliser cette clé aussi pour le CLI Qwen'."
            ),
        )

    if "qwen auth has been removed" in lower:
        raise HTTPException(
            status_code=410,
            detail=(
                "La commande 'qwen auth qwen-oauth' a été supprimée du CLI Qwen actuel. "
                "Utilisez une clé API DashScope ou configurez le CLI manuellement avec une session interactive."
            ),
        )

    urls = re.findall(r"(https?://[^\s]+)", collected)
    auth_urls = [
        url.rstrip(".,;')\"")
        for url in urls
        if "dashscope.aliyuncs.com/v1" not in url and "coding.dashscope.aliyuncs.com/v1" not in url
    ]
    if auth_urls:
        return {"url": auth_urls[0]}

    snippet = " ".join(collected.split())[:500]
    raise HTTPException(
        status_code=408,
        detail=f"Impossible d'obtenir une URL d'authentification Qwen. Sortie CLI: {snippet or 'aucune sortie'}",
    )


@router.post("/qwen-auth/key")
async def save_qwen_cli_api_key(
    body: QwenAuthKeyIn,
    _: object = Depends(get_current_admin),
):
    api_key = body.api_key.strip()
    if len(api_key) < 10:
        raise HTTPException(status_code=400, detail="Format de clé Qwen/DashScope invalide")

    QWEN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    settings_payload = {
        "modelProviders": {
            "openai": [{
                "id": "qwen-max",
                "name": "Qwen Max via DashScope",
                "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "envKey": "DASHSCOPE_API_KEY",
            }]
        },
        "env": {"DASHSCOPE_API_KEY": api_key},
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": "qwen-max"},
    }
    QWEN_SETTINGS_FILE.write_text(json.dumps(settings_payload, indent=2))
    return {"success": True, "method": "apikey"}


@router.get("/llm-config", response_model=list[ProviderConfigOut])
async def get_llm_configs(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """List all provider configurations."""
    result = await db.execute(select(LLMConfig))
    all_configs = result.scalars().all()
    configs = {c.provider: c for c in all_configs}
    custom_models: dict[str, list[str]] = {}
    for cfg in all_configs:
        if not cfg.provider.startswith("model_") or not cfg.value:
            continue
        parts = cfg.provider.split("_", 2)
        if len(parts) < 3:
            continue
        provider_key = parts[1]
        custom_models.setdefault(provider_key, [])
        if cfg.value not in custom_models[provider_key]:
            custom_models[provider_key].append(cfg.value)

    providers_out = []
    for key, info in PROVIDERS.items():
        if key == "mock":
            continue
        cfg = configs.get(key)
        rate_cfg = configs.get(f"rate_{key}_rpm")
        requests_per_minute = get_default_requests_per_minute(key)
        if rate_cfg and rate_cfg.value:
            try:
                requests_per_minute = max(1, min(int(rate_cfg.value), 600))
            except ValueError:
                requests_per_minute = get_default_requests_per_minute(key)
        providers_out.append(
            ProviderConfigOut(
                provider=key,
                name=info["name"],
                is_enabled=cfg.is_enabled if cfg else False,
                active_model=cfg.active_model if cfg else info["default_model"],
                has_api_key=bool(cfg and cfg.api_key_encrypted),
                models=[*info["models"], *custom_models.get(key, [])],
                tokens_used=cfg.total_tokens_used if cfg else 0,
                requests_per_minute=requests_per_minute,
            )
        )
    return providers_out


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

    if body.requests_per_minute is not None:
        rpm = max(1, min(body.requests_per_minute, 600))
        rate_key = f"rate_{provider}_rpm"
        result = await db.execute(select(LLMConfig).where(LLMConfig.provider == rate_key))
        rate_cfg = result.scalar_one_or_none()
        if rate_cfg is None:
            rate_cfg = LLMConfig(provider=rate_key)
            db.add(rate_cfg)
        rate_cfg.value = str(rpm)
        rate_cfg.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return {"success": True, "provider": provider}


@router.post("/llm-config/{provider}/models")
async def add_provider_model(
    provider: str,
    body: ProviderModelIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    """Add a custom model to a provider selector."""
    if provider not in PROVIDERS or provider == "mock":
        raise HTTPException(status_code=400, detail=f"Provider inconnu: {provider}")

    model = body.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Le nom du modèle est requis")
    if len(model) > 64:
        raise HTTPException(status_code=400, detail="Le nom du modèle doit faire 64 caractères maximum")

    default_models = set(PROVIDERS[provider]["models"])
    if model in default_models:
        return {"success": True, "provider": provider, "model": model, "already_exists": True}

    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.provider.like(f"model_{provider}_%"),
            LLMConfig.value == model,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {"success": True, "provider": provider, "model": model, "already_exists": True}

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model).strip("-").lower() or "custom"
    slug = slug[:40]
    base_key = f"model_{provider}_{slug}"
    key = base_key[:64]
    suffix = 2
    while True:
        result = await db.execute(select(LLMConfig).where(LLMConfig.provider == key))
        if result.scalar_one_or_none() is None:
            break
        suffix_text = f"_{suffix}"
        key = f"{base_key[:64 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    cfg = LLMConfig(provider=key, value=model)
    db.add(cfg)
    await db.commit()
    return {"success": True, "provider": provider, "model": model}


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
    result = await db.execute(select(LLMConfig).where(LLMConfig.provider.in_(list(PROVIDERS.keys()))))
    configs = {config.provider: config for config in result.scalars().all()}
    return [
        {
            "provider": provider,
            "name": info["name"],
            "tokens_used": int((configs.get(provider).total_tokens_used if configs.get(provider) else 0) or 0),
        }
        for provider, info in PROVIDERS.items()
        if provider != "mock"
    ]
