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
from app.core.llm_router import LLMRouter

WORKSPACE_ROOT_PATH_KEY = "workspace_root_path"
WORKSPACE_REQUIRE_APPROVAL_KEY = "workspace_require_technical_approval"
DEFAULT_WORKSPACE_ROOT = "/projects"
IMPLEMENTATION_PIPELINE_KEY = "implementation_pipeline"
IMPLEMENTATION_WORKSPACE_KEY = "implementation_workspace"

PIPELINE_PHASES = [
    ("admin_approval", "Validation admin"),
    ("technical_design", "Conception technique"),
    ("documentation_pack", "Pack documentaire"),
    ("openhands_bootstrap", "Handoff OpenHands"),
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
        project_dir.chmod(0o775)
    except Exception:
        pass
    for path in project_dir.rglob("*"):
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


def detect_application_stack(project_title: str, input_text: str, deliverables: dict[str, Any]) -> dict[str, str]:
    source = "\n".join([
        project_title or "",
        input_text or "",
        str(deliverables.get("cdc") or ""),
        str(deliverables.get("architecture") or ""),
        str(deliverables.get("roadmap") or ""),
        str(deliverables.get("notes_synthese") or ""),
    ]).lower()

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


def _backend_dockerfile() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""


def _backend_requirements() -> str:
    return """fastapi==0.115.0
uvicorn[standard]==0.30.6
psycopg[binary]==3.2.1
pydantic==2.9.2
"""


def _backend_main_py(project_title: str, deliverables: dict[str, Any]) -> str:
    summary = json.dumps({
        "title": project_title,
        "cdc": str(deliverables.get("cdc") or "")[:1200],
        "architecture": str(deliverables.get("architecture") or "")[:1200],
        "roadmap": str(deliverables.get("roadmap") or "")[:1200],
    }, ensure_ascii=True, indent=2)
    return f"""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title={project_title!r})
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

PROJECT_SUMMARY = {summary}

@app.get('/health')
async def health():
    return {{'status': 'ok'}}

@app.get('/api/project-summary')
async def project_summary():
    return PROJECT_SUMMARY
"""


def _frontend_dockerfile() -> str:
    return """FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY app.js /usr/share/nginx/html/app.js
COPY styles.css /usr/share/nginx/html/styles.css
"""


def _frontend_nginx_conf() -> str:
    return """server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  location / {
    try_files $uri /index.html;
  }
}
"""


def _frontend_index_html(title: str) -> str:
    safe_title = title.replace("<", "").replace(">", "")
    return f"""<!doctype html>
<html lang="fr">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <main class="shell">
      <header>
        <p class="eyebrow">AIA Studio</p>
        <h1>{safe_title}</h1>
        <p id="summary">Chargement du brief...</p>
      </header>
      <section class="card">
        <h2>Socle généré</h2>
        <ul>
          <li>Backend FastAPI</li>
          <li>Frontend statique Nginx</li>
          <li>Docker Compose + Traefik</li>
          <li>Compatible déploiement via docker_manager</li>
        </ul>
      </section>
    </main>
    <script src="/app.js"></script>
  </body>
</html>
"""


def _frontend_app_js() -> str:
    return """async function boot() {
  const summary = document.getElementById('summary');
  try {
    const response = await fetch('/api/project-summary');
    if (!response.ok) throw new Error('Erreur API');
    const data = await response.json();
    summary.textContent = data.cdc ? data.cdc.slice(0, 220) + '…' : 'Le brief est chargé.';
  } catch (error) {
    summary.textContent = 'Socle applicatif généré. Connectez le frontend au backend final selon l’architecture validée.';
  }
}
boot();
"""


def _frontend_styles() -> str:
    return """body { margin: 0; font-family: Inter, system-ui, sans-serif; background: #0b0d12; color: #f5f7fb; }
.shell { max-width: 920px; margin: 0 auto; padding: 64px 24px; }
.eyebrow { letter-spacing: 0.24em; text-transform: uppercase; font-size: 12px; color: #8b5cf6; }
h1 { font-size: clamp(2rem, 4vw, 3.5rem); margin-bottom: 12px; }
.card { margin-top: 24px; padding: 24px; border-radius: 24px; border: 1px solid rgba(139,92,246,.25); background: rgba(17,21,31,.82); }
ul { line-height: 1.8; }
"""


def _laravel_backend_dockerfile() -> str:
    return """FROM php:8.3-cli
WORKDIR /app
COPY . /app
CMD ["php", "-S", "0.0.0.0:8000", "-t", "public"]
"""


def _laravel_composer_json(project_title: str) -> str:
    return json.dumps({
        "name": slugify_project_title(project_title),
        "type": "project",
        "description": f"Socle applicatif oriente Laravel pour {project_title}",
        "require": {
            "php": "^8.2"
        },
        "autoload": {
            "psr-4": {
                "App\\": "app/"
            }
        }
    }, ensure_ascii=False, indent=2)


def _laravel_public_index(project_title: str) -> str:
    safe_title = project_title.replace("<", "").replace(">", "")
    return f"""<?php
header('Content-Type: text/html; charset=utf-8');
?><!doctype html>
<html lang="fr">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; background: #0b0d12; color: #f5f7fb; padding: 48px; }}
      .card {{ max-width: 900px; margin: 0 auto; padding: 24px; border-radius: 24px; border: 1px solid rgba(139,92,246,.3); background: rgba(17,21,31,.82); }}
    </style>
  </head>
  <body>
    <main class="card">
      <p>Socle backend PHP / Laravel prêt.</p>
      <h1>{safe_title}</h1>
      <p>Connecte maintenant les vraies routes Laravel, les contrôleurs, Eloquent et la configuration base de données selon les livrables validés.</p>
    </main>
  </body>
</html>
"""


def _laravel_routes_api() -> str:
    return r"""<?php

use App\Http\Controllers\ProjectSummaryController;

return [
    'GET /health' => [ProjectSummaryController::class, 'health'],
    'GET /api/project-summary' => [ProjectSummaryController::class, 'summary'],
];
"""


def _laravel_summary_controller(project_title: str, deliverables: dict[str, Any]) -> str:
    summary = json.dumps({
        "title": project_title,
        "cdc": str(deliverables.get("cdc") or "")[:1200],
        "architecture": str(deliverables.get("architecture") or "")[:1200],
        "roadmap": str(deliverables.get("roadmap") or "")[:1200],
    }, ensure_ascii=False, indent=2)
    return rf"""<?php

namespace App\Http\Controllers;

class ProjectSummaryController
{{
    private const PROJECT_SUMMARY = <<<'JSON'
{summary}
JSON;

    public function health(): array
    {{
        return ['status' => 'ok'];
    }}

    public function summary(): array
    {{
        return json_decode(self::PROJECT_SUMMARY, true) ?: [];
    }}
}}
"""


def _laravel_monolith_routes_web() -> str:
    return """<?php

use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('home');
});

Route::get('/health', function () {
    return response()->json(['status' => 'ok']);
});
"""


def _laravel_home_blade(project_title: str, deliverables: dict[str, Any]) -> str:
    safe_title = project_title.replace("<", "").replace(">", "")
    summary = json.dumps({
        'title': project_title,
        'cdc': str(deliverables.get('cdc') or '')[:1200],
        'architecture': str(deliverables.get('architecture') or '')[:1200],
        'roadmap': str(deliverables.get('roadmap') or '')[:1200],
    }, ensure_ascii=False, indent=2)
    return f"""<!doctype html>
<html lang="fr">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      :root {{ color-scheme: dark; }}
      body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: radial-gradient(circle at top, #1b1235, #090a0f 55%); color: #f5f7fb; }}
      .shell {{ max-width: 960px; margin: 0 auto; padding: 64px 24px; }}
      .eyebrow {{ letter-spacing: .24em; text-transform: uppercase; font-size: 12px; color: #a78bfa; }}
      h1 {{ font-size: clamp(2rem, 4vw, 3.5rem); margin-bottom: 16px; }}
      .card {{ margin-top: 24px; padding: 24px; border-radius: 24px; border: 1px solid rgba(167,139,250,.25); background: rgba(17,21,31,.82); backdrop-filter: blur(16px); }}
      pre {{ white-space: pre-wrap; word-break: break-word; font: inherit; color: rgba(245,247,251,.78); }}
    </style>
  </head>
  <body>
    <main class="shell">
      <p class="eyebrow">AIA Studio</p>
      <h1>{safe_title}</h1>
      <p>Socle Laravel monolithique prêt, avec Blade et SQLite à la racine du projet.</p>
      <section class="card">
        <h2>Livrables de départ</h2>
        <pre>{summary}</pre>
      </section>
    </main>
  </body>
</html>
"""


def _laravel_app_css() -> str:
    return """body { margin: 0; }
"""


def _documentation_specs(
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    workspace_root: str,
) -> list[tuple[str, str]]:
    slug = slugify_project_title(project_title)
    return [
        ("README.md", _readme(project_title, project_id, deliverables, workspace_root, stack)),
        ("docs/cdc.md", str(deliverables.get("cdc") or "").strip() or "# CDC\n"),
        ("docs/mcd.md", str(deliverables.get("mcd") or "").strip() or "# MCD\n"),
        ("docs/architecture.md", str(deliverables.get("architecture") or "").strip() or "# Architecture\n"),
        ("docs/roadmap.md", str(deliverables.get("roadmap") or "").strip() or "# Roadmap\n"),
        ("docs/notes_synthese.md", str(deliverables.get("notes_synthese") or "").strip() or "# Notes de synthese\n"),
        ("docs/stack_decision.md", _stack_decision(project_title, input_text, stack)),
        ("docs/global_environment.md", _global_environment(project_title, project_id, stack)),
        ("docs/implementation_plan.md", _implementation_plan(project_title, input_text, deliverables)),
        ("docs/requirements_matrix.md", _requirements_matrix(project_title, input_text, deliverables, stack)),
        ("docs/openhands_handoff.md", _openhands_handoff(project_title, project_id, input_text, deliverables, stack)),
        (".aia/workspace-policy.json", _workspace_policy(str(Path(workspace_root).resolve() / f"{slug}_{project_id}"))),
    ]


def _stack_decision(project_title: str, input_text: str, stack: dict[str, str]) -> str:
    layout = "monolithique" if stack.get("generation_frontend") == "monolith" else "séparé"
    frontend_decision = (
        "Aucun dossier `frontend/` n'est requis par les agents."
        if layout == "monolithique"
        else "OpenHands décidera de la présence d'un dossier `frontend/` et le créera uniquement si le stack le justifie."
    )
    backend_decision = (
        "Aucun dossier `backend/` n'est requis par les agents."
        if layout == "monolithique"
        else "OpenHands décidera de la présence d'un dossier `backend/` et le créera uniquement si le stack le justifie."
    )
    return f"""# Décision de stack

## Projet
- Titre: {project_title}

## Brief de départ
{input_text.strip()[:1800]}

## Stack détectée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- mobile: `{stack.get('mobile')}`
- base de données: `{stack.get('database')}`
- langages: `{stack.get('languages')}`

## Décision de structure
- layout retenu: `{layout}`
- génération source par les agents: `non`
- génération source par OpenHands: `oui`

## Conséquence sur le dépôt
- {frontend_decision}
- {backend_decision}

## Règle de pilotage
Les agents du studio produisent uniquement les documents de cadrage.
OpenHands prend ensuite la main pour créer la structure de code source la plus adaptée au stack validé.
"""


def _global_environment(project_title: str, project_id: str, stack: dict[str, str]) -> str:
    return f"""# Global Environment

## Projet
- Titre: {project_title}
- Project ID: `{project_id}`

## Rôle de ce document
Ce fichier sert de contrat d'environnement global pour OpenHands.
Il doit être lu avant toute modification de code.

## Contraintes obligatoires
- Tout doit être exécuté dans Docker.
- Ne jamais dépendre d'outils installés sur l'hôte.
- Vérifier l'état runtime avec des commandes comme `docker compose ps`.
- Lancer les commandes applicatives dans le conteneur adéquat avec `docker compose exec`.
- Si le stack n'est pas prêt, ajuster d'abord les fichiers Docker.

## Commandes de contrôle attendues
- `docker compose ps`
- `docker compose exec <service> composer --version`
- `docker compose exec <service> php artisan --version`
- `docker compose exec <service> php -v`

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

## Rappel déploiement
- Compatible `docker_manager`
- Compatible `traefik_master`
- Réseau partagé `proxy_net`
- Labels Traefik obligatoires
- Domaine cible du type `mon-projet.it-sefako.com`
- `docker-compose.yml`, `docker-compose.traefik.yml`, `docker-manager.yml` maintenus
- `.env.example` clair et reproductible
"""


def _openhands_handoff(
    project_title: str,
    project_id: str,
    input_text: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
) -> str:
    docs = [
        "docs/global_environment.md",
        "docs/openhands_handoff.md",
        "README.md",
        "docs/cdc.md",
        "docs/mcd.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/notes_synthese.md",
        "docs/stack_decision.md",
        "docs/implementation_plan.md",
        "docs/requirements_matrix.md",
    ]
    return f"""# Handoff OpenHands

## Contexte
- Projet: {project_title}
- Project ID: `{project_id}`
- Mode opératoire: les agents du studio ne produisent que les documents Markdown.
- Responsabilité OpenHands: générer le code source réel, les fichiers de build, les routes, les composants et la structure finale du dépôt.

## Instructions de démarrage
1. Lire les documents du dossier `docs/` listés ci-dessous.
2. Interpréter le stack détecté et confirmer s'il faut un frontend et un backend séparés.
3. Si le stack est monolithique, garder la structure source à la racine du projet.
4. Si le stack nécessite une séparation, créer uniquement la séparation utile, pas de structure artificielle.
5. Générer le code source dans le workspace OpenHands, pas dans les agents du studio.
6. Commencer par une conversation canonique du projet et conserver le contexte des documents fournis.

## Documents de référence
- {chr(10).join(f'- `{doc}`' for doc in docs)}

## Brief initial
{input_text.strip()[:2000]}

## Stack détectée
- backend: `{stack.get('backend')}`
- frontend: `{stack.get('frontend')}`
- mobile: `{stack.get('mobile')}`
- base de données: `{stack.get('database')}`
- generation backend: `{stack.get('generation_backend')}`
- generation frontend: `{stack.get('generation_frontend')}`

## Livrables déjà préparés par les agents
```json
{json.dumps({
    "cdc": str(deliverables.get("cdc") or "")[:1200],
    "mcd": str(deliverables.get("mcd") or "")[:1200],
    "architecture": str(deliverables.get("architecture") or "")[:1200],
    "roadmap": str(deliverables.get("roadmap") or "")[:1200],
    "notes_synthese": str(deliverables.get("notes_synthese") or "")[:1200],
}, ensure_ascii=True, indent=2)}
```

## Règle d'or
Ne redemande pas à l'utilisateur de reproduire le cadrage déjà fourni.
Pars des documents existants et produis directement le code source attendu.
"""

def _next_frontend_dockerfile() -> str:
    return """FROM node:20-alpine
WORKDIR /app
COPY package.json package.json
COPY tsconfig.json tsconfig.json
COPY next.config.js next.config.js
COPY next-env.d.ts next-env.d.ts
COPY app app
RUN npm install
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
CMD ["npm", "run", "start"]
"""


def _next_package_json(project_title: str) -> str:
    return json.dumps({
        "name": slugify_project_title(project_title) + "-frontend",
        "private": True,
        "scripts": {
            "dev": "next dev -p 3000",
            "build": "next build",
            "start": "next start -p 3000"
        },
        "dependencies": {
            "next": "15.3.3",
            "react": "19.0.0",
            "react-dom": "19.0.0"
        }
    }, ensure_ascii=False, indent=2)


def _next_tsconfig() -> str:
    return """{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["dom", "dom.iterable", "es2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": false,
    "noEmit": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
"""


def _next_config() -> str:
    return """/** @type {import('next').NextConfig} */
const nextConfig = {};
module.exports = nextConfig;
"""


def _next_layout(project_title: str) -> str:
    safe_title = project_title.replace("'", "\'")
    return f"""import './globals.css';

export const metadata = {{
  title: '{safe_title}',
  description: 'Socle Next.js généré par AIA Studio',
}};

export default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{
  return (
    <html lang="fr">
      <body>{{children}}</body>
    </html>
  );
}}
"""


def _next_page(project_title: str, deliverables: dict[str, Any]) -> str:
    cdc = json.dumps(str(deliverables.get("cdc") or "")[:1200], ensure_ascii=False)
    return f"""export default function HomePage() {{
  const cdc = {cdc};

  return (
    <main className="shell">
      <p className="eyebrow">AIA Studio</p>
      <h1>{project_title}</h1>
      <p className="summary">{{cdc || 'Socle Next.js généré à partir des livrables validés.'}}</p>
      <section className="card">
        <h2>Socle généré</h2>
        <ul>
          <li>Frontend Next.js</li>
          <li>Compatible déploiement Docker / Traefik</li>
          <li>Prêt pour brancher les pages métier réelles</li>
        </ul>
      </section>
    </main>
  );
}}
"""


def _next_globals_css() -> str:
    return """body { margin: 0; font-family: Inter, system-ui, sans-serif; background: #0b0d12; color: #f5f7fb; }
.shell { max-width: 960px; margin: 0 auto; padding: 64px 24px; }
.eyebrow { letter-spacing: .24em; text-transform: uppercase; font-size: 12px; color: #8b5cf6; }
h1 { font-size: clamp(2rem, 4vw, 3.5rem); margin-bottom: 16px; }
.summary { color: rgba(245,247,251,.8); line-height: 1.7; }
.card { margin-top: 24px; padding: 24px; border-radius: 24px; border: 1px solid rgba(139,92,246,.25); background: rgba(17,21,31,.82); }
"""


SYSTEM_PROMPT_BACKEND = """Tu es un ingénieur logiciel backend senior. Ta tâche est de coder l'intégralité du socle backend d'une application en fonction du cahier des charges, de l'architecture et du modèle conceptuel de données (MCD) fournis.
Tu dois renvoyer obligatoirement et uniquement une structure JSON contenant la liste des fichiers à créer dans le dossier `backend/` (les chemins doivent tous commencer par 'backend/').
Format attendu:
{
  "files": [
    {
      "path": "backend/Dockerfile",
      "content": "... (Dockerfile adapté à la technologie choisie) ..."
    },
    {
      "path": "backend/app/main.py",
      "content": "... (code source complet) ..."
    }
  ]
}

CONTRAINTES CRITIQUES :
1. Aucun texte en dehors du JSON. Ne mets pas de bloc markdown triple backticks autour du JSON si possible, ou assure-toi que le JSON est valide.
2. Le code généré doit être COMPLET, sans placeholders, sans commentaires "TODO" ou "implémenter ici". Écris le vrai code métier du MVP.
3. Tu DOIS générer un point d'entrée Dockerfile fonctionnel dans `backend/Dockerfile` pour ton langage.
4. Tu DOIS impérativement exposer une route ou endpoint d'état de santé `/health` ou `/api/health` qui renvoie {"status": "ok"} pour que le système puisse vérifier que le backend fonctionne.
5. Adapte le code, les bibliothèques et le framework (FastAPI, Django, Express, Spring Boot, Go, Rust, Laravel, etc.) au choix de la stack détectée.
6. Ne sors pas du répertoire `backend/` (pas de modification de docker-compose.yml ou d'autres fichiers à la racine).
"""

SYSTEM_PROMPT_FRONTEND = """Tu es un développeur frontend senior. Ta tâche est de coder l'intégralité de l'interface utilisateur frontend en fonction du cahier des charges et de l'architecture fournis.
Tu dois renvoyer obligatoirement et uniquement une structure JSON contenant la liste des fichiers à créer dans le dossier `frontend/` (les chemins doivent tous commencer par 'frontend/').
Format attendu:
{
  "files": [
    {
      "path": "frontend/Dockerfile",
      "content": "... (Dockerfile pour le frontend) ..."
    },
    {
      "path": "frontend/app/page.tsx",
      "content": "... (code source de la page principale) ..."
    }
  ]
}

CONTRAINTES CRITIQUES :
1. Aucun texte en dehors du JSON. Ne mets pas de bloc markdown triple backticks autour du JSON si possible, ou assure-toi que le JSON est valide.
2. Le design doit être RICHE et PREMIUM (WOW effect) : utilise des polices modernes (Google Fonts), des palettes de couleurs harmonieuses (ex: HSL tailwind-like ou dark sleek), des transitions douces, des micro-animations et une mise en page soignée. Pas de placeholders basiques ou de MVP pauvre !
3. Le code généré doit être COMPLET, sans placeholders.
4. Tu DOIS générer un Dockerfile fonctionnel dans `frontend/Dockerfile` pour builder/servir l'application (ex: avec nginx pour le statique, ou npm run start pour Next.js/Node).
5. Adapte le code et le framework (Next.js, React, Vue, Svelte, HTML/JS statique, etc.) au choix de la stack détectée.
6. Le frontend doit consommer et interagir avec l'API backend en utilisant des requêtes fetch.
7. Ne sors pas du répertoire `frontend/` (pas de modification de docker-compose.yml ou d'autres fichiers à la racine).
"""

def _parse_json_response(raw: str) -> dict | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start:end+1])
            except Exception:
                pass
    return None

