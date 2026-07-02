from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_config import LLMConfig
from app.models.workflow_event import WorkflowEvent
from app.core.llm_router import LLMRouter

WORKSPACE_ROOT_PATH_KEY = "workspace_root_path"
WORKSPACE_REQUIRE_APPROVAL_KEY = "workspace_require_technical_approval"
DEFAULT_WORKSPACE_ROOT = "/projects"
IMPLEMENTATION_PIPELINE_KEY = "implementation_pipeline"
IMPLEMENTATION_WORKSPACE_KEY = "implementation_workspace"
CODE_SERVER_UID = int(os.getenv("CODE_SERVER_UID", "1000"))
CODE_SERVER_GID = int(os.getenv("CODE_SERVER_GID", "1000"))

PIPELINE_PHASES = [
    ("admin_approval", "Validation admin"),
    ("technical_design", "Conception technique"),
    ("documentation_pack", "Pack documentaire"),
    ("editor_bootstrap", "Préparation de l'éditeur"),
    ("requirements_coverage", "Couverture du CDC"),
    ("automated_validation", "Tests et validations"),
    ("delivery_review", "Revue de livraison"),
]


@dataclass
class WorkspaceSettings:
    root_path: str = DEFAULT_WORKSPACE_ROOT
    require_technical_approval: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_workspace_root(root_path: str | None) -> str:
    candidate = (root_path or DEFAULT_WORKSPACE_ROOT).strip() or DEFAULT_WORKSPACE_ROOT
    path = Path(candidate)
    if not path.is_absolute():
        path = Path(DEFAULT_WORKSPACE_ROOT)
    try:
        resolved = path.resolve()
    except Exception:
        resolved = Path(DEFAULT_WORKSPACE_ROOT).resolve()

    allowed_root = Path(DEFAULT_WORKSPACE_ROOT).resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        return str(allowed_root)
    return str(resolved)


def parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


async def get_workspace_settings(db: AsyncSession) -> WorkspaceSettings:
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.provider.in_([WORKSPACE_ROOT_PATH_KEY, WORKSPACE_REQUIRE_APPROVAL_KEY])
        )
    )
    configs = {cfg.provider: cfg for cfg in result.scalars().all()}
    return WorkspaceSettings(
        root_path=sanitize_workspace_root(configs.get(WORKSPACE_ROOT_PATH_KEY).value if configs.get(WORKSPACE_ROOT_PATH_KEY) else None),
        require_technical_approval=parse_bool(configs.get(WORKSPACE_REQUIRE_APPROVAL_KEY).value if configs.get(WORKSPACE_REQUIRE_APPROVAL_KEY) else None, True),
    )


async def save_workspace_settings(
    db: AsyncSession,
    root_path: str,
    require_technical_approval: bool,
) -> WorkspaceSettings:
    normalized_root = sanitize_workspace_root(root_path)
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.provider.in_([WORKSPACE_ROOT_PATH_KEY, WORKSPACE_REQUIRE_APPROVAL_KEY])
        )
    )
    configs = {cfg.provider: cfg for cfg in result.scalars().all()}

    root_cfg = configs.get(WORKSPACE_ROOT_PATH_KEY)
    if root_cfg is None:
        root_cfg = LLMConfig(provider=WORKSPACE_ROOT_PATH_KEY)
        db.add(root_cfg)
    root_cfg.value = normalized_root
    root_cfg.updated_at = datetime.now(timezone.utc)

    approval_cfg = configs.get(WORKSPACE_REQUIRE_APPROVAL_KEY)
    if approval_cfg is None:
        approval_cfg = LLMConfig(provider=WORKSPACE_REQUIRE_APPROVAL_KEY)
        db.add(approval_cfg)
    approval_cfg.value = "true" if require_technical_approval else "false"
    approval_cfg.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return WorkspaceSettings(
        root_path=normalized_root,
        require_technical_approval=require_technical_approval,
    )


def slugify_project_title(title: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (title or "project").strip().lower()).strip("-")
    return normalized[:48] or "project"


def get_project_workspace_dir(root_path: str, project_id: str, title: str) -> Path:
    root = Path(sanitize_workspace_root(root_path))
    return root / f"{slugify_project_title(title)}_{project_id}"


def ensure_within_workspace(project_dir: Path, target: Path) -> Path:
    project_dir_resolved = project_dir.resolve()
    target_resolved = target.resolve()
    if target_resolved != project_dir_resolved and project_dir_resolved not in target_resolved.parents:
        raise ValueError("Tentative d'accès hors du dossier projet bloquée.")
    return target_resolved


