"""
LLM Router — Couche d'abstraction multi-fournisseurs.
Supporte: Gemini, DeepSeek, Claude (Anthropic), OpenAI/GPT, Azure OpenAI, Bedrock, Grok (xAI), Groq, Mistral, Qwen, Mock.
"""
from __future__ import annotations

import base64
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, AsyncGenerator, Any

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings


# ──────────────────────────────────────────────
# Encryption helpers
# ──────────────────────────────────────────────

def _get_fernet() -> Optional[Fernet]:
    key = settings.encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_api_key(plain_key: str) -> str:
    f = _get_fernet()
    if f is None:
        return plain_key  # No encryption if key not set
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    f = _get_fernet()
    if f is None:
        return encrypted_key
    try:
        return f.decrypt(encrypted_key.encode()).decode()
    except Exception:
        return encrypted_key


# ──────────────────────────────────────────────
# Provider constants
# ──────────────────────────────────────────────

PROVIDERS = {
    "gemini": {
        "name": "Google Gemini",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-pro",
        ],
        "default_model": "gemini-3.5-flash",
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-v4-flash",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"],
        "default_model": "claude-sonnet-4-5",
    },
    "openai": {
        "name": "OpenAI GPT",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
        "default_model": "gpt-4o",
    },
    "openrouter": {
        "name": "OpenRouter",
        "models": [
            "openai/gpt-oss-20b:free",
            "openai/gpt-oss-120b:free",
            "google/gemma-3-27b-it:free",
            "meta-llama/llama-3.1-8b-instruct:free",
        ],
        "default_model": "openai/gpt-oss-20b:free",
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "models": [
            "nvidia/nemotron-3-ultra-550b-a55b",
            "deepseek-ai/deepseek-v4-pro",
            "stepfun-ai/step-3.7-flash",
            "zai/glm-5.1",
        ],
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b",
    },
    "grok": {
        "name": "xAI Grok",
        "models": ["grok-3", "grok-3-mini", "grok-3-fast"],
        "default_model": "grok-3-mini",
    },
    "groq": {
        "name": "Groq Cloud",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ],
        "default_model": "llama-3.3-70b-versatile",
    },
    "mistral": {
        "name": "Mistral AI",
        "models": ["mistral-large-latest", "codestral-latest", "mistral-small-latest"],
        "default_model": "codestral-latest",
    },
    "qwen": {
        "name": "Qwen",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-coder-32b-instruct"],
        "default_model": "qwen-max",
    },
    "azure_openai": {
        "name": "Azure OpenAI",
        "models": ["gpt-5.5", "gpt-5.4-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-4o",
    },
    "bedrock": {
        "name": "AWS Bedrock",
        "models": [
            "anthropic.claude-sonnet-4-7",
            "anthropic.claude-opus-4-7",
            "amazon.nova-pro-v1:0",
            "deepseek-v4-pro",
            "openai.gpt-oss-120b",
        ],
        "default_model": "anthropic.claude-sonnet-4-7",
    },
    "mock": {
        "name": "Mock (Test)",
        "models": ["mock"],
        "default_model": "mock",
    },
}

# Default assignment: which provider serves each agent department
DEFAULT_ASSIGNMENTS = {
    "strategy": "gemini",
    "ux": "anthropic",
    "engineering": "mistral",
    "devops": "grok",
    "orchestrator": "gemini",
}

# Conservative defaults to avoid provider-side rate limits during multi-agent runs.
DEFAULT_REQUESTS_PER_MINUTE = {
    "gemini": 15,
    "deepseek": 10,
    "anthropic": 5,
    "openai": 10,
    "openrouter": 5,
    "nvidia": 5,
    "grok": 5,
    "groq": 2,
    "mistral": 10,
    "qwen": 5,
    "azure_openai": 10,
    "bedrock": 5,
}

