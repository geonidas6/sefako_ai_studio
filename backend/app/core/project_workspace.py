from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_config import LLMConfig

WORKSPACE_ROOT_PATH_KEY = "workspace_root_path"
WORKSPACE_REQUIRE_APPROVAL_KEY = "workspace_require_technical_approval"
DEFAULT_WORKSPACE_ROOT = "/opt"
IMPLEMENTATION_PIPELINE_KEY = "implementation_pipeline"
IMPLEMENTATION_WORKSPACE_KEY = "implementation_workspace"

PIPELINE_PHASES = [
    ("admin_approval", "Validation admin"),
    ("technical_design", "Conception technique"),
    ("repository_scaffold", "Scaffold du repo"),
    ("backend_foundation", "Socle backend"),
    ("frontend_foundation", "Socle frontend"),
    ("docker_packaging", "Compatibilité docker_manager"),
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
    normalized.setdefault("phases", _phase_status())
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


def _project_env_template(slug: str) -> str:
    return f"""APP_NAME={slug}
FRONTEND_DOMAIN={slug}.example.com
API_DOMAIN=api-{slug}.example.com
POSTGRES_DB={slug}_db
POSTGRES_USER={slug}_user
POSTGRES_PASSWORD=change-me
SECRET_KEY=change-me
API_PORT=8000
FRONTEND_PORT=80
"""


def _project_compose_template(slug: str) -> str:
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
      - "80"
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


def _project_traefik_template(slug: str) -> str:
    return f"""services:
  backend:
    labels:
      - traefik.enable=true
      - traefik.docker.network=proxy_net
      - traefik.http.routers.{slug}-backend.rule=Host(`api-${{API_DOMAIN_BASE:-{slug}.example.com}}`)
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
      - traefik.http.services.{slug}-frontend.loadbalancer.server.port=80
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


def _readme(project_title: str, project_id: str, deliverables: dict[str, Any], workspace_root: str) -> str:
    return f"""# {project_title}

Project ID: `{project_id}`

Ce workspace a été initialisé par AIA Studio pour la phase de conception technique.

## Garde-fous
- racine de génération: `{workspace_root}`
- toutes les écritures sont limitées au dossier de ce projet
- aucun accès direct à `docker_manager`, `traefik_master` ou aux autres projets

## Livrables d'entrée

```json
{json.dumps(deliverables, indent=2, ensure_ascii=True)}
```
"""


def initialize_project_workspace(
    *,
    root_path: str,
    project_id: str,
    project_title: str,
    deliverables: dict[str, Any],
) -> dict[str, Any]:
    project_dir = get_project_workspace_dir(root_path, project_id, project_title)
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_within_workspace(project_dir, project_dir)

    slug = slugify_project_title(project_title)
    files = [
        _write_workspace_file(project_dir, 'README.md', _readme(project_title, project_id, deliverables, root_path)),
        _write_workspace_file(project_dir, '.env.example', _project_env_template(slug)),
        _write_workspace_file(project_dir, '.env', _project_env_template(slug)),
        _write_workspace_file(project_dir, 'docker-compose.yml', _project_compose_template(slug)),
        _write_workspace_file(project_dir, 'docker-compose.traefik.yml', _project_traefik_template(slug)),
        _write_workspace_file(project_dir, 'backend/Dockerfile', _backend_dockerfile()),
        _write_workspace_file(project_dir, 'backend/requirements.txt', _backend_requirements()),
        _write_workspace_file(project_dir, 'backend/app/main.py', _backend_main_py(project_title, deliverables)),
        _write_workspace_file(project_dir, 'frontend/Dockerfile', _frontend_dockerfile()),
        _write_workspace_file(project_dir, 'frontend/nginx.conf', _frontend_nginx_conf()),
        _write_workspace_file(project_dir, 'frontend/index.html', _frontend_index_html(project_title)),
        _write_workspace_file(project_dir, 'frontend/app.js', _frontend_app_js()),
        _write_workspace_file(project_dir, 'frontend/styles.css', _frontend_styles()),
        _write_workspace_file(project_dir, 'docs/cdc.md', str(deliverables.get('cdc') or '').strip() or '# CDC\n'),
        _write_workspace_file(project_dir, 'docs/mcd.md', str(deliverables.get('mcd') or '').strip() or '# MCD\n'),
        _write_workspace_file(project_dir, 'docs/architecture.md', str(deliverables.get('architecture') or '').strip() or '# Architecture\n'),
        _write_workspace_file(project_dir, 'docs/roadmap.md', str(deliverables.get('roadmap') or '').strip() or '# Roadmap\n'),
        _write_workspace_file(project_dir, 'docs/notes_synthese.md', str(deliverables.get('notes_synthese') or '').strip() or '# Notes de synthese\n'),
        _write_workspace_file(project_dir, 'docs/implementation_plan.md', _implementation_plan(project_title, deliverables.get('input_text') or '', deliverables)),
        _write_workspace_file(project_dir, '.aia/workspace-policy.json', _workspace_policy(str(project_dir.resolve()))),
        _write_workspace_file(project_dir, 'DEPLOY.md', _deploy_readme(slug, str(project_dir.resolve()))),
    ]

    return {
        'project_dir': str(project_dir.resolve()),
        'root_path': sanitize_workspace_root(root_path),
        'generated_at': utc_now_iso(),
        'files': files,
        'repo_name': project_dir.name,
    }


def generate_application_foundation(
    *,
    project_dir: str,
    project_id: str,
    project_title: str,
    input_text: str,
    deliverables: dict[str, Any],
) -> dict[str, Any]:
    base = Path(project_dir).resolve()
    ensure_within_workspace(base, base)
    slug = slugify_project_title(project_title)
    files = [
        _write_workspace_file(base, 'README.md', _readme(project_title, project_id, deliverables, str(base.parent))),
        _write_workspace_file(base, '.env.example', _project_env_template(slug)),
        _write_workspace_file(base, '.env', _project_env_template(slug)),
        _write_workspace_file(base, 'docker-compose.yml', _project_compose_template(slug)),
        _write_workspace_file(base, 'docker-compose.traefik.yml', _project_traefik_template(slug)),
        _write_workspace_file(base, 'backend/Dockerfile', _backend_dockerfile()),
        _write_workspace_file(base, 'backend/requirements.txt', _backend_requirements()),
        _write_workspace_file(base, 'backend/app/main.py', _backend_main_py(project_title, {**deliverables, 'input_text': input_text})),
        _write_workspace_file(base, 'frontend/Dockerfile', _frontend_dockerfile()),
        _write_workspace_file(base, 'frontend/nginx.conf', _frontend_nginx_conf()),
        _write_workspace_file(base, 'frontend/index.html', _frontend_index_html(project_title)),
        _write_workspace_file(base, 'frontend/app.js', _frontend_app_js()),
        _write_workspace_file(base, 'frontend/styles.css', _frontend_styles()),
        _write_workspace_file(base, 'docs/implementation_plan.md', _implementation_plan(project_title, input_text, deliverables)),
        _write_workspace_file(base, '.aia/workspace-policy.json', _workspace_policy(str(base))),
        _write_workspace_file(base, 'DEPLOY.md', _deploy_readme(slug, str(base))),
        _write_workspace_file(base, 'manifest.aia.json', json.dumps({
            'project_id': project_id,
            'project_title': project_title,
            'workspace': str(base),
            'docker_manager_compatible': True,
            'generated_at': utc_now_iso(),
        }, ensure_ascii=True, indent=2)),
    ]
    return {
        'project_dir': str(base),
        'generated_at': utc_now_iso(),
        'files': files,
        'repo_name': base.name,
    }