async def _generate_llm_backend_files(
    project_title: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    llm_router: LLMRouter
) -> list[tuple[str, str]]:
    prompt = f"""Génère tous les fichiers backend requis pour le projet "{project_title}".
Stack technique backend demandée: {stack.get('backend')} (langage: {stack.get('languages')}, base de données: {stack.get('database')}).

Documents de référence:
1. Cahier des charges (CDC):
{str(deliverables.get('cdc') or '')[:3000]}

2. Architecture technique:
{str(deliverables.get('architecture') or '')[:3000]}

3. Modèle conceptuel de données (MCD):
{str(deliverables.get('mcd') or '')[:3000]}

Génère la structure complète des fichiers (Dockerfile, fichiers de dépendances, scripts d'initialisation de base de données, routes, modèles, controlleurs) dans le format JSON demandé.
"""
    try:
        response = await llm_router.generate(
            prompt=prompt,
            agent_type="engineering",
            system_prompt=SYSTEM_PROMPT_BACKEND
        )
        parsed = _parse_json_response(response)
        if parsed and isinstance(parsed, dict) and "files" in parsed:
            specs = []
            for item in parsed["files"]:
                path = item.get("path")
                content = item.get("content")
                if path and content is not None:
                    try:
                        path = str(Path(path).relative_to(Path(path).anchor))
                    except Exception:
                        pass
                    if not path.startswith("backend/"):
                        path = "backend/" + path
                    specs.append((path, content))
            if specs:
                return specs
    except Exception as e:
        print(f"Erreur génération LLM backend: {e}")
    return []