def _write_workspace_file(project_dir: Path, relative_path: str, content: str) -> str:
    target = ensure_within_workspace(project_dir, project_dir / relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return str(target)


def _set_workspace_permissions(project_dir: Path) -> None:
    try:
        os.chown(project_dir, CODE_SERVER_UID, CODE_SERVER_GID)
    except Exception:
        pass
    try:
        project_dir.chmod(0o775)
    except Exception:
        pass
    for path in project_dir.rglob("*"):
        try:
            os.chown(path, CODE_SERVER_UID, CODE_SERVER_GID)
        except Exception:
            pass
        try:
            if path.is_dir():
                path.chmod(0o775)
                continue
            mode = 0o775 if path.suffix == ".sh" or path.name.endswith(".sh") else 0o664
            path.chmod(mode)
        except Exception:
            continue


def _phase_status(default: str = "pending") -> list[dict[str, str]]:
    return [{"key": key, "label": label, "status": default} for key, label in PIPELINE_PHASES]


def build_initial_pipeline(settings: WorkspaceSettings, workspace_info: dict[str, Any] | None = None) -> dict[str, Any]:
    requires_approval = bool(settings.require_technical_approval)
    status = "awaiting_admin_approval" if requires_approval else "ready"
    phases = _phase_status()
    phases[0]["status"] = "waiting" if requires_approval else "completed"
    if workspace_info:
        phases[1]["status"] = "completed"
    return {
        "status": status,
        "current_phase": "admin_approval" if requires_approval and not workspace_info else ("technical_design" if workspace_info else "ready"),
        "requires_admin_approval": requires_approval,
        "root_path": settings.root_path,
        "project_dir": workspace_info.get("project_dir") if workspace_info else None,
        "generated_files": workspace_info.get("files", []) if workspace_info else [],
        "generated_file_count": len(workspace_info.get("files", [])) if workspace_info else 0,
        "last_error": None,
        "updated_at": utc_now_iso(),
        "phases": phases,
    }


def infer_workspace_info_from_pipeline(pipeline: dict[str, Any] | None, settings: WorkspaceSettings) -> dict[str, Any] | None:
    if not isinstance(pipeline, dict):
        return None
    project_dir = pipeline.get("project_dir")
    if not project_dir:
        return None
    try:
        resolved = Path(str(project_dir)).resolve()
    except Exception:
        return None
    generated_files = pipeline.get("generated_files")
    if not isinstance(generated_files, list):
        generated_files = []
    return {
        "project_dir": str(resolved),
        "root_path": pipeline.get("root_path") or settings.root_path,
        "generated_at": pipeline.get("updated_at") or utc_now_iso(),
        "files": generated_files,
        "repo_name": resolved.name,
    }


def ensure_pipeline_metadata(deliverables: dict[str, Any] | None, settings: WorkspaceSettings) -> dict[str, Any]:
    payload = dict(deliverables or {})
    workspace_info = payload.get(IMPLEMENTATION_WORKSPACE_KEY)
    pipeline = payload.get(IMPLEMENTATION_PIPELINE_KEY)
    if not isinstance(pipeline, dict):
        payload[IMPLEMENTATION_PIPELINE_KEY] = build_initial_pipeline(settings, workspace_info if isinstance(workspace_info, dict) else None)
        return payload

    normalized = dict(pipeline)
    normalized.setdefault("status", "ready")
    normalized.setdefault("current_phase", "ready")
    normalized.setdefault("requires_admin_approval", settings.require_technical_approval)
    normalized.setdefault("root_path", settings.root_path)
    normalized.setdefault("project_dir", workspace_info.get("project_dir") if isinstance(workspace_info, dict) else None)
    normalized.setdefault("generated_files", workspace_info.get("files", []) if isinstance(workspace_info, dict) else [])
    normalized.setdefault("generated_file_count", len(normalized.get("generated_files", [])))
    normalized.setdefault("last_error", None)
    normalized.setdefault("updated_at", utc_now_iso())
    existing_phases = normalized.get("phases")
    if isinstance(existing_phases, list):
        by_key = {item.get("key"): dict(item) for item in existing_phases if isinstance(item, dict)}
        normalized["phases"] = [
            {**{"key": key, "label": label, "status": "pending"}, **by_key.get(key, {})}
            for key, label in PIPELINE_PHASES
        ]
    else:
        normalized["phases"] = _phase_status()
    if not isinstance(workspace_info, dict):
        inferred_workspace = infer_workspace_info_from_pipeline(normalized, settings)
        if inferred_workspace:
            payload[IMPLEMENTATION_WORKSPACE_KEY] = inferred_workspace
    payload[IMPLEMENTATION_PIPELINE_KEY] = normalized
    return payload


def set_pipeline_phase(
    pipeline: dict[str, Any],
    phase_key: str,
    phase_status: str,
    *,
    overall_status: str | None = None,
    project_dir: str | None = None,
    generated_files: list[str] | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    updated = dict(pipeline or {})
    phases = [dict(item) for item in updated.get("phases") or _phase_status()]
    for item in phases:
        if item.get("key") == phase_key:
            item["status"] = phase_status
    updated["phases"] = phases
    updated["current_phase"] = phase_key
    if overall_status:
        updated["status"] = overall_status
    if project_dir:
        updated["project_dir"] = project_dir
    if generated_files is not None:
        updated["generated_files"] = generated_files
        updated["generated_file_count"] = len(generated_files)
    if last_error is not None:
        updated["last_error"] = last_error
    updated["updated_at"] = utc_now_iso()
    return updated


def _match_stack(source: str, patterns: list[tuple[str, list[str]]], default: str) -> str:
    for stack_name, keywords in patterns:
        for keyword in keywords:
            if re.search(keyword, source):
                return stack_name
    return default


STATIC_ONLY_CONTEXT_PATTERNS = [
    r"\bonly\s+html\b.*\bcss\b.*\bjs\b",
    r"\bhtml\b.*\bcss\b.*\bjs\b.*\bonly\b",
    r"\bhtml\s*/\s*css\s*/\s*js\b.*\bonly\b",
    r"\bvanilla\s+js\b",
    r"\bpure\s+html\b.*\bcss\b.*\bjs\b",
    r"\bsans\s+framework\b",
    r"\bno\s+framework\b",
    r"\bwithout\s+framework\b",
    r"\buniquement\s+html\b.*\bcss\b.*\bjs\b",
    r"\bjust\s+html\b.*\bcss\b.*\bjs\b",
]


def _looks_like_static_only_request(source: str) -> bool:
    lowered = source.lower()
    return any(re.search(pattern, lowered, re.DOTALL) for pattern in STATIC_ONLY_CONTEXT_PATTERNS)


def detect_application_stack(
    project_title: str,
    input_text: str,
    deliverables: dict[str, Any],
    *,
    extra_context: str = "",
) -> dict[str, str]:
    source = "\n".join([
        project_title or "",
        input_text or "",
        extra_context or "",
        str(deliverables.get("cdc") or ""),
        str(deliverables.get("architecture") or ""),
        str(deliverables.get("roadmap") or ""),
        str(deliverables.get("notes_synthese") or ""),
    ]).lower()

    if _looks_like_static_only_request(source):
        return {
            "backend": "none",
            "frontend": "static",
            "mobile": "none",
            "database": "none",
            "languages": "html, css, javascript",
            "generation_backend": "none",
            "generation_frontend": "static",
        }

    backend_patterns: list[tuple[str, list[str]]] = [
        ("laravel", [r"\blaravel\b", r"\bphp\b", r"\bsymfony\b", r"\bcodeigniter\b", r"\byii\b", r"\bcakephp\b", r"\bslim\b"]),
        ("rails", [r"\brails\b", r"ruby on rails", r"\bruby\b", r"\bsinatra\b", r"\bhanami\b"]),
        ("django", [r"\bdjango\b"]),
        ("flask", [r"\bflask\b", r"\bquart\b", r"\bfalcon\b"]),
        ("fastapi", [r"\bfastapi\b", r"\bstarlette\b", r"\bpython api\b"]),
        ("nestjs", [r"\bnest\b", r"\bnestjs\b"]),
        ("express", [r"\bexpress\b", r"\bnode\b", r"\bnodejs\b", r"\bkoa\b", r"\bhapi\b", r"\bfastify\b", r"\badonis\b"]),
        ("springboot", [r"spring boot", r"\bspring\b", r"\bjava\b", r"\bquarkus\b", r"\bmicronaut\b"]),
        ("dotnet", [r"\basp\.net\b", r"\baspnet\b", r"\b.net\b", r"\bdotnet\b", r"\bc#\b", r"\bblazor\b"]),
        ("go", [r"\bgolang\b", r"\bgo api\b", r"\bgin\b", r"\bfiber\b", r"\becho\b", r"\bchi\b", r"\bbeego\b"]),
        ("rust", [r"\brust\b", r"\baxum\b", r"\bactix\b", r"\brocket\b", r"\bwarp\b"]),
        ("phoenix", [r"\bphoenix\b", r"\belixir\b"]),
        ("kotlin", [r"\bkotlin\b", r"ktor"]),
    ]

    frontend_patterns: list[tuple[str, list[str]]] = [
        ("nextjs", [r"next\.?js", r"\bnextjs\b"]),
        ("nuxt", [r"\bnuxt\b", r"nuxt\.?js"]),
        ("sveltekit", [r"\bsveltekit\b", r"\bsvelte\b"]),
        ("angular", [r"\bangular\b"]),
        ("vue", [r"\bvue\b", r"\bvuejs\b", r"\bvite\b.*\bvue\b"]),
        ("react", [r"\breact\b", r"\breactjs\b", r"\bvite\b.*\breact\b"]),
        ("blade", [r"\bblade\b", r"laravel blade", r"\blaravel views?\b"]),
        ("flutter_web", [r"flutter web"]),
        ("static", [r"\bhtml\b", r"\bcss\b", r"\bjavascript\b", r"\bvanilla js\b"]),
    ]

    mobile_patterns: list[tuple[str, list[str]]] = [
        ("flutter", [r"\bflutter\b", r"\bdart\b"]),
        ("react_native", [r"react native", r"\bexpo\b"]),
        ("swift", [r"\bswiftui\b", r"\bswift\b", r"\bios\b"]),
        ("kotlin_mobile", [r"\bkotlin\b", r"\bandroid\b", r"jetpack compose"]),
        ("ionic", [r"\bionic\b", r"capacitor", r"cordova"]),
    ]

    database_patterns: list[tuple[str, list[str]]] = [
        ("postgresql", [r"postgres", r"postgresql"]),
        ("mysql", [r"\bmysql\b", r"mariadb"]),
        ("mongodb", [r"mongodb", r"mongo db", r"\bmongo\b"]),
        ("sqlite", [r"\bsqlite\b"]),
        ("redis", [r"\bredis\b"]),
        ("supabase", [r"\bsupabase\b"]),
        ("firebase", [r"\bfirebase\b", r"firestore"]),
    ]

    language_keywords = {
        "python": [r"\bpython\b"],
        "php": [r"\bphp\b"],
        "javascript": [r"\bjavascript\b"],
        "typescript": [r"\btypescript\b"],
        "java": [r"\bjava\b"],
        "csharp": [r"\bc#\b", r"\bdotnet\b", r"\basp\.net\b"],
        "go": [r"\bgolang\b", r"\bgo\b"],
        "rust": [r"\brust\b"],
        "ruby": [r"\bruby\b"],
        "elixir": [r"\belixir\b"],
        "kotlin": [r"\bkotlin\b"],
        "swift": [r"\bswift\b"],
        "dart": [r"\bdart\b"],
    }

    backend = _match_stack(source, backend_patterns, "fastapi")
    frontend = _match_stack(source, frontend_patterns, "static")
    mobile = _match_stack(source, mobile_patterns, "none")
    database = _match_stack(source, database_patterns, "postgresql")

    detected_languages = [
        language
        for language, patterns in language_keywords.items()
        if any(re.search(pattern, source) for pattern in patterns)
    ]

    generation_backend_map = {
        "laravel": "laravel",
        "django": "fastapi",
        "flask": "fastapi",
        "fastapi": "fastapi",
        "express": "fastapi",
        "nestjs": "fastapi",
        "springboot": "fastapi",
        "dotnet": "fastapi",
        "go": "fastapi",
        "rust": "fastapi",
        "rails": "fastapi",
        "phoenix": "fastapi",
        "kotlin": "fastapi",
        "none": "none",
    }
    generation_frontend_map = {
        "nextjs": "nextjs",
        "react": "nextjs",
        "vue": "static",
        "nuxt": "static",
        "sveltekit": "static",
        "angular": "static",
        "flutter_web": "static",
        "blade": "monolith",
        "static": "static",
    }

    generation_backend = generation_backend_map.get(backend, "fastapi")
    generation_frontend = generation_frontend_map.get(frontend, "static")

    return {
        "backend": backend,
        "frontend": frontend,
        "mobile": mobile,
        "database": database,
        "languages": ", ".join(detected_languages) if detected_languages else "inconnu",
        "generation_backend": generation_backend,
        "generation_frontend": generation_frontend,
    }



def _project_env_template(slug: str, stack: dict[str, str]) -> str:
    frontend_port = "3000" if stack.get("generation_frontend") == "nextjs" else "80"
    if stack.get("generation_backend") == "none":
        return f"""APP_NAME={slug}
APP_ENV=local
APP_KEY=change-me
APP_DEBUG=true
APP_URL=https://{slug}.example.com
FRONTEND_DOMAIN={slug}.example.com
FRONTEND_PORT={frontend_port}
STACK_BACKEND=none
STACK_FRONTEND={stack.get('frontend', 'static')}
STACK_LAYOUT=static-only
"""
    if stack.get("generation_frontend") == "monolith":
        return f"""APP_NAME={slug}
APP_ENV=local
APP_KEY=change-me
APP_DEBUG=true
APP_URL=https://{slug}.example.com
DB_CONNECTION=sqlite
DB_DATABASE=database/database.sqlite
STACK_BACKEND={stack.get('backend', 'laravel')}
STACK_FRONTEND={stack.get('frontend', 'blade')}
STACK_LAYOUT=monolith
"""
    if stack.get('database') == 'sqlite':
        return f"""APP_NAME={slug}
APP_ENV=local
APP_KEY=change-me
APP_DEBUG=true
APP_URL=https://{slug}.example.com
DB_CONNECTION=sqlite
DB_DATABASE=database/database.sqlite
FRONTEND_PORT={frontend_port}
STACK_BACKEND={stack.get('backend', 'fastapi')}
STACK_FRONTEND={stack.get('frontend', 'static')}
"""
    return f"""APP_NAME={slug}
FRONTEND_DOMAIN={slug}.example.com
API_DOMAIN=api-{slug}.example.com
POSTGRES_DB={slug}_db
POSTGRES_USER={slug}_user
POSTGRES_PASSWORD=change-me
SECRET_KEY=change-me
API_PORT=8000
FRONTEND_PORT={frontend_port}
STACK_BACKEND={stack.get('backend', 'fastapi')}
STACK_FRONTEND={stack.get('frontend', 'static')}
"""


def _project_compose_template(slug: str, stack: dict[str, str]) -> str:
    frontend_port = "3000" if stack.get("generation_frontend") == "nextjs" else "80"
    if stack.get("generation_backend") == "none":
        return f"""services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    env_file:
      - .env
    expose:
      - "{frontend_port}"
    restart: unless-stopped
"""
    if stack.get("generation_frontend") == "monolith":
        return f"""services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    expose:
      - "8000"
    restart: unless-stopped
"""
    if stack.get('database') == 'sqlite':
        return f"""services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file:
      - .env
    expose:
      - "8000"
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      - backend
    expose:
      - "{frontend_port}"
    restart: unless-stopped
"""
    return f"""services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      - db
    expose:
      - "8000"
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      - backend
    expose:
      - "{frontend_port}"
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${{POSTGRES_DB}}
      POSTGRES_USER: ${{POSTGRES_USER}}
      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD}}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
"""


def _project_traefik_template(slug: str, stack: dict[str, str]) -> str:
    frontend_port = "3000" if stack.get("generation_frontend") == "nextjs" else "80"
    if stack.get("generation_backend") == "none":
        return f"""services:
  frontend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{slug}-frontend.rule=Host(`${{FRONTEND_DOMAIN}}`)
      - traefik.http.routers.{slug}-frontend.entrypoints=websecure
      - traefik.http.routers.{slug}-frontend.tls=true
      - traefik.http.routers.{slug}-frontend.tls.certresolver=myresolver
      - traefik.http.services.{slug}-frontend.loadbalancer.server.port={frontend_port}
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
"""
    if stack.get("generation_frontend") == "monolith":
        return f"""services:
  app:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{slug}-app.rule=Host(`${{FRONTEND_DOMAIN}}`)
      - traefik.http.routers.{slug}-app.entrypoints=websecure
      - traefik.http.routers.{slug}-app.tls.certresolver=myresolver
      - traefik.http.services.{slug}-app.loadbalancer.server.port=8000
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
"""
    return f"""services:
  backend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{slug}-backend.rule=Host(`${{API_DOMAIN}}`)
      - traefik.http.routers.{slug}-backend.entrypoints=websecure
      - traefik.http.routers.{slug}-backend.tls.certresolver=myresolver
      - traefik.http.services.{slug}-backend.loadbalancer.server.port=8000
    networks:
      - proxy_net

  frontend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{slug}-frontend.rule=Host(`${{FRONTEND_DOMAIN}}`)
      - traefik.http.routers.{slug}-frontend.entrypoints=websecure
      - traefik.http.routers.{slug}-frontend.tls.certresolver=myresolver
      - traefik.http.services.{slug}-frontend.loadbalancer.server.port={frontend_port}
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
"""


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _markdown_excerpt(text: str, limit: int = 2400) -> str:
    return " ".join((text or "").split())[:limit]


def _document_fallback(
    relative_path: str,
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    workspace_root: str,
    client_context: str,
) -> str:
    if relative_path == "README.md":
        return _readme(project_title, project_id, deliverables, workspace_root, stack, client_context)
    if relative_path == "docs/cdc.md":
        return str(deliverables.get("cdc") or "").strip() or "# CDC\n"
    if relative_path == "docs/mcd.md":
        return str(deliverables.get("mcd") or "").strip() or "# MCD\n"
    if relative_path == "docs/architecture.md":
        return str(deliverables.get("architecture") or "").strip() or "# Architecture\n"
    if relative_path == "docs/roadmap.md":
        return str(deliverables.get("roadmap") or "").strip() or "# Roadmap\n"
    if relative_path == "docs/notes_synthese.md":
        return str(deliverables.get("notes_synthese") or "").strip() or "# Notes de synthese\n"
    if relative_path == "docs/client_updates.md":
        return _client_updates(project_title, project_id, input_text, deliverables, client_context)
    if relative_path == "docs/stack_decision.md":
        return _stack_decision(project_title, input_text, stack, client_context)
    if relative_path == "docs/architecture.md":
        return _architecture(project_title, input_text, deliverables, stack)
    if relative_path == "docs/global_environment.md":
        return _global_environment(project_title, project_id, stack, client_context)
    if relative_path == "docs/implementation_plan.md":
        return _implementation_plan(project_title, input_text, deliverables)
    if relative_path == "docs/requirements_matrix.md":
        return _requirements_matrix(project_title, input_text, deliverables, stack)
    if relative_path == "docs/user_stories.md":
        return _user_stories(project_title, input_text, deliverables, stack)
    if relative_path == "docs/functional_spec.md":
        return _functional_spec(project_title, input_text, deliverables, stack)
    if relative_path == "docs/interface_spec.md":
        return _interface_spec(project_title, input_text, deliverables, stack)
    if relative_path == "docs/mld.md":
        return _mld(project_title, input_text, deliverables, stack)
    if relative_path == "docs/api_contract.md":
        return _api_contract(project_title, input_text, deliverables, stack)
    if relative_path == "docs/ide_generation_prompt.md":
        return _ide_generation_prompt(project_title, project_id, input_text, deliverables, stack, workspace_root, client_context)
    return "# Document\n"


async def _generate_document_markdown(
    relative_path: str,
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    workspace_root: str,
    client_context: str,
    llm_router: LLMRouter | None,
) -> str:
    role_map = {
        "README.md": ("devops", "DevOps & Handoff"),
        "docs/cdc.md": ("strategy", "Stratégie & Growth"),
        "docs/mcd.md": ("engineering", "Ingénierie & Architecture"),
        "docs/architecture.md": ("engineering", "Ingénierie & Architecture"),
        "docs/roadmap.md": ("strategy", "Stratégie & Growth"),
        "docs/notes_synthese.md": ("orchestrator", "Synthèse"),
        "docs/client_updates.md": ("ux", "Conception & UX"),
        "docs/stack_decision.md": ("engineering", "Ingénierie & Architecture"),
        "docs/architecture.md": ("engineering", "Ingénierie & Architecture"),
        "docs/global_environment.md": ("devops", "DevOps & Sécurité"),
        "docs/implementation_plan.md": ("devops", "DevOps & Sécurité"),
        "docs/requirements_matrix.md": ("devops", "DevOps & Sécurité"),
        "docs/user_stories.md": ("strategy", "Stratégie & Growth"),
        "docs/functional_spec.md": ("engineering", "Ingénierie & Architecture"),
        "docs/interface_spec.md": ("ux", "Conception & UX"),
        "docs/mld.md": ("engineering", "Ingénierie & Architecture"),
        "docs/api_contract.md": ("engineering", "Ingénierie & Architecture"),
        "docs/ide_generation_prompt.md": ("orchestrator", "Synthèse"),
    }
    agent_type, role_label = role_map.get(relative_path, ("orchestrator", "Synthèse"))
    fallback = _document_fallback(relative_path, project_title, project_id, input_text, deliverables, stack, workspace_root, client_context)
    if llm_router is None:
        return fallback

    sections = [
        f"Projet: {project_title}",
        f"Project ID: {project_id}",
        f"Document cible: {relative_path}",
        f"Rôle de l'employé: {role_label}",
        f"Stack détectée: backend={stack.get('backend')}, frontend={stack.get('frontend')}, mobile={stack.get('mobile')}, database={stack.get('database')}, languages={stack.get('languages')}",
        f"Brief initial: {_markdown_excerpt(input_text, 2400)}",
    ]
    if client_context.strip():
        sections.append(f"Corrections récentes: {_markdown_excerpt(client_context, 1600)}")
    for label, content in (
        ("CDC", deliverables.get("cdc")),
        ("MCD", deliverables.get("mcd")),
        ("Architecture", deliverables.get("architecture")),
        ("Roadmap", deliverables.get("roadmap")),
        ("Notes synthèse", deliverables.get("notes_synthese")),
    ):
        excerpt = _markdown_excerpt(str(content or ""), 2200)
        if excerpt:
            sections.append(f"{label}: {excerpt}")

    system_prompts = {
        "README.md": (
            "Tu es un employé DevOps chargé de rédiger le README final du workspace. "
            "Tu réponds uniquement en Markdown propre, sans préambule, sans notes de raisonnement. "
            "Le document doit décrire le projet, le stack validé, le relais vers l'éditeur web et les règles de travail."
        ),
        "docs/cdc.md": (
            "Tu es un employé Stratégie & Growth chargé de rédiger le cahier des charges final. "
            "Tu réponds uniquement en Markdown structuré et directement copiable dans le fichier cible."
        ),
        "docs/mcd.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger le MCD final. "
            "Tu réponds uniquement en Markdown et tu inclus un bloc Mermaid si cela améliore la clarté."
        ),
        "docs/architecture.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger l'architecture technique finale. "
            "Tu réponds uniquement en Markdown structuré."
        ),
        "docs/roadmap.md": (
            "Tu es un employé Stratégie & Growth chargé de rédiger la roadmap finale. "
            "Tu réponds uniquement en Markdown structuré avec des phases, priorités et jalons."
        ),
        "docs/notes_synthese.md": (
            "Tu es un employé chargé de la synthèse finale. "
            "Tu réponds uniquement en Markdown et tu consolides les arbitrages, risques et points ouverts."
        ),
        "docs/client_updates.md": (
            "Tu es un employé Conception & UX chargé de tenir le journal des corrections client. "
            "Tu réponds uniquement en Markdown lisible et exploitable."
        ),
        "docs/stack_decision.md": (
            "Tu es un employé Ingénierie & Architecture chargé de documenter la décision de stack. "
            "Tu réponds uniquement en Markdown et tu explicites les choix techniques retenus."
        ),
        "docs/architecture.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger l'architecture technique finale. "
            "Tu réponds uniquement en Markdown structuré, avec couches, composants, flux, responsabilités, sécurité, déploiement et limites."
        ),
        "docs/global_environment.md": (
            "Tu es un employé DevOps & Sécurité chargé de documenter le contrat d'environnement du workspace. "
            "Tu réponds uniquement en Markdown et tu explicites les règles de confinement et d'exécution. "
            "Le document doit rappeler le déploiement complet: compatibilité docker_manager, compatibilité traefik_master, réseau partagé proxy_net, labels Traefik obligatoires, domaine cible du type mon-projet.it-sefako.com, et maintien de docker-compose.yml, docker-compose.traefik.yml, docker-manager.yml et .env.example. "
            "Pour un stack simple HTML/CSS/JavaScript à la racine, tu fournis aussi un exemple de contenu concret pour ces fichiers, inspiré d'un projet statique comme portfolio_grace. "
            "Pour un stack fullstack avec API, frontend et base de données, tu fournis aussi un exemple complet de contenu YAML inspiré d'un projet comme kaba-compta, y compris le cas d'un docker-compose-local.yml si un mode local est utile."
        ),
        "docs/implementation_plan.md": (
            "Tu es un employé DevOps & Sécurité chargé de rédiger le plan d'implémentation. "
            "Tu réponds uniquement en Markdown actionnable pour la reprise dans l'éditeur web."
        ),
        "docs/requirements_matrix.md": (
            "Tu es un employé DevOps & Sécurité chargé de rédiger la matrice de couverture du CDC. "
            "Tu réponds uniquement en Markdown et tu relies chaque exigence aux livrables et documents de référence."
        ),
        "docs/user_stories.md": (
            "Tu es un employé Stratégie & Growth chargé de rédiger les user stories finales. "
            "Tu réponds uniquement en Markdown structuré, avec objectifs, acteurs, priorités, parcours nominaux, variantes, dépendances et critères d'acceptation détaillés."
        ),
        "docs/functional_spec.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger les spécifications fonctionnelles. "
            "Tu réponds uniquement en Markdown structuré et tu détailles les fonctionnalités, règles métier, données manipulées, cas d'erreur, validations et critères de succès."
        ),
        "docs/interface_spec.md": (
            "Tu es un employé Conception & UX chargé de rédiger les spécifications d'interface. "
            "Tu réponds uniquement en Markdown structuré et tu détailles les écrans, composants, états, interactions, responsive, accessibilité et messages système."
        ),
        "docs/mld.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger le MLD final. "
            "Tu réponds uniquement en Markdown structuré et tu précises tables, champs, clés, index, relations, contraintes et exemples de valeurs."
        ),
        "docs/api_contract.md": (
            "Tu es un employé Ingénierie & Architecture chargé de rédiger le contrat API. "
            "Tu réponds uniquement en Markdown structuré et tu précises les endpoints, méthodes, payloads, erreurs, exemples de requêtes/réponses et règles d'authentification."
        ),
        "docs/ide_generation_prompt.md": (
            "Tu es un employé chargé de rédiger le prompt de génération pour l'IA de l'IDE. "
            "Tu réponds uniquement en Markdown clair, avec un prompt prêt à copier-coller dans l'IDE, "
            "et tu t'assures qu'il ordonne la lecture des documents de cadrage, le respect du stack validé, "
            "la couverture des user stories, des fonctionnalités, des interfaces, des MCD/MLD, des règles métier, "
            "des contrats API et du déploiement."
        ),
    }

    try:
        raw = await llm_router.generate(
            prompt="\n\n".join(sections),
            agent_type=agent_type,
            system_prompt=system_prompts.get(relative_path, "Tu réponds uniquement en Markdown propre et exploitable."),
        )
        cleaned = _strip_markdown_fences(raw)
        if cleaned.strip():
            return cleaned if cleaned.endswith("\n") else cleaned + "\n"
    except Exception as e:
        print(f"Erreur génération Markdown {relative_path}: {e}")

    return fallback if fallback.endswith("\n") else fallback + "\n"


