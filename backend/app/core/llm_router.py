"""
LLM Router — Couche d'abstraction multi-fournisseurs.
Supporte: Gemini, Claude (Anthropic), OpenAI/GPT, Grok (xAI), Mistral, Mock.
"""
from __future__ import annotations

import base64
import json
from typing import Optional, AsyncGenerator

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
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"],
        "default_model": "gemini-2.5-flash",
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
    "grok": {
        "name": "xAI Grok",
        "models": ["grok-3", "grok-3-mini", "grok-3-fast"],
        "default_model": "grok-3-mini",
    },
    "mistral": {
        "name": "Mistral AI",
        "models": ["mistral-large-latest", "codestral-latest", "mistral-small-latest"],
        "default_model": "codestral-latest",
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

    async def _load_configs(self) -> dict:
        if self._config_cache:
            return self._config_cache

        from app.models.llm_config import LLMConfig
        result = await self.db.execute(select(LLMConfig))
        configs = result.scalars().all()
        self._config_cache = {c.provider: c for c in configs}
        return self._config_cache

    async def get_provider_for_agent(self, agent_type: str) -> tuple[str, str, Optional[str]]:
        """Returns (provider, model, api_key) for an agent type."""
        configs = await self._load_configs()

        # Check if there's a specific assignment for this agent
        assignment_key = f"assign_{agent_type}"
        provider = DEFAULT_ASSIGNMENTS.get(agent_type, "gemini")

        if assignment_key in configs:
            provider = configs[assignment_key].value or provider

        config = configs.get(provider)

        # Get API key
        api_key = None
        if config and config.api_key_encrypted:
            api_key = decrypt_api_key(config.api_key_encrypted)
        else:
            # Fallback to env var
            env_keys = {
                "gemini": settings.gemini_api_key,
                "anthropic": settings.anthropic_api_key,
                "openai": settings.openai_api_key,
                "grok": settings.grok_api_key,
                "mistral": settings.mistral_api_key,
            }
            api_key = env_keys.get(provider, "")

        model = PROVIDERS[provider]["default_model"] if provider in PROVIDERS else "mock"
        if config and config.active_model:
            model = config.active_model

        return provider, model, api_key if api_key else None

    async def generate(self, prompt: str, agent_type: str, system_prompt: str = "") -> str:
        """Generate a response from the appropriate LLM for the given agent."""
        provider, model, api_key = await self.get_provider_for_agent(agent_type)

        if not api_key or provider == "mock":
            return self._mock_response(agent_type)

        try:
            return await self._call_provider(provider, model, api_key, prompt, system_prompt)
        except Exception as e:
            print(f"⚠️ LLM {provider} error: {e}. Using failover mock.")
            return self._mock_response(agent_type)

    async def _call_provider(
        self, provider: str, model: str, api_key: str, prompt: str, system_prompt: str
    ) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.7)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model=model, anthropic_api_key=api_key, temperature=0.7)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=model, api_key=api_key, temperature=0.7)
        elif provider == "grok":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                temperature=0.7,
            )
        elif provider == "mistral":
            from langchain_mistralai import ChatMistralAI
            llm = ChatMistralAI(model=model, api_key=api_key, temperature=0.7)
        else:
            return self._mock_response(provider)

        response = await llm.ainvoke(messages)
        return response.content

    def _mock_response(self, agent_type: str) -> str:
        """Return a mock response for testing without API keys."""
        return MOCK_RESPONSES.get(agent_type, f"[Mock] Réponse de l'agent {agent_type}.")

    async def test_connection(self, provider: str, api_key: str, model: str) -> dict:
        """Test if a provider connection works."""
        try:
            result = await self._call_provider(
                provider, model, api_key, "Réponds juste 'OK' en un mot.", ""
            )
            return {"success": True, "response": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