_PROVIDER_RATE_LOCKS: dict[str, asyncio.Lock] = {}
_PROVIDER_LAST_CALL_AT: dict[str, float] = {}
QWEN_CONFIG_DIR = Path(os.environ.get("QWEN_CONFIG_DIR") or Path.home() / ".qwen")
QWEN_OAUTH_FILE = QWEN_CONFIG_DIR / "oauth_creds.json"
QWEN_SETTINGS_FILE = QWEN_CONFIG_DIR / "settings.json"


def get_default_requests_per_minute(provider: str) -> int:
    return DEFAULT_REQUESTS_PER_MINUTE.get(provider, 5)


def qwen_cli_is_authenticated() -> bool:
    return QWEN_OAUTH_FILE.exists() or QWEN_SETTINGS_FILE.exists()


def get_qwen_auth_method() -> str:
    if QWEN_OAUTH_FILE.exists():
        return "oauth"
    if QWEN_SETTINGS_FILE.exists():
        return "apikey"
    return "none"


# ──────────────────────────────────────────────
# Mock responses for testing without API keys
# ──────────────────────────────────────────────

MOCK_RESPONSES = {
    "strategy": """
## Analyse Stratégique (Mock)

### Viabilité du marché
Le marché des outils d'automatisation IA pour développeurs est en forte croissance.
TAM estimé: 12Mrd$ d'ici 2027. Segments cibles: PME tech, agences digitales, freelances senior.

### KPIs recommandés
- Time-to-CDC: < 5 minutes
- Satisfaction: NPS > 60
- Rétention M3: > 70%

### Positionnement
"L'agence IA qui pense avant de coder" — différenciateur: débat contradictoire entre agents.
""",
    "ux": """
## Conception UX (Mock)

### Parcours Utilisateur Principal
1. Landing → CTA "Démarrer un projet"
2. Studio → Input conversationnel (texte/PDF)
3. Dashboard → Suivi temps réel des 4 agents
4. Livrables → Export CDC/MCD/Code

### Points de friction identifiés
- L'attente pendant l'analyse IA (mitigation: streaming en temps réel)
- La complexité du MCD pour non-techniques (mitigation: visualisation simplifiée)

### Recommandations UX
- Interface conversationnelle, pas de formulaire
- Progress bar par département
- Annotations inline sur les livrables
""",
    "engineering": """
## Architecture Technique (Mock)

### MCD Proposé
Entités: User, Project, Deliverable, LLMConfig, AgentRun
Relations: User 1→N Projects, Project 1→N Deliverables, Project 1→N AgentRuns

### Stack validée
- Backend: FastAPI + LangGraph + PostgreSQL
- Frontend: Next.js + TypeScript
- Infra: Docker Compose + Traefik

### Modules prioritaires (MVP)
1. LLM Router (abstraction multi-provider)
2. Orchestrateur LangGraph (3 rounds)
3. API REST + WebSocket streaming
4. Admin panel (config LLM)
""",
    "devops": """
## DevOps & Sécurité (Mock)

### Infrastructure proposée
- docker-compose.yml: backend + frontend + postgres
- Traefik comme reverse proxy
- CrowdSec pour la protection IPS

### Checklist Sécurité MVP
✅ Clés API chiffrées en base (Fernet)
✅ JWT avec expiration 24h
✅ CORS strict
✅ Validation des inputs (Pydantic)
⚠️ Rate limiting à ajouter (Phase 2)
⚠️ Audit log à ajouter (Phase 2)

### Volumes & Backup
- PostgreSQL: volume persistant
- Backup automatique recommandé: pg_dump daily
""",
    "critique": "Les analyses sont cohérentes et complémentaires. Points de convergence validés.",
    "synthesis": """
## Synthèse Finale — Livrables AIA

### CDC Généré
Projet validé par les 4 départements. Architecture FastAPI + Next.js recommandée.

### MCD Final
User → Projects → Deliverables (1-N-N)
AgentRun → Project (N-1)
LLMConfig → Singleton admin

### Roadmap
- Phase 1 (M1-3): MVP LLM Router + 4 agents + Admin panel
- Phase 2 (M4-6): Code generation + PDF export
- Phase 3 (M7-12): Multi-stack + collaboration

### Architecture recommandée
Backend: FastAPI 0.115 / LangGraph 0.2 / PostgreSQL 16
Frontend: Next.js 14 / TypeScript / Vanilla CSS
""",
}