async def _documentation_specs(
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    workspace_root: str,
    client_context: str = "",
    llm_router: LLMRouter | None = None,
) -> list[tuple[str, str]]:
    slug = slugify_project_title(project_title)
    doc_paths = [
        "README.md",
        "docs/cdc.md",
        "docs/mcd.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/notes_synthese.md",
        "docs/client_updates.md",
        "docs/stack_decision.md",
        "docs/global_environment.md",
        "docs/implementation_plan.md",
        "docs/requirements_matrix.md",
        "docs/user_stories.md",
        "docs/functional_spec.md",
        "docs/interface_spec.md",
        "docs/mld.md",
        "docs/api_contract.md",
        "docs/ide_generation_prompt.md",
    ]
    markdown_docs = []
    for relative_path in doc_paths:
        markdown_docs.append(
            await _generate_document_markdown(
                relative_path,
                project_title,
                project_id,
                input_text,
                deliverables,
                stack,
                workspace_root,
                client_context,
                llm_router,
            )
        )
    docs = list(zip(doc_paths, markdown_docs, strict=True))
    docs.append((".aia/workspace-policy.json", _workspace_policy(str(Path(workspace_root).resolve() / f"{slug}_{project_id}"))))
    return [(path, content) for path, content in docs]


def _client_updates(project_title: str, project_id: str, input_text: str, deliverables: dict[str, Any], client_context: str) -> str:
    lines = [
        "# Journal des corrections client",
        "",
        f"Projet: {project_title}",
        f"Project ID: `{project_id}`",
        "",
        "## Brief initial",
        input_text.strip()[:1600] or "Aucun brief initial disponible.",
        "",
        "## Corrections récentes",
    ]
    if client_context.strip():
        lines.extend(client_context.strip().splitlines())
    else:
        lines.append("Aucune correction récente n'a encore été enregistrée.")
    validation_answers = deliverables.get("validation_answers")
    if isinstance(validation_answers, list) and validation_answers:
        lines.extend([
            "",
            "## Réponses de validation",
        ])
        for index, item in enumerate(validation_answers, start=1):
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("id") or f"Question {index}").strip()
            answer = str(item.get("answer") or "").strip()
            if answer:
                lines.append(f"{index}. {question} -> {answer}")
    return "\n".join(lines) + "\n"