async def _generate_llm_frontend_files(
    project_title: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    llm_router: LLMRouter
) -> list[tuple[str, str]]:
    prompt = f"""Génère tous les fichiers frontend requis pour le projet "{project_title}".
Stack technique frontend demandée: {stack.get('frontend')}.

Documents de référence:
1. Cahier des charges (CDC):
{str(deliverables.get('cdc') or '')[:3000]}

2. Architecture technique:
{str(deliverables.get('architecture') or '')[:3000]}

Génère la structure complète des fichiers frontend (Dockerfile, package.json ou index.html, pages de composants, styles CSS stylisés premium) dans le format JSON demandé.
"""
    try:
        response = await llm_router.generate(
            prompt=prompt,
            agent_type="ux",
            system_prompt=SYSTEM_PROMPT_FRONTEND
        )
        parsed = _parse_json_response(response)
        if parsed and isinstance(parsed, dict) and "files" in parsed:
            specs = []
            for item in parsed["files"]:
                path = item.get("path")
                content = item.get("content")
                if path and content is not None:
                    try:
                        path = str(Path(path).relative_to(Path(path).anchor))
                    except Exception:
                        pass
                    if not path.startswith("frontend/"):
                        path = "frontend/" + path
                    specs.append((path, content))
            if specs:
                return specs
    except Exception as e:
        print(f"Erreur génération LLM frontend: {e}")
    return []