# ──────────────────────────────────────────────
# LLM Router
# ──────────────────────────────────────────────

class LLMRouter:
    """
    Abstraction layer for multiple LLM providers.
    Reads configuration from DB and routes requests accordingly.
    Falls back to mock mode if no API key is configured.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._config_cache: dict = {}
        self._config_lock = asyncio.Lock()

    async def _load_configs(self) -> dict:
        if self._config_cache:
            return self._config_cache

        async with self._config_lock:
            if self._config_cache:
                return self._config_cache

            from app.models.llm_config import LLMConfig
            result = await self.db.execute(select(LLMConfig))
            configs = result.scalars().all()
            self._config_cache = {c.provider: c for c in configs}
        return self._config_cache

    async def _get_requests_per_minute(self, provider: str) -> int:
        configs = await self._load_configs()
        cfg = configs.get(f"rate_{provider}_rpm")
        if cfg and cfg.value:
            try:
                rpm = int(cfg.value)
                return max(1, min(rpm, 600))
            except ValueError:
                pass
        return get_default_requests_per_minute(provider)

    async def _get_llm_timeout_seconds(self) -> int:
        configs = await self._load_configs()
        cfg = configs.get("workflow_llm_timeout_seconds")
        if cfg and cfg.value:
            try:
                timeout = int(cfg.value)
                return max(30, min(timeout, 900))
            except ValueError:
                pass
        return 180

    async def _run_with_rate_limit(self, provider: str, rpm: int, call):
        lock = _PROVIDER_RATE_LOCKS.setdefault(provider, asyncio.Lock())
        interval = 60 / max(1, rpm)
        async with lock:
            last_call_at = _PROVIDER_LAST_CALL_AT.get(provider, 0)
            elapsed = time.monotonic() - last_call_at
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            try:
                return await call()
            finally:
                _PROVIDER_LAST_CALL_AT[provider] = time.monotonic()

    def _estimate_tokens(self, *texts: str) -> int:
        # Approximation conservative: 1 token ~= 4 caractères.
        total_chars = sum(len(text or "") for text in texts)
        return max(1, total_chars // 4)

    def _extract_token_usage(self, response, prompt: str, system_prompt: str) -> int:
        usage = getattr(response, "usage_metadata", None) or {}
        response_metadata = getattr(response, "response_metadata", None) or {}
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}

        candidates = [
            usage.get("total_tokens") if isinstance(usage, dict) else None,
            usage.get("input_tokens", 0) + usage.get("output_tokens", 0) if isinstance(usage, dict) else None,
            token_usage.get("total_tokens") if isinstance(token_usage, dict) else None,
            token_usage.get("prompt_tokens", 0) + token_usage.get("completion_tokens", 0) if isinstance(token_usage, dict) else None,
        ]
        for value in candidates:
            try:
                parsed = int(value or 0)
            except (TypeError, ValueError):
                parsed = 0
            if parsed > 0:
                return parsed

        content = getattr(response, "content", "")
        return self._estimate_tokens(prompt, system_prompt, str(content))

    async def _record_token_usage(self, provider: str, tokens: int) -> None:
        if provider not in PROVIDERS or provider == "mock" or tokens <= 0:
            return

        from app.models.llm_config import LLMConfig

        result = await self.db.execute(select(LLMConfig).where(LLMConfig.provider == provider))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            cfg = LLMConfig(provider=provider)
            self.db.add(cfg)
        cfg.total_tokens_used = int(cfg.total_tokens_used or 0) + int(tokens)
        await self.db.commit()
        self._config_cache = {}

    async def get_provider_details(self, provider: str) -> tuple[str, str, Optional[str]]:
        """Return (provider, model, api_key) for a concrete provider key."""
        configs = await self._load_configs()
        config = configs.get(provider)

        api_key = None
        if config and config.api_key_encrypted:
            api_key = decrypt_api_key(config.api_key_encrypted)
        else:
            env_keys = {
                "gemini": settings.gemini_api_key,
                "deepseek": settings.deepseek_api_key,
                "anthropic": settings.anthropic_api_key,
                "openai": settings.openai_api_key,
                "openrouter": settings.openrouter_api_key,
                "nvidia": settings.nvidia_api_key,
                "grok": settings.grok_api_key,
                "groq": settings.groq_api_key,
                "mistral": settings.mistral_api_key,
                "qwen": settings.qwen_api_key,
                "azure_openai": settings.azure_openai_api_key,
                "bedrock": "",
            }
            api_key = env_keys.get(provider, "")

        model = PROVIDERS[provider]["default_model"] if provider in PROVIDERS else "mock"
        if config and config.active_model:
            model = config.active_model

        return provider, model, api_key if api_key else None

    async def get_provider_for_agent(self, agent_type: str) -> tuple[str, str, Optional[str]]:
        """Returns (provider, model, api_key) for an agent type."""
        configs = await self._load_configs()

        assignment_key = f"assign_{agent_type}"
        provider = DEFAULT_ASSIGNMENTS.get(agent_type, "gemini")
        if assignment_key in configs:
            provider = configs[assignment_key].value or provider

        return await self.get_provider_details(provider)

    async def generate(self, prompt: str, agent_type: str, system_prompt: str = "") -> str:
        """Generate a response from the configured LLM provider.

        No mock fallback is allowed in production workflow: configuration or
        provider errors must stop the analysis and be shown to the user.
        """
        provider, model, api_key = await self.get_provider_for_agent(agent_type)

        if provider == "mock":
            raise RuntimeError(
                f"Le département {agent_type} est assigné au provider Mock. "
                "Assignez un vrai fournisseur IA dans l'administration."
            )
        if provider == "bedrock":
            api_key = api_key or "__aws_bedrock__"
        if not api_key:
            if provider == "qwen" and qwen_cli_is_authenticated():
                api_key = "__qwen_cli_auth__"
            else:
                provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                raise RuntimeError(
                    f"Aucune clé API configurée pour {provider_name}. "
                    "Ajoutez une clé valide dans l'administration avant de lancer l'analyse."
                )

        rpm = await self._get_requests_per_minute(provider)
        timeout_seconds = await self._get_llm_timeout_seconds()

        try:
            return await asyncio.wait_for(
                self._run_with_rate_limit(
                    provider,
                    rpm,
                    lambda: self._call_provider(provider, model, api_key, prompt, system_prompt),
                ),
                timeout=timeout_seconds,
            )
        except Exception as e:
            provider_name = PROVIDERS.get(provider, {}).get("name", provider)
            raise RuntimeError(f"Erreur API {provider_name} ({model}) : {e}") from e

    async def generate_with_provider(
        self,
        provider: str,
        model: str,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """Generate a response using an explicit provider/model pair."""
        if provider not in PROVIDERS:
            raise RuntimeError(f"Provider inconnu ou non supporté: {provider}")
        if provider == "mock":
            raise RuntimeError("Le provider Mock ne peut pas être utilisé pour générer un message de commit.")

        _, default_model, api_key = await self.get_provider_details(provider)
        selected_model = (model or default_model).strip() or default_model

        if provider == "bedrock":
            api_key = api_key or "__aws_bedrock__"
        if not api_key:
            if provider == "qwen" and qwen_cli_is_authenticated():
                api_key = "__qwen_cli_auth__"
            else:
                provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                raise RuntimeError(
                    f"Aucune clé API configurée pour {provider_name}. "
                    "Ajoutez une clé valide dans l'administration avant de lancer l'analyse."
                )

        rpm = await self._get_requests_per_minute(provider)
        timeout_seconds = await self._get_llm_timeout_seconds()

        try:
            return await asyncio.wait_for(
                self._run_with_rate_limit(
                    provider,
                    rpm,
                    lambda: self._call_provider(provider, selected_model, api_key, prompt, system_prompt),
                ),
                timeout=timeout_seconds,
            )
        except Exception as e:
            provider_name = PROVIDERS.get(provider, {}).get("name", provider)
            raise RuntimeError(f"Erreur API {provider_name} ({selected_model}) : {e}") from e

    async def generate_with_fallback(
        self,
        prompt: str,
        agent_type: str,
        system_prompt: str = "",
        fallback_providers: list[str] | None = None,
    ) -> str:
        """Generate a response with provider fallbacks for user-facing questions.

        This keeps the strict behavior for workflow generation, but lets direct
        user questions still receive an answer when the assigned provider is
        temporarily unavailable or rejects a specific model.
        """
        primary_provider, primary_model, primary_api_key = await self.get_provider_for_agent(agent_type)
        provider_order = [primary_provider]

        for provider in fallback_providers or []:
            if provider not in provider_order:
                provider_order.append(provider)

        errors: list[str] = []
        for provider in provider_order:
            if provider == "mock" or provider not in PROVIDERS:
                continue

            try:
                _, model, api_key = await self.get_provider_details(provider)
                if provider == primary_provider:
                    model = primary_model
                    api_key = primary_api_key

                if provider == "bedrock":
                    api_key = api_key or "__aws_bedrock__"

                if not api_key:
                    if provider == "qwen" and qwen_cli_is_authenticated():
                        api_key = "__qwen_cli_auth__"
                    else:
                        provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                        raise RuntimeError(
                            f"Aucune clé API configurée pour {provider_name}. "
                            "Ajoutez une clé valide dans l'administration avant de lancer l'analyse."
                        )

                rpm = await self._get_requests_per_minute(provider)
                timeout_seconds = await self._get_llm_timeout_seconds()
                return await asyncio.wait_for(
                    self._run_with_rate_limit(
                        provider,
                        rpm,
                        lambda: self._call_provider(provider, model, api_key, prompt, system_prompt),
                    ),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                errors.append(f"{provider_name} ({provider}) : {exc}")

        details = " | ".join(errors[:4]) if errors else "aucun provider disponible"
        raise RuntimeError(f"Aucune réponse automatique n'a pu être générée. Détails: {details}")

    async def _call_qwen_cli(self, prompt: str, system_prompt: str, model: str) -> str:
        if not qwen_cli_is_authenticated():
            raise RuntimeError("Qwen CLI n'est pas authentifié. Lancez l'auth Web/CLI dans l'administration.")

        full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n---\n{prompt}"
        safe_prompt = full_prompt[:24000]
        process = await asyncio.create_subprocess_exec(
            "qwen",
            "-p",
            safe_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "FORCE_COLOR": "0"},
        )
        try:
            timeout_seconds = await self._get_llm_timeout_seconds()
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            process.kill()
            raise RuntimeError(f"Qwen CLI a dépassé le timeout de {timeout_seconds} secondes.") from exc

        if process.returncode != 0:
            error = (stderr or stdout).decode(errors="ignore").strip()
            raise RuntimeError(f"Qwen CLI error: {error[:500] or process.returncode}")

        result = stdout.decode(errors="ignore").strip()
        if not result:
            raise RuntimeError("Qwen CLI n'a retourné aucune réponse.")

        await self._record_token_usage("qwen", self._estimate_tokens(prompt, system_prompt, result))
        return result

    async def _call_provider(
        self, provider: str, model: str, api_key: str, prompt: str, system_prompt: str, record_usage: bool = True
    ) -> str:
        if provider == "qwen" and api_key == "__qwen_cli_auth__":
            return await self._call_qwen_cli(prompt, system_prompt, model)
        if provider == "bedrock":
            return await self._call_bedrock(prompt, system_prompt, model)

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.4, max_output_tokens=1800)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model=model, anthropic_api_key=api_key, temperature=0.4, max_tokens=1800)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=model, api_key=api_key, temperature=0.4, max_tokens=1800)
        elif provider == "openrouter":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "nvidia":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://integrate.api.nvidia.com/v1",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "grok":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "groq":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "mistral":
            from langchain_mistralai import ChatMistralAI
            llm = ChatMistralAI(model=model, api_key=api_key, temperature=0.4, max_tokens=1800)
        elif provider == "qwen":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "deepseek":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.deepseek.com",
                temperature=0.4,
                max_tokens=1800,
            )
        elif provider == "azure_openai":
            from langchain_openai import AzureChatOpenAI
            endpoint = (settings.azure_openai_endpoint or "").strip()
            api_version = (settings.azure_openai_api_version or "").strip()
            if not endpoint or not api_version:
                raise RuntimeError(
                    "Azure OpenAI nécessite les variables AZURE_OPENAI_ENDPOINT et AZURE_OPENAI_API_VERSION côté backend."
                )
            llm = AzureChatOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                azure_deployment=model,
                api_key=api_key,
                temperature=0.4,
                max_tokens=1800,
            )
        else:
            raise ValueError(f"Provider inconnu ou non supporté: {provider}")

        response = await llm.ainvoke(messages)
        if record_usage:
            tokens_used = self._extract_token_usage(response, prompt, system_prompt)
            await self._record_token_usage(provider, tokens_used)
        return response.content

    async def _call_bedrock(self, prompt: str, system_prompt: str, model: str) -> str:
        region = (settings.bedrock_region or "").strip()
        if not region:
            raise RuntimeError("AWS Bedrock nécessite la variable BEDROCK_REGION côté backend.")

        import boto3

        client = boto3.client("bedrock-runtime", region_name=region)
        request: dict[str, Any] = {
            "modelId": model,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            "inferenceConfig": {
                "temperature": 0.4,
                "maxTokens": 1800,
            },
        }
        if system_prompt.strip():
            request["system"] = [{"text": system_prompt}]

        try:
            response = client.converse(**request)
        except Exception as exc:
            raise RuntimeError(f"Erreur AWS Bedrock ({model}) : {exc}") from exc

        output = response.get("output") or {}
        message = output.get("message") or {}
        content = message.get("content") or []
        texts = [str(item.get("text")) for item in content if isinstance(item, dict) and item.get("text")]
        result = "\n".join(texts).strip()
        if not result:
            raise RuntimeError("AWS Bedrock n'a retourné aucune réponse exploitable.")

        usage = response.get("usage") or {}
        tokens_used = 0
        if isinstance(usage, dict):
            try:
                tokens_used = int(
                    usage.get("totalTokens")
                    or (usage.get("inputTokens", 0) + usage.get("outputTokens", 0))
                    or 0
                )
            except (TypeError, ValueError):
                tokens_used = 0
        if tokens_used <= 0:
            tokens_used = self._estimate_tokens(prompt, system_prompt, result)
        await self._record_token_usage("bedrock", tokens_used)
        return result

    def _mock_response(self, agent_type: str) -> str:
        """Return a mock response for testing without API keys."""
        return MOCK_RESPONSES.get(agent_type, f"[Mock] Réponse de l'agent {agent_type}.")

    async def test_connection(self, provider: str, api_key: str, model: str) -> dict:
        """Test if a provider connection works."""
        try:
            result = await self._call_provider(
                provider, model, api_key, "Réponds juste 'OK' en un mot.", "", record_usage=False
            )
            return {"success": True, "message": result}
        except Exception as e:
            return {"success": False, "message": str(e)}