def _stack_decision(project_title: str, input_text: str, stack: dict[str, str], client_context: str = "") -> str:
    layout = "monolithique" if stack.get("generation_frontend") == "monolith" else "séparé"
    frontend_decision = (
        "Aucun dossier `frontend/` n'est requis par les agents."
        if layout == "monolithique"
        else "L'éditeur web décidera de la présence d'un dossier `frontend/` et le créera uniquement si le stack le justifie."
    )
    if stack.get("generation_backend") == "none":
        backend_decision = "Aucun dossier `backend/` n'est requis par les agents."
    elif layout == "monolithique":
        backend_decision = "Aucun dossier `backend/` n'est requis par les agents."
    else:
        backend_decision = "L'éditeur web décidera de la présence d'un dossier `backend/` et le créera uniquement si le stack le justifie."
    return f"""# Décision de stack

## Projet
- Titre: {project_title}

## Brief de départ
{input_text.strip()[:1800]}

## Corrections récentes
{client_context.strip()[:1200] or "Aucune correction récente."}

## Stack détectée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- mobile: `{stack.get('mobile')}`
- base de données: `{stack.get('database')}`
- langages: `{stack.get('languages')}`

## Décision de structure
- layout retenu: `{layout}`
- implémentation par les employés: `non`
- implémentation par l'éditeur web: `oui`

## Conséquence sur le dépôt
- {frontend_decision}
- {backend_decision}

    ## Règle de pilotage
    Les employés du studio produisent uniquement les documents de cadrage.
    Le document `docs/global_environment.md` doit être relu avant toute génération ou modification de fichiers Docker.
    L'éditeur web prend ensuite le relais pour poursuivre l'implémentation manuelle à partir du cadrage validé.
    """