async def _backend_file_specs(
    project_title: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    llm_router: LLMRouter | None = None
) -> list[tuple[str, str]]:
    if llm_router is not None:
        llm_files = await _generate_llm_backend_files(project_title, deliverables, stack, llm_router)
        if llm_files:
            return llm_files

    if stack.get("generation_backend") == "laravel":
        return [
            ('backend/Dockerfile', _laravel_backend_dockerfile()),
            ('backend/composer.json', _laravel_composer_json(project_title)),
            ('backend/public/index.php', _laravel_public_index(project_title)),
            ('backend/routes/api.php', _laravel_routes_api()),
            ('backend/app/Http/Controllers/ProjectSummaryController.php', _laravel_summary_controller(project_title, deliverables)),
        ]
    return [
        ('backend/Dockerfile', _backend_dockerfile()),
        ('backend/requirements.txt', _backend_requirements()),
        ('backend/app/main.py', _backend_main_py(project_title, deliverables)),
    ]


async def _frontend_file_specs(
    project_title: str,
    deliverables: dict[str, Any],
    stack: dict[str, str],
    llm_router: LLMRouter | None = None
) -> list[tuple[str, str]]:
    if llm_router is not None:
        llm_files = await _generate_llm_frontend_files(project_title, deliverables, stack, llm_router)
        if llm_files:
            return llm_files

    if stack.get("generation_frontend") == "nextjs":
        return [
            ('frontend/Dockerfile', _next_frontend_dockerfile()),
            ('frontend/package.json', _next_package_json(project_title)),
            ('frontend/tsconfig.json', _next_tsconfig()),
            ('frontend/next.config.js', _next_config()),
            ('frontend/next-env.d.ts', "/// <reference types=\"next\" />\n/// <reference types=\"next/image-types/global\" />\n"),
            ('frontend/app/layout.tsx', _next_layout(project_title)),
            ('frontend/app/page.tsx', _next_page(project_title, deliverables)),
            ('frontend/app/globals.css', _next_globals_css()),
        ]
    return [
        ('frontend/Dockerfile', _frontend_dockerfile()),
        ('frontend/nginx.conf', _frontend_nginx_conf()),
        ('frontend/index.html', _frontend_index_html(project_title)),
        ('frontend/app.js', _frontend_app_js()),
        ('frontend/styles.css', _frontend_styles()),
    ]


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
        "| # | Exigence | Couverture actuelle | Références | Statut |",
        "|---|---|---|---|---|",
    ]
    for index, requirement in enumerate(requirements, 1):
        lowered = requirement.lower()
        refs = ["docs/cdc.md", "docs/stack_decision.md", "docs/openhands_handoff.md"]
        if any(word in lowered for word in ["api", "backend", "base", "donnée", "donnee", "auth", "crud", "laravel", "fastapi"]):
            refs.append("docs/openhands_handoff.md")
        if any(word in lowered for word in ["interface", "utilisateur", "page", "mobile", "frontend", "dashboard", "écran", "ecran"]):
            refs.append("docs/stack_decision.md")
        if any(word in lowered for word in ["docker", "déploiement", "deploiement", "traefik", "env"]):
            refs.extend(["docs/openhands_handoff.md", "README.md"])
        coverage = "Tracé dans les documents de cadrage et le handoff OpenHands. Le code source est délégué à OpenHands."
        status = "couvert" if len(refs) > 2 else "à préciser"
        rows.append(f"| {index} | {requirement.replace('|', '/')} | {coverage} | {', '.join(dict.fromkeys(refs))} | {status} |")
    rows.extend([
        "",
        "## Stack reconnue",
        f"- backend demandé: `{stack.get('backend')}`",
        f"- frontend demandé: `{stack.get('frontend')}`",
        f"- backend généré par agents: `non`",
        f"- frontend généré par agents: `non`",
        f"- backend confié à: `OpenHands`",
        f"- frontend confié à: `OpenHands`",
        "",
        "Cette matrice sert de contrat de vérification pour le cadrage et le handoff OpenHands.",
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
        "docs/cdc.md",
        "docs/mcd.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/notes_synthese.md",
        "docs/stack_decision.md",
        "docs/global_environment.md",
        "docs/implementation_plan.md",
        "docs/requirements_matrix.md",
        "docs/openhands_handoff.md",
        ".aia/workspace-policy.json",
    ]
    missing_files = [relative for relative in required_files if not (base / relative).exists()]

    readme = (base / "README.md").read_text(errors="ignore") if (base / "README.md").exists() else ""
    stack_decision = (base / "docs/stack_decision.md").read_text(errors="ignore") if (base / "docs/stack_decision.md").exists() else ""
    handoff = (base / "docs/openhands_handoff.md").read_text(errors="ignore") if (base / "docs/openhands_handoff.md").exists() else ""

    checks = [
        {"key": "required_files", "label": "Documents minimum du repo présents", "ok": not missing_files},
        {"key": "readme_mentions_openhands", "label": "README documente le passage de relais à OpenHands", "ok": "OpenHands" in readme and "Markdown" in readme},
        {"key": "stack_decision_present", "label": "Décision de stack documentée", "ok": "Décision de stack" in stack_decision and stack.get("backend") in stack_decision},
        {"key": "openhands_handoff_present", "label": "Handoff OpenHands documenté", "ok": "Handoff OpenHands" in handoff and "générer le code source" in handoff},
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


def _readme(project_title: str, project_id: str, deliverables: dict[str, Any], workspace_root: str, stack: dict[str, str]) -> str:
    return f"""# {project_title}

Project ID: `{project_id}`

Ce workspace est un espace de cadrage documentaire pour AIA Studio.
Les agents du studio produisent les documents Markdown, puis OpenHands prend le relais pour générer le code source.

## Stack détectée
- backend demandé: `{stack.get('backend')}`
- frontend demandé: `{stack.get('frontend')}`
- mobile détecté: `{stack.get('mobile')}`
- base de données détectée: `{stack.get('database')}`
- langages détectés: `{stack.get('languages')}`

## Décision de livraison
- code source généré par les agents: `non`
- code source généré par OpenHands: `oui`
- structure du dépôt décidée par le couple cadrage + OpenHands

## Règles de travail
- racine de génération: `{workspace_root}`
- les agents n'écrivent que des documents Markdown et les garde-fous internes
- OpenHands reçoit ensuite le contexte et produit le dépôt exécutable
- aucun accès direct à `docker_manager`, `traefik_master` ou aux autres projets

## Livrables d'entrée

```json
{json.dumps(deliverables, indent=2, ensure_ascii=True)}
```
"""


async def initialize_project_workspace(
    *,
    root_path: str,
    project_id: str,
    project_title: str,
    deliverables: dict[str, Any],
) -> dict[str, Any]:
    project_dir = get_project_workspace_dir(root_path, project_id, project_title)
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_within_workspace(project_dir, project_dir)

    input_text = str(deliverables.get('input_text') or '')
    stack = detect_application_stack(project_title, input_text, deliverables)
    docs_specs = _documentation_specs(project_title, project_id, input_text, deliverables, stack, root_path)

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
    docs_specs = _documentation_specs(project_title, project_id, input_text, deliverables, stack, str(base.parent))
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