def _architecture(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    cdc = _markdown_excerpt(str(deliverables.get("cdc") or ""), 1600) or "CDC à préciser."
    architecture_source = _markdown_excerpt(str(deliverables.get("architecture") or ""), 2200) or "Architecture à préciser."
    roadmap = _markdown_excerpt(str(deliverables.get("roadmap") or ""), 1000) or "Roadmap à préciser."
    return f"""# Architecture technique

## Projet
- Titre: {project_title}

## Objectif
- décrire l'architecture cible de manière suffisamment précise pour permettre une implémentation fidèle
- clarifier les responsabilités des couches
- documenter les flux entre frontend, backend, base de données et services annexes

## Extrait du CDC
{cdc}

## Source d'architecture
{architecture_source}

## Stack validée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- mobile: `{stack.get('mobile')}`
- base de données: `{stack.get('database')}`
- langages: `{stack.get('languages')}`

## Vue d'ensemble
| Couche | Responsabilité | Entrées | Sorties |
|---|---|---|---|
| Présentation | affichage, navigation, interactions | données d'API, état UI | événements utilisateur, requêtes |
| Application / API | règles métier, orchestration, validation | requêtes, paramètres, contexte | réponses JSON, erreurs structurées |
| Domaine | règles cœur métier | événements, données métier | objets métier, décisions |
| Persistance | stockage durable | écritures, lectures | entités, listes, états |
| Déploiement | exposition et supervision | services, environnements, domaines | application accessible |

## Composants attendus
- frontend React avec séparation claire des composants et services
- backend FastAPI avec routes, schémas, services et couche d'accès aux données
- PostgreSQL comme source de vérité des données
- conteneurisation Docker et exposition Traefik

## Flux principaux
1. le navigateur charge le frontend
2. le frontend interroge l'API
3. l'API valide et applique les règles métier
4. l'API lit ou écrit en base PostgreSQL
5. le frontend affiche le résultat ou l'erreur

## Sécurité et robustesse
- valider toutes les entrées côté backend
- ne jamais exposer de secrets dans les fichiers `.md`
- séparer les variables d'environnement, le code et les données
- documenter les droits d'accès et les routes protégées

## Déploiement
- compatibilité docker_manager obligatoire
- compatibilité traefik_master obligatoire
- réseau partagé `proxy_net`
- domaine public du type `mon-projet.it-sefako.com`
- fichiers de déploiement à maintenir: `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml`, `.env.example`

## Roadmap technique
{roadmap}

## Résultat attendu
- un plan architectural suffisant pour que l'IA de l'IDE reconstruise l'application sans inventer la structure
"""


def _static_stack_deployment_examples(project_slug: str) -> str:
    domain = f"{project_slug}.it-sefako.com"
    api_domain = f"api-{project_slug}.it-sefako.com"
    return f"""## Exemple de stack simple HTML / CSS / JavaScript à la racine du projet

Cas d'usage: projet statique comme `portfolio_grace`, avec les fichiers applicatifs directement à la racine du dépôt:
- `index.html`
- `styles.css`
- `app.js`
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.traefik.yml`
- `docker-manager.yml`
- `.env.example`

### `docker-compose.yml`
```yaml
services:
  frontend:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    restart: unless-stopped
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
```

### `docker-compose.traefik.yml`
```yaml
services:
  frontend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{project_slug}.rule=Host(`{domain}`)
      - traefik.http.routers.{project_slug}.entrypoints=websecure
      - traefik.http.routers.{project_slug}.tls=true
      - traefik.http.routers.{project_slug}.tls.certresolver=myresolver
      - traefik.http.services.{project_slug}.loadbalancer.server.port=80
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
```

### `docker-manager.yml`
```yaml
version: 1
kind: website
name: {project_slug}
services:
  frontend:
    public: true
    domain: {domain}
    port: 80
    network: proxy_net
    description: Site statique HTML / CSS / JavaScript
```

### `.env.example`
```env
DOMAIN={domain}
API_DOMAIN={api_domain}
TZ=UTC
```

### Rappel pratique
- `docker_manager` et `traefik_master` doivent partager `proxy_net`.
- Les labels Traefik sont obligatoires pour l'exposition publique.
- La racine du projet reste le point d'entrée quand le site est statique.
"""


def _fullstack_deployment_examples(project_slug: str) -> str:
    frontend_domain = f"{project_slug}.it-sefako.com"
    api_domain = f"api-{project_slug}.it-sefako.com"
    db_domain = f"db-{project_slug}.it-sefako.com"
    return f"""## Exemple de stack fullstack avec API, frontend et admin DB

Cas d'usage: projet comme `kaba-compta`, avec séparation frontend / backend / base de données.

### `docker-compose.yml`
```yaml
services:
  api:
    build: ./backend
    restart: always
    env_file:
      - ./backend/.env
    depends_on:
      - db
    expose:
      - "8000"
    networks:
      - backend
      - proxy_net

  db:
    image: mongo:latest
    restart: always
    volumes:
      - db_data:/data/db
    networks:
      - backend

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: always
    env_file:
      - ./frontend/.env
    expose:
      - "3000"
    networks:
      - proxy_net

  dbadmin:
    image: mongo-express:latest
    restart: always
    env_file:
      - .env
    expose:
      - "8081"
    networks:
      - backend
      - proxy_net

volumes:
  db_data:

networks:
  backend:
  proxy_net:
    external: true
```

### `docker-compose.traefik.yml`
```yaml
services:
  api:
    labels:
      - traefik.enable=true
      - traefik.http.routers.{project_slug}-api.rule=Host(`{api_domain}`)
      - traefik.http.routers.{project_slug}-api.entrypoints=websecure
      - traefik.http.routers.{project_slug}-api.tls.certresolver=myresolver
      - traefik.http.services.{project_slug}-api.loadbalancer.server.port=8000
      - traefik.docker.network=proxy_net
    networks:
      - backend
      - proxy_net

  frontend:
    labels:
      - traefik.enable=true
      - traefik.http.routers.{project_slug}-frontend.rule=Host(`{frontend_domain}`)
      - traefik.http.routers.{project_slug}-frontend.entrypoints=websecure
      - traefik.http.routers.{project_slug}-frontend.tls.certresolver=myresolver
      - traefik.http.services.{project_slug}-frontend.loadbalancer.server.port=3000
      - traefik.docker.network=proxy_net
    networks:
      - proxy_net

  dbadmin:
    labels:
      - traefik.enable=true
      - traefik.http.routers.{project_slug}-dbadmin.rule=Host(`{db_domain}`)
      - traefik.http.routers.{project_slug}-dbadmin.entrypoints=websecure
      - traefik.http.routers.{project_slug}-dbadmin.tls.certresolver=myresolver
      - traefik.http.services.{project_slug}-dbadmin.loadbalancer.server.port=8081
      - traefik.docker.network=proxy_net
    networks:
      - backend
      - proxy_net

networks:
  backend:
  proxy_net:
    external: true
```

### `docker-manager.yml`
```yaml
version: 1
kind: fullstack
domains:
  frontend: {frontend_domain}
  api: {api_domain}
  db_admin: {db_domain}
services:
  frontend:
    public: true
    domain: {frontend_domain}
    port: 3000
  api:
    public: true
    domain: {api_domain}
    port: 8000
    extra_networks:
      - backend
  db:
    public: false
  dbadmin:
    public: true
    domain: {db_domain}
    port: 8081
    extra_networks:
      - backend
```

### `.env.example`
```env
LANDING_DOMAIN_URL={frontend_domain}
DOMAIN_API={api_domain}
DB_MANAGER_URL={db_domain}
TZ=UTC
```

### Variante locale
Si le projet a besoin d'un mode local de développement, ajouter un `docker-compose-local.yml` pour l'override dev:
- montage des volumes source
- ports exposés en local
- dépendances live reload si le stack le permet

### Rappel pratique
- `proxy_net` reste le réseau partagé avec Traefik.
- Les services exposés publiquement doivent avoir leurs labels Traefik.
- Les fichiers `.env.example` doivent rester clairs et reproductibles.
"""


def _global_environment(project_title: str, project_id: str, stack: dict[str, str], client_context: str = "") -> str:
    project_slug = slugify_project_title(project_title)
    static_examples = _static_stack_deployment_examples(project_slug)
    fullstack_examples = _fullstack_deployment_examples(project_slug)
    if stack.get("generation_backend") == "none":
        return f"""# Global Environment

## Projet
- Titre: {project_title}
- Project ID: `{project_id}`

## Rôle de ce document
Ce fichier est le contrat d'environnement à suivre par l'agent IA dans VS Code web.
Il doit être lu avant toute modification de fichier, avant toute création de config, et avant toute génération de contenu de déploiement.
Si une consigne utilisateur contredit un ancien document, la consigne la plus récente prime.

## Source de vérité
- `README.md`
- `docs/client_updates.md`
- `docs/stack_decision.md`
- `docs/architecture.md`
- `docs/requirements_matrix.md`
- `docs/user_stories.md`
- `docs/functional_spec.md`
- `docs/interface_spec.md`
- `docs/mld.md`
- `docs/api_contract.md`
- `docs/ide_generation_prompt.md`
- `docs/global_environment.md`

## Chaîne de production
```mermaid
flowchart LR
    subgraph EMP[Employés]
        E1[Stratégie]
        E2[UX]
        E3[Ingénierie]
        E4[DevOps]
    end
    subgraph DOC[Pack documentaire]
        D1[Docs Markdown]
        D2[README + specs]
        D3[Architecture + MLD]
    end
    subgraph ORC[Orchestrateur]
        O1[Relit]
        O2[Valide]
        O3[Relance si besoin]
    end
    subgraph IDE[IA de l'IDE]
        I1[Lit tous les docs]
        I2[Genere l'app]
        I3[Respecte le stack]
    end
    F1[Application finale]

    E1 --> D1
    E2 --> D2
    E3 --> D3
    E4 --> D2
    D1 --> O1
    D2 --> O1
    D3 --> O1
    O1 --> O2 --> O3 --> I1
    I1 --> I2 --> I3 --> F1
```

## Ordre de lecture conseillé
1. `README.md`
2. `docs/stack_decision.md`
3. `docs/architecture.md`
4. `docs/user_stories.md`
5. `docs/functional_spec.md`
6. `docs/interface_spec.md`
7. `docs/mld.md`
8. `docs/api_contract.md`
9. `docs/global_environment.md`
10. `docs/ide_generation_prompt.md`

## Pack documentaire attendu
- vision produit et périmètre
- user stories complètes par rôle
- spécifications fonctionnelles détaillées par feature
- spécifications d'interface écran par écran
- MLD détaillé avec tables, champs et relations
- contrat API détaillé
- plan d'implémentation et matrice de couverture
- prompt de génération pour l'IA de l'IDE

## Ordre de lecture conseillé
1. `README.md`
2. `docs/stack_decision.md`
3. `docs/architecture.md`
4. `docs/user_stories.md`
5. `docs/functional_spec.md`
6. `docs/interface_spec.md`
7. `docs/mld.md`
8. `docs/api_contract.md`
9. `docs/global_environment.md`
10. `docs/ide_generation_prompt.md`

## Pack documentaire attendu
- vision produit et périmètre
- user stories complètes par rôle
- spécifications fonctionnelles détaillées par feature
- spécifications d'interface écran par écran
- MLD détaillé avec tables, champs et relations
- contrat API détaillé
- plan d'implémentation et matrice de couverture
- prompt de génération pour l'IA de l'IDE

## Ce que l'agent doit produire
- `docker-compose.yml`
- `docker-compose.traefik.yml`
- `docker-manager.yml`
- `.env.example`
- `README.md`
- les fichiers applicatifs nécessaires au stack validé
- du contenu applicatif uniquement dans le dossier du projet
- aucune sortie hors workspace

## Contraintes obligatoires
- Tout doit être exécuté dans Docker.
- Ne jamais dépendre d'outils installés sur l'hôte.
- Vérifier l'état runtime avec des commandes comme `docker compose ps`.
- Lancer les commandes applicatives dans le conteneur adéquat avec `docker compose exec`.
- Si le stack n'est pas prêt, ajuster d'abord les fichiers Docker.
- Si une correction client change le stack, il faut réécrire les fichiers `.md` concernés avant de poursuivre le travail.
- Avant de générer ou de modifier `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml` ou `.env.example`, relire ce document en entier.

## Commandes de contrôle attendues
- `docker compose ps`
- `docker compose logs frontend`
- `docker compose exec frontend nginx -v`
- `docker compose exec frontend ls -la /usr/share/nginx/html`

## Exemples d'actions attendues pour un projet HTML / CSS / JavaScript
```bash
docker compose ps
docker compose exec frontend ls -la /usr/share/nginx/html
docker compose exec frontend cat /usr/share/nginx/html/index.html
docker compose exec frontend cat /usr/share/nginx/html/styles.css
docker compose exec frontend cat /usr/share/nginx/html/app.js
```

## Exemples de fichiers à générer
```text
docker-compose.yml
docker-compose.traefik.yml
docker-manager.yml
.env.example
frontend/
  Dockerfile
  nginx.conf
  index.html
  styles.css
  app.js
docs/
  global_environment.md
  stack_decision.md
  architecture.md
  client_updates.md
  user_stories.md
  functional_spec.md
  interface_spec.md
  mld.md
  api_contract.md
  ide_generation_prompt.md
```

{static_examples}

{fullstack_examples}

## Ce que doivent contenir les fichiers Docker
### `docker-compose.yml`
- la définition des services applicatifs
- les variables d'environnement
- les réseaux
- les volumes si nécessaires
- les ports internes exposés

### `docker-compose.traefik.yml`
- les labels `traefik.enable=true`
- les routeurs pour le domaine public
- les ports des services
- `proxy_net` comme réseau partagé
- `websecure` comme entrypoint pour le HTTPS
- `tls.certresolver=myresolver` pour l'émission automatique du certificat
- un exemple concret de règle `Host(...)` avec le domaine réel du projet

### Exemple concret attendu pour `docker-compose.traefik.yml`
```yaml
services:
  frontend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.mon-projet.rule=Host(`mon-projet.it-sefako.com`)
      - traefik.http.routers.mon-projet.entrypoints=websecure
      - traefik.http.routers.mon-projet.tls=true
      - traefik.http.routers.mon-projet.tls.certresolver=myresolver
      - traefik.http.services.mon-projet.loadbalancer.server.port=80
    networks:
      - proxy_net
```

### `docker-manager.yml`
- la description des services publics et privés
- les noms de domaines
- les ports
- les fichiers `.env`
- un exemple lisible qui associe le service public à son domaine

### `.env.example`
- toutes les variables nécessaires au démarrage
- des valeurs d'exemple lisibles
- aucune vraie donnée sensible
- `FRONTEND_DOMAIN`
- `API_DOMAIN` si une API existe
- `IDE_DOMAIN` si l'éditeur web est exposé
- `TZ`

## Exemple de structure Docker attendue
```yaml
services:
  frontend:
    build:
      context: ./frontend
    env_file:
      - .env
    labels:
      - traefik.enable=true
      - traefik.http.routers.mon-projet.rule=Host(`${{FRONTEND_DOMAIN}}`)
      - traefik.http.services.mon-projet.loadbalancer.server.port=80
```

## Exemple de manifeste `docker-manager.yml`
```yaml
version: 1
kind: auto-detected
domains:
  frontend: ${{DOMAIN}}
services:
  frontend:
    public: true
    domain: frontend
    port: 80
```

## Exemple concret attendu pour `docker-compose.yml`
```yaml
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    env_file:
      - .env
    expose:
      - "80"
    restart: unless-stopped
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true
```

## Ce qu'il ne faut pas faire
- inventer un backend si le projet est un simple site HTML / CSS / JavaScript
- utiliser des labels Traefik sans `proxy_net`
- oublier `websecure` sur un déploiement HTTPS
- oublier `tls.certresolver=myresolver`
- laisser les fichiers Docker incomplets et attendre que l'éditeur web devine le reste

## Exemple de contenu attendu dans le code
### `index.html`
- structure de page simple et lisible
- liens vers `styles.css` et `app.js`
- aucun framework JavaScript

### `styles.css`
- variables de couleurs
- layout responsive
- typographie lisible

### `app.js`
- logique métier en JavaScript natif
- lecture et écriture dans `localStorage` si le besoin le demande
- aucune dépendance externe

## Stack détectée
- backend: `none`
- frontend: `{stack.get('frontend')}`
- base de données: `none`
- layout: `static-only`

## Corrections récentes
{client_context.strip()[:1200] or "Aucune correction récente."}

## Rappel déploiement
- Compatible `docker_manager`
- Compatible `traefik_master`
- Réseau partagé `proxy_net`
- Labels Traefik obligatoires
- Domaine cible du type `mon-projet.it-sefako.com`
- `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml` maintenus
- `.env.example` clair et reproductible
"""
    return f"""# Global Environment

## Projet
- Titre: {project_title}
- Project ID: `{project_id}`

## Rôle de ce document
Ce fichier est le contrat d'environnement à suivre par l'agent IA dans VS Code web.
Il doit être lu avant toute modification de fichier, avant toute création de config, et avant toute génération de contenu de déploiement.
Si une consigne utilisateur contredit un ancien document, la consigne la plus récente prime.

## Source de vérité
- `README.md`
- `docs/client_updates.md`
- `docs/stack_decision.md`
- `docs/architecture.md`
- `docs/requirements_matrix.md`
- `docs/user_stories.md`
- `docs/functional_spec.md`
- `docs/interface_spec.md`
- `docs/mld.md`
- `docs/api_contract.md`
- `docs/ide_generation_prompt.md`
- `docs/global_environment.md`

## Ce que l'agent doit produire
- des fichiers de configuration cohérents avec le stack validé
- du contenu applicatif uniquement dans le dossier du projet
- aucune sortie hors workspace
- des fichiers Markdown mis à jour quand une décision change

## Contraintes obligatoires
- Tout doit être exécuté dans Docker.
- Ne jamais dépendre d'outils installés sur l'hôte.
- Vérifier l'état runtime avec des commandes comme `docker compose ps`.
- Lancer les commandes applicatives dans le conteneur adéquat avec `docker compose exec`.
- Si le stack n'est pas prêt, ajuster d'abord les fichiers Docker.
- Si une correction client change le stack, il faut réécrire les fichiers `.md` concernés avant de poursuivre le travail.
- Avant de générer ou de modifier `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml` ou `.env.example`, relire ce document en entier.

## Commandes de contrôle attendues
- `docker compose ps`
- `docker compose exec <service> composer --version`
- `docker compose exec <service> php artisan --version`
- `docker compose exec <service> php -v`

## Exemples d'actions attendues
### Projet backend type Laravel
```bash
docker compose ps
docker compose exec app composer install
docker compose exec app php artisan --version
docker compose exec app php artisan migrate --force
```

### Projet backend type FastAPI
```bash
docker compose ps
docker compose exec backend python -m pip install -r requirements.txt
docker compose exec backend python -m pytest
```

### Projet frontend statique
```bash
docker compose ps
docker compose exec frontend ls -la /usr/share/nginx/html
docker compose exec frontend cat /usr/share/nginx/html/index.html
```

## Exemples de fichiers à générer
```text
backend/
  Dockerfile
  requirements.txt | composer.json
  app/main.py | public/index.php
frontend/
  Dockerfile
  index.html | app/page.tsx
  styles.css | globals.css
  app.js
docs/
  global_environment.md
  stack_decision.md
  architecture.md
  client_updates.md
  user_stories.md
  functional_spec.md
  interface_spec.md
  mld.md
  api_contract.md
  ide_generation_prompt.md
```

{static_examples}

{fullstack_examples}

## Exemple de contenu attendu dans le code
### Si le stack est HTML / CSS / JavaScript
- `index.html` avec structure sémantique claire
- `styles.css` avec variables de couleur et responsive design
- `app.js` en JavaScript natif, sans framework

### Si le stack est FastAPI
- `Dockerfile` Python
- `requirements.txt`
- `app/main.py`
- routes simples, testables, documentées

### Si le stack est Laravel
- `composer.json`
- `public/index.php`
- `routes/api.php`
- contrôleur de résumé ou de santé

## Exemple concret pour Laravel
Quand le projet est en Laravel, les vérifications et opérations doivent ressembler à ceci:

```bash
docker compose ps
docker compose exec app composer install
docker compose exec app php artisan --version
docker compose exec app php artisan migrate --force
```

Remplace `app` par le nom réel du service applicatif si nécessaire.

## Stack détectée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- base de données: `{stack.get('database')}`
- layout: `{ 'monolithique' if stack.get('generation_frontend') == 'monolith' else 'séparé' }`

## Corrections récentes
{client_context.strip()[:1200] or "Aucune correction récente."}

## Rappel déploiement
- Compatible `docker_manager`
- Compatible `traefik_master`
- Réseau partagé `proxy_net`
- Labels Traefik obligatoires
- Domaine cible du type `mon-projet.it-sefako.com`
- `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml` maintenus
- `.env.example` clair et reproductible
"""


async def refresh_project_workspace_documents(
    *,
    project_dir: str,
    project_id: str,
    project_title: str,
    input_text: str,
    deliverables: dict[str, Any],
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    base = Path(project_dir).resolve()
    ensure_within_workspace(base, base)

    recent_notes: list[str] = []
    if db is not None:
        try:
            result = await db.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.project_id == project_id, WorkflowEvent.event_type == "user_message")
                .order_by(WorkflowEvent.sequence.desc())
                .limit(12)
            )
            events = list(reversed(result.scalars().all()))
            for event in events:
                payload = event.payload or {}
                content = (payload.get("content") or payload.get("message") or "").strip()
                if not content:
                    continue
                author = (payload.get("author") or "Utilisateur").strip()
                recent_notes.append(f"- {author}: {content}")
        except Exception:
            recent_notes = []

    validation_answers = deliverables.get("validation_answers")
    if isinstance(validation_answers, list) and validation_answers:
        if recent_notes:
            recent_notes.append("")
        recent_notes.append("Réponses de validation enregistrées:")
        for index, item in enumerate(validation_answers, start=1):
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("id") or f"Question {index}").strip()
            answer = str(item.get("answer") or "").strip()
            if answer:
                recent_notes.append(f"- {index}. {question}: {answer}")

    client_context = "\n".join(recent_notes).strip()
    doc_input_text = input_text.strip()
    if client_context:
        doc_input_text = f"{doc_input_text}\n\n{client_context}"

    stack = detect_application_stack(project_title, doc_input_text, deliverables, extra_context=client_context)
    docs_specs = await _documentation_specs(
        project_title,
        project_id,
        doc_input_text,
        deliverables,
        stack,
        str(base.parent),
        client_context=client_context,
        llm_router=LLMRouter(db) if db is not None else None,
    )
    files = [_write_workspace_file(base, relative_path, content) for relative_path, content in docs_specs]
    _set_workspace_permissions(base)
    return {
        "project_dir": str(base),
        "generated_at": utc_now_iso(),
        "files": files,
        "repo_name": base.name,
        "stack": stack,
        "client_context": client_context,
    }

def _extract_requirement_candidates(project_title: str, input_text: str, deliverables: dict[str, Any]) -> list[str]:
    source = "\n".join([
        project_title or "",
        input_text or "",
        str(deliverables.get("cdc") or ""),
    ])
    candidates: list[str] = []
    for raw_line in source.splitlines():
        line = re.sub(r"^[\s#>*\-0-9.()]+", "", raw_line).strip()
        if len(line) < 18:
            continue
        if line.lower().startswith(("table", "figure", "note")):
            continue
        candidates.append(line[:220])
    if not candidates:
        cleaned = re.sub(r"\s+", " ", source).strip()
        chunks = re.split(r"(?<=[.!?])\s+", cleaned)
        candidates = [chunk[:220] for chunk in chunks if len(chunk) >= 24]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 18:
            break
    return deduped or [f"Livrer une application conforme au brief: {project_title}"]


def _requirements_matrix(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    requirements = _extract_requirement_candidates(project_title, input_text, deliverables)
    rows = [
        "# Matrice de couverture du CDC",
        "",
        "## Méthode",
        "- chaque exigence est reformulée pour pouvoir être vérifiée",
        "- la couverture référence les documents qui portent la vérité métier",
        "- le statut indique si l'exigence est déjà décrite ou reste à préciser",
        "",
        "| # | Exigence | Type | Couverture actuelle | Références | Statut |",
        "|---|---|---|---|---|---|",
    ]
    for index, requirement in enumerate(requirements, 1):
        lowered = requirement.lower()
        refs = ["docs/cdc.md", "docs/stack_decision.md", "docs/global_environment.md"]
        req_type = "métier"
        if any(word in lowered for word in ["api", "backend", "base", "donnée", "donnee", "auth", "crud", "laravel", "fastapi"]):
            refs.extend(["docs/global_environment.md", "docs/architecture.md", "docs/mld.md", "docs/api_contract.md"])
            req_type = "technique"
        if any(word in lowered for word in ["interface", "utilisateur", "page", "mobile", "frontend", "dashboard", "écran", "ecran"]):
            refs.extend(["docs/stack_decision.md", "docs/interface_spec.md", "docs/user_stories.md"])
            req_type = "interface"
        if any(word in lowered for word in ["docker", "déploiement", "deploiement", "traefik", "env"]):
            refs.extend(["docs/global_environment.md", "README.md"])
            req_type = "déploiement"
        coverage = "Tracé dans les documents de cadrage et le guide d'éditeur web. L'implémentation finale est déléguée à l'éditeur web."
        status = "couvert" if len(refs) > 2 else "à préciser"
        rows.append(f"| {index} | {requirement.replace('|', '/')} | {req_type} | {coverage} | {', '.join(dict.fromkeys(refs))} | {status} |")
    rows.extend([
        "",
        "## Stack reconnue",
        f"- backend demandé: `{stack.get('backend')}`",
        f"- frontend demandé: `{stack.get('frontend')}`",
        f"- backend traité par: `employés`",
        f"- frontend traité par: `employés`",
        f"- backend confié à: `éditeur web`",
        f"- frontend confié à: `éditeur web`",
        "",
        "## Lecture attendue",
        "- si une exigence est en `à préciser`, elle doit être complétée dans un autre document avant la génération finale",
        "- toute exigence de type interface doit aussi exister dans les specs d'interface",
        "- toute exigence de type technique doit aussi exister dans le MLD, le contrat API ou l'architecture",
        "- toute exigence de type déploiement doit aussi exister dans le contrat d'environnement",
        "",
        "Cette matrice sert de contrat de vérification pour le cadrage et le guide d'éditeur web.",
    ])
    return "\n".join(rows) + "\n"

def _delivery_review(project_title: str, stack: dict[str, str], validation: dict[str, Any]) -> str:
    missing = validation.get("missing_files") or []
    checks = validation.get("checks") or []
    status = "livrable" if validation.get("success") else "à corriger"
    lines = [
        "# Revue de livraison",
        "",
        f"Projet: {project_title}",
        f"Statut: **{status}**",
        "",
        "## Résultat des contrôles",
    ]
    for check in checks:
        label = check.get("label", "Contrôle")
        ok = "OK" if check.get("ok") else "KO"
        lines.append(f"- {ok} - {label}")
    if missing:
        lines.extend(["", "## Fichiers manquants", *[f"- `{item}`" for item in missing]])
    lines.extend([
        "",
        "## Conclusion",
        "Le repo reste confiné au dossier projet et contient les fichiers nécessaires à une reprise par l'admin ou par les employés IA.",
        "Les tests système profonds restent à lancer dans l'environnement cible quand les dépendances du stack sont installées.",
    ])
    return "\n".join(lines) + "\n"


def validate_workspace_delivery(
    *,
    project_dir: str,
    project_id: str,
    project_title: str,
    input_text: str,
    deliverables: dict[str, Any],
) -> dict[str, Any]:
    base = Path(project_dir).resolve()
    ensure_within_workspace(base, base)
    stack = detect_application_stack(project_title, input_text, deliverables)
    required_files = [
        "README.md",
        "docs/client_updates.md",
        "docs/cdc.md",
        "docs/mcd.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/notes_synthese.md",
        "docs/stack_decision.md",
        "docs/global_environment.md",
        "docs/implementation_plan.md",
        "docs/requirements_matrix.md",
        "docs/user_stories.md",
        "docs/functional_spec.md",
        "docs/interface_spec.md",
        "docs/mld.md",
        "docs/api_contract.md",
        "docs/ide_generation_prompt.md",
        ".aia/workspace-policy.json",
    ]
    missing_files = [relative for relative in required_files if not (base / relative).exists()]

    readme = (base / "README.md").read_text(errors="ignore") if (base / "README.md").exists() else ""
    stack_decision = (base / "docs/stack_decision.md").read_text(errors="ignore") if (base / "docs/stack_decision.md").exists() else ""

    checks = [
        {"key": "required_files", "label": "Documents minimum du repo présents", "ok": not missing_files},
        {"key": "readme_mentions_editor", "label": "README documente le passage de relais à l'éditeur", "ok": "éditeur" in readme.lower() and "Markdown" in readme},
        {"key": "stack_decision_present", "label": "Décision de stack documentée", "ok": "Décision de stack" in stack_decision and stack.get("backend") in stack_decision},
        {"key": "workspace_guard", "label": "Politique de confinement présente", "ok": (base / ".aia/workspace-policy.json").exists()},
    ]
    success = all(check["ok"] for check in checks)
    matrix = _requirements_matrix(project_title, input_text, deliverables, stack)
    validation = {
        "success": success,
        "project_id": project_id,
        "project_title": project_title,
        "stack": stack,
        "checks": checks,
        "missing_files": missing_files,
        "validated_at": utc_now_iso(),
    }
    _write_workspace_file(base, "docs/requirements_matrix.md", matrix)
    _write_workspace_file(base, "docs/test_report.md", "# Rapport de validation\n\n```json\n" + json.dumps(validation, ensure_ascii=True, indent=2) + "\n```\n")
    _write_workspace_file(base, "docs/delivery_review.md", _delivery_review(project_title, stack, validation))
    _write_workspace_file(base, "manifest.aia.json", json.dumps({
        "project_id": project_id,
        "project_title": project_title,
        "workspace": str(base),
        "docker_manager_compatible": True,
        "delivery_status": "ready" if success else "needs_fix",
        "validated_at": validation["validated_at"],
        "stack": stack,
        "checks": checks,
        "missing_files": missing_files,
    }, ensure_ascii=True, indent=2))
    validation["files"] = sorted([str(item.relative_to(base)) for item in base.rglob("*") if item.is_file()])
    return validation

def _workspace_policy(project_dir: str) -> str:
    return json.dumps({
        "allowed_root": project_dir,
        "deny_patterns": ["../", "/opt/docker_manager", "/opt/traefik_master"],
        "note": "Toutes les écritures doivent rester strictement confinées au dossier projet."
    }, ensure_ascii=True, indent=2)


def _deploy_readme(slug: str, workspace_dir: str) -> str:
    return f"""# Déploiement via docker_manager

Ce repo a été préparé pour rester autonome et compatible avec un déploiement Git via docker_manager.

## Fichiers clés
- `.env.example`
- `docker-compose.yml`
- `docker-compose.traefik.yml`

## Garde-fou
- dossier autorisé: `{workspace_dir}`
- aucun accès ni modification de `docker_manager`, `traefik_master` ou d'un autre projet

## Convention
- frontend: `{slug}.example.com`
- api: `api-{slug}.example.com`
"""


def _implementation_plan(project_title: str, input_text: str, deliverables: dict[str, Any]) -> str:
    return f"""# Plan d'implémentation

## Projet
- Titre: {project_title}
- Brief: {input_text.strip()[:1200]}

## Base de travail
### CDC
{str(deliverables.get('cdc') or '').strip()[:2400]}

### Architecture
{str(deliverables.get('architecture') or '').strip()[:2400]}

### Roadmap
{str(deliverables.get('roadmap') or '').strip()[:2400]}

## Objectif de cette phase
- produire un repo autonome
- rester compatible avec docker_manager
- rester strictement confiné au dossier projet
"""


def _user_stories(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    brief = _markdown_excerpt(input_text, 1400) or "À compléter à partir du brief."
    cdc = _markdown_excerpt(str(deliverables.get("cdc") or ""), 1200) or "CDC à préciser."
    roles = [
        ("visiteur", "consulter la proposition de valeur et comprendre l'objectif du produit"),
        ("utilisateur", "accomplir les tâches principales dans l'application"),
        ("administrateur", "superviser les données, les paramètres et les livraisons"),
        ("éditeur web", "implémenter le produit fidèlement à partir des documents"),
    ]
    role_rows = "\n".join(
        f"| {role} | {goal} | haute | relié aux écrans et aux règles métier |"
        for role, goal in roles
    )
    return f"""# User Stories

## Projet
- Titre: {project_title}
- Stack: backend `{stack.get('backend')}`, frontend `{stack.get('frontend')}`, base `{stack.get('database')}`

## Vision
{brief}

## Extrait du CDC
{cdc}

## Tableau de synthèse
| Rôle | Objectif | Priorité | Dépendances |
|---|---|---|---|
{role_rows}

## Stories détaillées
### 1. Visiteur
#### Story
En tant que visiteur, je veux comprendre rapidement ce que fait l'application afin de décider si elle répond à mon besoin.
#### Scénario nominal
- j'arrive sur l'application
- je vois le titre, la proposition de valeur et les principaux bénéfices
- je comprends les actions possibles
#### Variantes
- si l'application demande une connexion, j'accède d'abord à l'écran d'authentification
- si le contenu est vide, un état de démarrage clair s'affiche
#### Critères d'acceptation
- la proposition de valeur est visible en moins de 5 secondes
- le texte d'accueil résume le périmètre
- aucun élément mobile n'est présenté si le projet est desktop/web

### 2. Utilisateur
#### Story
En tant qu'utilisateur, je veux exécuter les fonctionnalités principales afin d'accomplir ma tâche métier de bout en bout.
#### Scénario nominal
- j'ouvre l'écran principal
- j'accède aux listes, filtres, formulaires ou détails pertinents
- je crée ou modifie une donnée selon mes droits
#### Variantes
- si une validation échoue, je vois le message exact sur le champ concerné
- si une action est impossible, je comprends la raison et la correction attendue
#### Critères d'acceptation
- chaque action métier a un écran ou composant dédié
- les formulaires bloquent les saisies invalides
- les états loading / empty / error sont documentés

### 3. Administrateur
#### Story
En tant qu'administrateur, je veux superviser les données, la configuration et les utilisateurs afin de maintenir le bon fonctionnement du système.
#### Scénario nominal
- je consulte les données clés
- j'accède aux paramètres et aux journaux si le besoin existe
- je peux vérifier l'état des services ou des traitements
#### Critères d'acceptation
- les accès sensibles sont documentés
- les actions administratives sont distinctes des actions utilisateur
- les permissions sont explicites

### 4. Éditeur web
#### Story
En tant qu'éditeur web, je veux disposer d'un cadrage exhaustif afin de générer l'application finale sans improvisation.
#### Critères d'acceptation
- tous les écrans sont reliés à une story
- toutes les règles métier sont écrites
- la structure des données est décrite
- le contrat API et le déploiement sont couverts

## Critères transverses
- chaque story est reliée à un écran, une règle métier et au moins un critère d'acceptation
- aucune fonctionnalité mobile ne doit être inventée si elle n'est pas validée
- le stack validé doit être respecté
- les user stories doivent pouvoir être transformées directement en tickets de développement
"""


def _functional_spec(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    cdc = _markdown_excerpt(str(deliverables.get("cdc") or ""), 1800) or "CDC à préciser."
    architecture = _markdown_excerpt(str(deliverables.get("architecture") or ""), 1800) or "Architecture à préciser."
    roadmap = _markdown_excerpt(str(deliverables.get("roadmap") or ""), 1200) or "Roadmap à préciser."
    return f"""# Spécifications fonctionnelles

## Projet
- Titre: {project_title}

## Périmètre
{cdc}

## Contexte de lecture
{_markdown_excerpt(input_text, 1600) or "Contexte à préciser."}

## Fonctionnalités détaillées
### F1. Accès et entrée dans l'application
- décrire l'écran d'entrée
- préciser la navigation initiale
- définir les conditions d'accès

### F2. Consultation des données
- lister les vues principales
- définir les filtres, tris et recherches
- préciser les états vide et chargement

### F3. Création et modification
- lister les champs à saisir
- définir les validations de chaque champ
- préciser les messages d'erreur

### F4. Suppression, archivage ou clôture
- documenter si l'action existe
- préciser les confirmations nécessaires
- définir l'impact sur les données liées

### F5. Tableaux de bord et indicateurs
- définir les KPIs ou agrégats visibles
- préciser la fréquence d'actualisation
- documenter les sources de calcul

## Règles métier
- respecter le besoin décrit dans le CDC
- couvrir les cas limites et les erreurs utilisateur
- conserver la cohérence avec le stack et l'architecture
- toute règle doit être formulée de manière testable
- chaque règle doit préciser l'entrée, la condition et la conséquence

## Cas d'erreur et traitements
| Situation | Réponse attendue |
|---|---|
| champ obligatoire manquant | message de validation explicite |
| ressource introuvable | message contextualisé |
| action interdite | refus clair avec cause |
| erreur réseau ou API | message de reprise et tentative de nouvelle action |

## Architecture de référence
{architecture}

## Roadmap fonctionnelle
{roadmap}

## Stack détectée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- base de données: `{stack.get('database')}`
"""


def _interface_spec(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    screens = [
        "Accueil ou tableau de bord",
        "Liste des éléments métier",
        "Détail d'un élément",
        "Formulaire de création",
        "Formulaire d'édition",
        "Écran de confirmation / succès",
        "Écran d'erreur / accès refusé",
    ]
    screen_rows = "\n".join(
        [
            f"| {screens[0]} | orienter l'utilisateur | hero, résumé, actions rapides | vide, chargé |",
            f"| {screens[1]} | parcourir les données | tableau, cartes, filtres, recherche | loading, empty, error |",
            f"| {screens[2]} | consulter une ressource | titre, attributs, historique, actions | lecture seule |",
            f"| {screens[3]} | créer une ressource | champs, aide contextuelle, validation | initial, invalide, soumis |",
            f"| {screens[4]} | modifier une ressource | champs préremplis, validation | initial, invalide, soumis |",
            f"| {screens[5]} | rassurer l'utilisateur | message, retour, CTA | success |",
            f"| {screens[6]} | expliquer le problème | message, cause, action de reprise | error, forbidden |",
        ]
    )
    return f"""# Spécifications d'interface

## Projet
- Titre: {project_title}

## Intentions UI
- interface claire, cohérente et fidèle au besoin
- hiérarchie visuelle nette
- composants réutilisables
- feedback utilisateur explicite
- design responsive
- accessibilité suffisante pour un usage standard
- états visuels distincts pour loading, empty, success, warning et error

## Écrans
| Écran | Rôle | Composants principaux | États |
|---|---|---|---|
{screen_rows}

## Comportements
- gérer les états loading, empty, success et error
- valider les champs avant envoi
- afficher des messages clairs après action
- préserver la lisibilité sur petits et grands écrans
- maintenir les interactions simples et prévisibles

## Composants réutilisables
- barre de navigation
- carte récapitulative
- tableau ou grille de données
- modal de confirmation
- toast ou alerte système
- champ de formulaire avec erreur

## Parcours utilisateur
- arrivée sur l'écran principal
- exploration des données ou des fonctionnalités
- action principale
- confirmation ou correction
- retour à l'écran de synthèse

## Stack détectée
- frontend: `{stack.get('frontend')}`
- mobile: `{stack.get('mobile')}`
"""


def _mld(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    source = _markdown_excerpt(input_text, 1200) or "À préciser."
    return f"""# MLD détaillé

## Projet
- Titre: {project_title}

## Source métier
- {source}

## Tables attendues
| Table | Rôle | Champs principaux | Relations |
|---|---|---|---|
| `users` ou équivalent | gérer les identités | id, nom, email, rôle, statut | reliée aux ressources métier |
| table métier principale | stocker le cœur fonctionnel | id, libellé, statut, dates, auteur | dépend du besoin |
| tables de liaison | gérer les relations n-n | ids de référence, ordre, statut | reliant plusieurs entités |
| `audit_logs` ou équivalent | tracer les changements | id, action, cible, date, utilisateur | traçabilité |
| tables techniques | configuration ou cache | clé, valeur, timestamps | système |

## Contraintes
- clés primaires explicites
- clés étrangères cohérentes
- index sur les champs de recherche
- types alignés avec PostgreSQL
- nullabilité documentée
- valeurs par défaut explicites
- unicité sur les colonnes métier nécessaires

## Règles de modélisation
- normaliser les données utiles
- conserver la traçabilité des relations
- documenter les champs obligatoires et optionnels
- séparer clairement les données de référence, métier et techniques

## Détail attendu par table
Pour chaque table, décrire:
- nom
- objectif
- colonnes
- type de donnée
- obligatoire ou non
- valeur par défaut
- clé primaire
- clés étrangères
- index
- contraintes d'unicité

## Exemple de relations
- un utilisateur peut créer plusieurs éléments métier
- un élément métier peut avoir plusieurs enfants ou lignes de détail
- plusieurs éléments peuvent partager la même catégorie ou référence

## Rappel d'implémentation
- le MLD doit être directement traduisible en migration SQL
- chaque table doit pouvoir être reliée aux écrans et à l'API
"""


def _api_contract(project_title: str, input_text: str, deliverables: dict[str, Any], stack: dict[str, str]) -> str:
    return f"""# Contrat API détaillé

## Projet
- Titre: {project_title}

## Endpoints attendus
- `GET /health`
- `GET /api/...`
- `POST /api/...`
- `PUT /api/...`
- `DELETE /api/...`

## Spécifications
- décrire les payloads d'entrée et de sortie
- lister les codes d'erreur
- fournir des exemples de requêtes et réponses
- documenter l'authentification si elle existe
- préciser le comportement des routes protégées
- préciser la pagination, le tri et le filtrage si nécessaires

## Format attendu par endpoint
| Élément | Description |
|---|---|
| méthode | GET, POST, PUT, PATCH, DELETE |
| chemin | URL exacte |
| entrée | paramètres, query, body |
| sortie | structure JSON |
| erreurs | 400, 401, 403, 404, 409, 422, 500 |
| exemples | requête et réponse |

## Exemples de contrat
### `GET /health`
- réponse: `{"status":"ok"}`

### `GET /api/...`
- usage: lecture de données
- réponse: liste paginée ou objet détaillé

### `POST /api/...`
- usage: création
- validation: champs obligatoires
- réponse: ressource créée ou erreur de validation

### `PUT /api/...`
- usage: remplacement ou mise à jour complète

### `DELETE /api/...`
- usage: suppression ou archivage
- confirmation: si l'action est sensible

## Stack
- backend: `{stack.get('backend')}`
- base de données: `{stack.get('database')}`
"""


def _ide_generation_prompt(
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    workspace_root: str,
    client_context: str = "",
) -> str:
    return f"""# Prompt de génération pour l'IA de l'IDE

Ce fichier est le prompt prêt à copier-coller dans l'IDE pour générer l'application finale à partir du cadrage produit par les employés.

## Chaîne de production
```mermaid
flowchart LR
    subgraph EMP[Employés]
        E1[Stratégie]
        E2[UX]
        E3[Ingénierie]
        E4[DevOps]
    end
    subgraph DOC[Pack documentaire]
        D1[Docs Markdown]
        D2[README + specs]
        D3[Architecture + MLD]
    end
    subgraph ORC[Orchestrateur]
        O1[Relit]
        O2[Valide]
        O3[Relance si besoin]
    end
    subgraph IDE[IA de l'IDE]
        I1[Lit tous les docs]
        I2[Genere l'app]
        I3[Respecte le stack]
    end
    F1[Application finale]

    E1 --> D1
    E2 --> D2
    E3 --> D3
    E4 --> D2
    D1 --> O1
    D2 --> O1
    D3 --> O1
    O1 --> O2 --> O3 --> I1
    I1 --> I2 --> I3 --> F1
```

```text
Tu es l'IA de l'IDE chargée de générer fidèlement l'application finale du projet "{project_title}".

Contexte général:
- Project ID: {project_id}
- Racine du workspace: {workspace_root}
- Brief initial: {_markdown_excerpt(input_text, 2200)}
- Corrections récentes: {_markdown_excerpt(client_context, 1600) or "Aucune correction récente."}

Stack validée:
- backend: {stack.get('backend')}
- frontend: {stack.get('frontend')}
- mobile: {stack.get('mobile')}
- base de données: {stack.get('database')}
- langages: {stack.get('languages')}

Source de vérité:
- lis intégralement tous les fichiers `.md` du dossier `docs/`
- respecte en priorité `README.md`, `docs/stack_decision.md`, `docs/architecture.md`, `docs/global_environment.md`, `docs/implementation_plan.md` et `docs/requirements_matrix.md`
- prends aussi comme référence `docs/user_stories.md`, `docs/functional_spec.md`, `docs/interface_spec.md`, `docs/mld.md` et `docs/api_contract.md`
- si un document manque, crée-le avant de coder plutôt que d'inventer

Livrables attendus:
- un socle applicatif complet et fidèle au besoin
- des écrans et interfaces cohérents avec les descriptions fonctionnelles
- les règles métier, validations, états d'erreur et parcours utilisateur
- les MCD / MLD / dictionnaire de données si nécessaire
- les contrats API, modèles, services, routes et intégrations
- le déploiement Docker / Traefik / .env.example si le projet l'exige

Ce que tu dois couvrir:
- vision produit et périmètre
- user stories
- features et cas d'usage
- description détaillée des interfaces
- flux de navigation et écrans
- MCD et MLD
- dictionnaire de données
- contrats API
- règles métier
- critères d'acceptation
- exigences non fonctionnelles
- déploiement et environnement

Contraintes absolues:
- ne change pas le stack validé
- ne réintroduis pas d'application mobile si elle est exclue
- n'invente pas de logique non documentée
- garde l'architecture lisible, maintenable et alignée sur les documents
- si une ambiguïté subsiste, privilégie la solution la plus fidèle au CDC et à la décision de stack

Sortie attendue:
- génère ou mets à jour le code et les fichiers nécessaires dans le dépôt
- fournis des fichiers complets, sans placeholders
- respecte exactement les conventions de nommage, les chemins et les livrables décrits dans les documents
- termine en laissant un projet runnable et fidèle au cadrage
```
"""


def _readme(
    project_title: str,
    project_id: str,
    deliverables: dict[str, Any],
    workspace_root: str,
    stack: dict[str, str],
    client_context: str = "",
) -> str:
    backend_note = (
        "Aucun backend n'est requis: le projet reste en HTML / CSS / JavaScript statique."
        if stack.get("generation_backend") == "none"
        else "Le backend éventuel est documenté dans `docs/stack_decision.md` et `docs/global_environment.md`."
    )
    return f"""# {project_title}

Project ID: `{project_id}`

Ce workspace est un espace de cadrage documentaire pour AIA Studio.
Les employés du studio produisent les documents Markdown, puis l'éditeur web prend le relais pour finaliser l'implémentation manuelle.

## Chaîne de production
```mermaid
flowchart LR
    subgraph EMP[Employés]
        E1[Stratégie]
        E2[UX]
        E3[Ingénierie]
        E4[DevOps]
    end
    subgraph DOC[Pack documentaire]
        D1[Docs Markdown]
        D2[README + specs]
        D3[Architecture + MLD]
    end
    subgraph ORC[Orchestrateur]
        O1[Relit]
        O2[Valide]
        O3[Relance si besoin]
    end
    subgraph IDE[IA de l'IDE]
        I1[Lit tous les docs]
        I2[Genere l'app]
        I3[Respecte le stack]
    end
    F1[Application finale]

    E1 --> D1
    E2 --> D2
    E3 --> D3
    E4 --> D2
    D1 --> O1
    D2 --> O1
    D3 --> O1
    O1 --> O2 --> O3 --> I1
    I1 --> I2 --> I3 --> F1
```

## Stack détectée
- backend demandé: `{stack.get('backend')}`
- frontend demandé: `{stack.get('frontend')}`
- mobile détecté: `{stack.get('mobile')}`
- base de données détectée: `{stack.get('database')}`
- langages détectés: `{stack.get('languages')}`

## Corrections récentes
{client_context.strip()[:1200] or "Aucune correction récente."}

## Décision de livraison
- implémentation générée par les employés: `non`
- implémentation gérée par l'éditeur web: `oui`
- structure du dépôt décidée par le couple cadrage + éditeur web
- {backend_note}

## Règles de travail
- racine de génération: `{workspace_root}`
- les employés n'écrivent que des documents Markdown et les garde-fous internes
- l'éditeur web reçoit ensuite le contexte et finalise le dépôt exécutable
- aucun accès direct à `docker_manager`, `traefik_master` ou aux autres projets

"""


async def initialize_project_workspace(
    *,
    root_path: str,
    project_id: str,
    project_title: str,
    deliverables: dict[str, Any],
    llm_router: LLMRouter | None = None,
) -> dict[str, Any]:
    project_dir = get_project_workspace_dir(root_path, project_id, project_title)
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_within_workspace(project_dir, project_dir)

    input_text = str(deliverables.get('input_text') or '')
    stack = detect_application_stack(project_title, input_text, deliverables)
    docs_specs = await _documentation_specs(
        project_title,
        project_id,
        input_text,
        deliverables,
        stack,
        root_path,
        llm_router=llm_router,
    )

    files = [
        _write_workspace_file(project_dir, relative_path, content)
        for relative_path, content in docs_specs
    ]

    _set_workspace_permissions(project_dir)

    return {
        'project_dir': str(project_dir.resolve()),
        'root_path': sanitize_workspace_root(root_path),
        'generated_at': utc_now_iso(),
        'files': files,
        'repo_name': project_dir.name,
    }


async def generate_application_foundation(
    *,
    project_dir: str,
    project_id: str,
    project_title: str,
    input_text: str,
    deliverables: dict[str, Any],
    llm_router: LLMRouter | None = None,
) -> dict[str, Any]:
    base = Path(project_dir).resolve()
    ensure_within_workspace(base, base)
    stack = detect_application_stack(project_title, input_text, deliverables)
    docs_specs = await _documentation_specs(
        project_title,
        project_id,
        input_text,
        deliverables,
        stack,
        str(base.parent),
        llm_router=llm_router,
    )
    files = []
    for relative_path, content in docs_specs:
        files.append(_write_workspace_file(base, relative_path, content))
    _set_workspace_permissions(base)
    return {
        'project_dir': str(base),
        'generated_at': utc_now_iso(),
        'files': files,
        'repo_name': base.name,
    }
