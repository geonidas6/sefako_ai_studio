import asyncio
import io
import shutil
import uuid
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import urlopen
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete
from pydantic import BaseModel

from app.core.config import settings
from app.core.project_workspace import IMPLEMENTATION_PIPELINE_KEY, IMPLEMENTATION_WORKSPACE_KEY, ensure_pipeline_metadata, ensure_within_workspace, get_workspace_settings, initialize_project_workspace, set_pipeline_phase
from app.core.openhands_bridge import ensure_project_conversation, run_openhands_task
from app.core.security import get_current_admin
from app.db.database import get_db
from app.models.project import Project
from app.models.workflow_event import WorkflowEvent
from app.core.workflow_runner import get_project_events, is_workflow_active, publish_project_event, request_pause, start_project_workflow
from app.core.implementation_runner import is_implementation_active, start_implementation_pipeline

router = APIRouter()




def _get_workspace_dir(project: Project) -> Path | None:
    deliverables = dict(project.final_deliverables or {})
    workspace = deliverables.get(IMPLEMENTATION_WORKSPACE_KEY)
    project_dir = workspace.get("project_dir") if isinstance(workspace, dict) else None
    if not project_dir:
        pipeline = deliverables.get(IMPLEMENTATION_PIPELINE_KEY)
        project_dir = pipeline.get("project_dir") if isinstance(pipeline, dict) else None
    if not project_dir:
        return None
    try:
        return Path(project_dir).resolve()
    except Exception:
        return None


def _build_markdown_export(project: Project) -> str:
    deliverables = dict(project.final_deliverables or {})
    critiques = dict(project.critiques or {})
    sections = [
        f"# {project.title}",
        '',
        f"- Projet ID: `{project.id}`",
        f"- Statut: `{project.status}`",
        f"- Créé le: `{project.created_at.isoformat()}`",
        f"- Terminé le: `{project.completed_at.isoformat()}`" if project.completed_at else '- Terminé le: `n/a`',
        '',
        '## Brief',
        '',
        project.input_text or '',
        '',
        '## Round 1 - Stratégie',
        '',
        project.strategy_r1 or '',
        '',
        '## Round 1 - UX',
        '',
        project.ux_r1 or '',
        '',
        '## Round 1 - Ingénierie',
        '',
        project.engineering_r1 or '',
        '',
        '## Round 1 - DevOps',
        '',
        project.devops_r1 or '',
        '',
        '## Round 2 - Critiques',
        '',
        '### Stratégie',
        '',
        critiques.get('strategy', ''),
        '',
        '### UX',
        '',
        critiques.get('ux', ''),
        '',
        '### Ingénierie',
        '',
        critiques.get('engineering', ''),
        '',
        '### DevOps',
        '',
        critiques.get('devops', ''),
        '',
        '## Round 3 - CDC',
        '',
        str(deliverables.get('cdc') or ''),
        '',
        '## Round 3 - MCD',
        '',
        str(deliverables.get('mcd') or ''),
        '',
        '## Round 3 - Architecture',
        '',
        str(deliverables.get('architecture') or ''),
        '',
        '## Round 3 - Roadmap',
        '',
        str(deliverables.get('roadmap') or ''),
        '',
        '## Round 3 - Synthèse',
        '',
        str(deliverables.get('notes_synthese') or ''),
        '',
    ]
    pipeline = deliverables.get(IMPLEMENTATION_PIPELINE_KEY)
    if isinstance(pipeline, dict):
        sections.extend([
            '## Pipeline applicatif',
            '',
            f"- Statut: `{pipeline.get('status')}`",
            f"- Phase courante: `{pipeline.get('current_phase')}`",
            f"- Dossier projet: `{pipeline.get('project_dir') or 'n/a'}`",
            '',
        ])
    return '\n'.join(sections).strip() + '\n'


def _workspace_tree(project_dir: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for entry_path in sorted(project_dir.rglob('*')):
        resolved = ensure_within_workspace(project_dir, entry_path)
        rel = resolved.relative_to(project_dir).as_posix()
        items.append({
            'path': rel,
            'name': resolved.name,
            'is_dir': resolved.is_dir(),
            'kind': 'directory' if resolved.is_dir() else 'file',
        })
    return items



def _normalize_base_url(base_url: str | None) -> str | None:
    candidate = (base_url or '').strip().rstrip('/')
    return candidate or None


def _probe_url(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= getattr(response, 'status', 200) < 400
    except URLError:
        return False
    except Exception:
        return False

class ProjectCreateIn(BaseModel):
    title: str
    input_text: str


class ProjectMessageIn(BaseModel):
    content: str
    author: str = "Utilisateur"


class ProjectOut(BaseModel):
    id: str
    title: str
    input_text: str
    status: str
    strategy_r1: Optional[str]
    ux_r1: Optional[str]
    engineering_r1: Optional[str]
    devops_r1: Optional[str]
    critiques: Optional[dict]
    final_deliverables: Optional[dict]
    created_at: str
    completed_at: Optional[str]


class TechnicalDesignStartIn(BaseModel):
    approved: bool = False


class ImplementationStartIn(BaseModel):
    approved: bool = False


class WorkspaceFileUpdateIn(BaseModel):
    path: str
    content: str


class WorkspaceCreateIn(BaseModel):
    path: str
    is_directory: bool = False
    content: str = ""


class WorkspaceMoveIn(BaseModel):
    old_path: str
    new_path: str


class WorkspaceHostExportCommandOut(BaseModel):
    project_dir: str
    repo_name: str
    destination: str
    command: str


class OpenHandsStatusOut(BaseModel):
    enabled: bool
    base_url: str | None = None
    alive: bool = False
    health: bool = False
    ready: bool = False
    workspace_dir: str | None = None
    conversation_id: str | None = None
    suggested_url: str | None = None
    embed_url: str | None = None
    notes: list[str] = []

def project_to_dict(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        title=p.title,
        input_text=p.input_text,
        status=p.status,
        strategy_r1=p.strategy_r1,
        ux_r1=p.ux_r1,
        engineering_r1=p.engineering_r1,
        devops_r1=p.devops_r1,
        critiques=p.critiques,
        final_deliverables=p.final_deliverables,
        created_at=p.created_at.isoformat(),
        completed_at=p.completed_at.isoformat() if p.completed_at else None,
    )


@router.get("", response_model=list[ProjectOut])
@router.get("/", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).order_by(desc(Project.created_at)).limit(50)
    )
    return [project_to_dict(p) for p in result.scalars().all()]


@router.post("")
@router.post("/", response_model=ProjectOut)
async def create_project(body: ProjectCreateIn, db: AsyncSession = Depends(get_db)):
    project = Project(
        id=str(uuid.uuid4()),
        title=body.title,
        input_text=body.input_text,
        status="pending",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project_to_dict(project)


@router.get("/{project_id}/events")
async def list_project_events(project_id: str, after_sequence: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project.id).where(Project.id == project_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    return await get_project_events(project_id, after_sequence=after_sequence)


@router.post("/{project_id}/messages")
async def add_project_message(project_id: str, body: ProjectMessageIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Le message est vide")
    if len(content) > 8000:
        raise HTTPException(status_code=400, detail="Le message doit faire 8000 caractères maximum")

    await publish_project_event(project_id, {
        "type": "user_message",
        "author": body.author.strip()[:80] or "Utilisateur",
        "content": content,
        "message": content,
    })

    if project.status == "running" or is_workflow_active(project_id):
        await publish_project_event(project_id, {
            "type": "employee_message",
            "agent": "orchestrator",
            "department": "Orchestrateur",
            "employee": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
            "message": "Nouvelle information client reçue. Je l'ajoute au contexte et je la redistribue aux départements aux prochaines étapes.",
            "phase": "client_input",
            "target": "tous les départements",
        })
        return {"success": True, "restart_triggered": False}

    workspace_dir = _get_workspace_dir(project)
    is_openhands_request = body.author.strip().lower() in {"workspace", "workspace ide", "ide", "openhands"}
    if is_openhands_request and workspace_dir:
        request_file = ensure_within_workspace(workspace_dir, workspace_dir / "docs/feature_requests.md")
        request_file.parent.mkdir(parents=True, exist_ok=True)
        existing = request_file.read_text(encoding="utf-8") if request_file.exists() else "# Demandes OpenHands\n\n"
        timestamp = datetime.now(timezone.utc).isoformat()
        request_file.write_text(existing.rstrip() + f"\n\n## {timestamp}\n\n{content}\n", encoding="utf-8")
        await publish_project_event(project_id, {
            "type": "employee_message",
            "agent": "orchestrator",
            "department": "Orchestrateur",
            "employee": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
            "message": "Brief OpenHands reçu. Je le range dans le contexte du projet et je prépare l'exécution locale.",
            "phase": "application_request",
            "target": "docs/feature_requests.md",
        })
        if project.status == "completed":
            async def _run_task() -> None:
                try:
                    await run_openhands_task(project_id, project.title, workspace_dir, content)
                except Exception as exc:
                    await publish_project_event(project_id, {
                        "type": "implementation_error",
                        "message": "OpenHands n'a pas pu exécuter la tâche.",
                        "error": str(exc),
                    })

            asyncio.create_task(_run_task())
            return {"success": True, "restart_triggered": False, "implementation_restart_triggered": True}
        return {"success": True, "restart_triggered": False, "implementation_restart_triggered": False}

    if project.status in {"completed", "failed", "paused"}:
        deliverables = dict(project.final_deliverables or {})
        for key in ["cdc", "mcd", "architecture", "roadmap", "notes_synthese", "error"]:
            deliverables.pop(key, None)
        project.final_deliverables = deliverables or None
        project.status = "pending"
        project.completed_at = None
        await db.commit()
        await publish_project_event(project_id, {
            "type": "employee_message",
            "agent": "orchestrator",
            "department": "Orchestrateur",
            "employee": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
            "message": "Nouvelle demande reçue après la livraison. Je relance automatiquement une passe de correction à partir des checkpoints existants.",
            "phase": "client_correction",
            "target": "tous les départements",
        })
        await publish_project_event(project_id, {
            "type": "implementation_status",
            "message": "Demande de correction reçue. Reprise automatique des analyses finales depuis les checkpoints.",
        })
        await start_project_workflow(project_id, reset=False)
        return {"success": True, "restart_triggered": True}

    return {"success": True, "restart_triggered": False}


@router.post("/{project_id}/start")
async def start_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    if project.status == "completed":
        raise HTTPException(status_code=400, detail="Le projet est déjà terminé. Utilisez relancer pour repartir de zéro.")
    try:
        result = await start_project_workflow(project_id, reset=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.post("/{project_id}/pause", response_model=ProjectOut)
async def pause_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    await request_pause(project_id)

    if project.status == "running" or is_workflow_active(project_id):
        project.status = "paused"
        project.final_deliverables = {"error": "Analyse mise en pause par l'utilisateur."}
        await db.commit()
        await db.refresh(project)

    return project_to_dict(project)


@router.post("/{project_id}/restart", response_model=ProjectOut)
async def restart_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    await request_pause(project_id)

    project.status = "pending"
    project.strategy_r1 = None
    project.ux_r1 = None
    project.engineering_r1 = None
    project.devops_r1 = None
    project.critiques = None
    project.final_deliverables = None
    project.completed_at = None
    await db.execute(delete(WorkflowEvent).where(WorkflowEvent.project_id == project_id))
    await db.commit()
    await db.refresh(project)
    return project_to_dict(project)


@router.post("/{project_id}/technical-design/start", response_model=ProjectOut)
async def start_technical_design(
    project_id: str,
    body: TechnicalDesignStartIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    if project.status != "completed":
        raise HTTPException(status_code=400, detail="La conception technique n'est disponible qu'après une analyse terminée.")

    settings = await get_workspace_settings(db)
    if settings.require_technical_approval and not body.approved:
        raise HTTPException(status_code=409, detail="Validation administrateur requise avant de lancer la phase conception technique.")

    deliverables = ensure_pipeline_metadata(dict(project.final_deliverables or {}), settings)
    workspace_info = await initialize_project_workspace(
        root_path=settings.root_path,
        project_id=project.id,
        project_title=project.title,
        deliverables={**deliverables, "input_text": project.input_text},
    )
    deliverables[IMPLEMENTATION_WORKSPACE_KEY] = workspace_info
    pipeline = dict(deliverables.get(IMPLEMENTATION_PIPELINE_KEY) or {})
    pipeline = set_pipeline_phase(
        pipeline,
        "admin_approval",
        "completed",
        overall_status="ready",
        project_dir=workspace_info["project_dir"],
        generated_files=workspace_info.get("files") or [],
        last_error=None,
    )
    pipeline = set_pipeline_phase(
        pipeline,
        "technical_design",
        "completed",
        overall_status="ready",
        project_dir=workspace_info["project_dir"],
        generated_files=workspace_info.get("files") or [],
        last_error=None,
    )
    deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
    project.final_deliverables = deliverables
    await db.commit()
    await db.refresh(project)

    await publish_project_event(project_id, {
        "type": "employee_message",
        "agent": "orchestrator",
        "department": "Orchestrateur",
        "employee": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
        "message": f"Workspace de conception technique initialisé dans {workspace_info['project_dir']}. Les futures générations resteront confinées dans ce dossier.",
        "phase": "technical_design",
        "target": "workspace projet",
    })
    await publish_project_event(project_id, {
        "type": "implementation_status",
        "message": "Conception technique prête. L'admin peut maintenant lancer la phase applicative.",
        "pipeline": pipeline,
    })

    return project_to_dict(project)


@router.post("/{project_id}/implementation/start")
async def start_project_implementation(
    project_id: str,
    body: ImplementationStartIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    if project.status != "completed":
        raise HTTPException(status_code=400, detail="La phase applicative n'est disponible qu'après une analyse terminée.")
    if is_implementation_active(project_id):
        return {"started": False, "already_running": True}

    settings = await get_workspace_settings(db)
    deliverables = ensure_pipeline_metadata(dict(project.final_deliverables or {}), settings)
    pipeline = dict(deliverables.get(IMPLEMENTATION_PIPELINE_KEY) or {})
    if settings.require_technical_approval and pipeline.get("status") == "awaiting_admin_approval" and not body.approved:
        raise HTTPException(status_code=409, detail="Validation administrateur requise avant de lancer la phase applicative.")
    workspace = deliverables.get(IMPLEMENTATION_WORKSPACE_KEY)
    if not isinstance(workspace, dict) or not workspace.get("project_dir"):
        raise HTTPException(status_code=409, detail="Initialisez d'abord la phase conception technique.")

    try:
        return await start_implementation_pipeline(project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/exports/markdown")
async def export_project_markdown(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    content = _build_markdown_export(project)
    filename = f"aia-project-{project.id}.md"
    return Response(
        content=content,
        media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/workspace/tree")
async def get_project_workspace_tree(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")
    return {'project_dir': str(project_dir), 'files': _workspace_tree(project_dir)}


@router.get("/{project_id}/workspace/file")
async def get_project_workspace_file(
    project_id: str,
    path: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")
    target = ensure_within_workspace(project_dir, project_dir / path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    content = target.read_text(errors='ignore')
    if len(content) > 250000:
        content = content[:250000] + "\n\n[Tronqué automatiquement]"
    return {'path': target.relative_to(project_dir).as_posix(), 'content': content}


@router.put("/{project_id}/workspace/file")
async def update_project_workspace_file(
    project_id: str,
    body: WorkspaceFileUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    relative_path = (body.path or '').strip()
    if not relative_path:
        raise HTTPException(status_code=400, detail="Chemin de fichier invalide")
    target = ensure_within_workspace(project_dir, project_dir / relative_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    if len(body.content) > 1_000_000:
        raise HTTPException(status_code=400, detail="Contenu trop volumineux")

    target.write_text(body.content)
    await publish_project_event(project_id, {
        "type": "implementation_status",
        "message": f"Fichier sauvegardé : {relative_path}",
        "pipeline": dict((project.final_deliverables or {}).get(IMPLEMENTATION_PIPELINE_KEY) or {}),
    })
    await publish_project_event(project_id, {
        "type": "employee_message",
        "agent": "engineering",
        "department": "Ingénierie",
        "employee": {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR"},
        "message": f"J'ai mis à jour le fichier `{relative_path}` dans le workspace projet sans sortir du périmètre autorisé.",
        "phase": "workspace_edit",
        "target": "repo projet",
        "round": 4,
    })
    return {"success": True, "path": relative_path}


@router.post("/{project_id}/workspace/create")
async def create_project_workspace_entry(
    project_id: str,
    body: WorkspaceCreateIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    relative_path = (body.path or '').strip().strip('/')
    if not relative_path:
        raise HTTPException(status_code=400, detail="Chemin invalide")

    target = ensure_within_workspace(project_dir, project_dir / relative_path)
    if target.exists():
        raise HTTPException(status_code=400, detail="Le chemin existe déjà")

    if body.is_directory:
        target.mkdir(parents=True, exist_ok=False)
        message = f"Dossier créé : {relative_path}"
        employee_message = f"J'ai créé le dossier `{relative_path}` dans le workspace projet pour préparer la suite de l'implémentation."
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        if len(body.content) > 1_000_000:
            raise HTTPException(status_code=400, detail="Contenu initial trop volumineux")
        target.write_text(body.content)
        message = f"Fichier créé : {relative_path}"
        employee_message = f"J'ai créé le fichier `{relative_path}` dans le workspace projet afin d'avancer sur la phase applicative."

    await publish_project_event(project_id, {
        "type": "implementation_status",
        "message": message,
        "pipeline": dict((project.final_deliverables or {}).get(IMPLEMENTATION_PIPELINE_KEY) or {}),
    })
    await publish_project_event(project_id, {
        "type": "employee_message",
        "agent": "engineering",
        "department": "Ingénierie",
        "employee": {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR"},
        "message": employee_message,
        "phase": "workspace_create",
        "target": "repo projet",
        "round": 4,
    })
    return {"success": True, "path": relative_path, "is_directory": body.is_directory}


@router.post("/{project_id}/workspace/move")
async def move_project_workspace_entry(
    project_id: str,
    body: WorkspaceMoveIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    old_path = (body.old_path or '').strip().strip('/')
    new_path = (body.new_path or '').strip().strip('/')
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="Chemins invalides")

    source = ensure_within_workspace(project_dir, project_dir / old_path)
    destination = ensure_within_workspace(project_dir, project_dir / new_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source introuvable")
    if destination.exists():
        raise HTTPException(status_code=400, detail="La destination existe déjà")

    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)

    await publish_project_event(project_id, {
        "type": "implementation_status",
        "message": f"Entrée déplacée/renommée : {old_path} -> {new_path}",
        "pipeline": dict((project.final_deliverables or {}).get(IMPLEMENTATION_PIPELINE_KEY) or {}),
    })
    await publish_project_event(project_id, {
        "type": "employee_message",
        "agent": "engineering",
        "department": "Ingénierie",
        "employee": {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR"},
        "message": f"J'ai renommé ou déplacé `{old_path}` vers `{new_path}` dans le workspace projet, sans sortir du dossier autorisé.",
        "phase": "workspace_move",
        "target": "repo projet",
        "round": 4,
    })
    return {"success": True, "old_path": old_path, "new_path": new_path}


@router.delete("/{project_id}/workspace/entry")
async def delete_project_workspace_entry(
    project_id: str,
    path: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    relative_path = (path or '').strip().strip('/')
    if not relative_path:
        raise HTTPException(status_code=400, detail="Chemin invalide")
    target = ensure_within_workspace(project_dir, project_dir / relative_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Chemin introuvable")

    if target.is_dir():
        shutil.rmtree(target)
        human_kind = 'Dossier'
        employee_message = f"J'ai supprimé le dossier `{relative_path}` du workspace projet pour nettoyer le périmètre de travail."
    else:
        target.unlink()
        human_kind = 'Fichier'
        employee_message = f"J'ai supprimé le fichier `{relative_path}` du workspace projet pour garder un repo cohérent."

    await publish_project_event(project_id, {
        "type": "implementation_status",
        "message": f"{human_kind} supprimé : {relative_path}",
        "pipeline": dict((project.final_deliverables or {}).get(IMPLEMENTATION_PIPELINE_KEY) or {}),
    })
    await publish_project_event(project_id, {
        "type": "employee_message",
        "agent": "engineering",
        "department": "Ingénierie",
        "employee": {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR"},
        "message": employee_message,
        "phase": "workspace_delete",
        "target": "repo projet",
        "round": 4,
    })
    return {"success": True, "path": relative_path}


@router.get("/{project_id}/workspace/archive")
async def download_project_workspace_archive(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in project_dir.rglob('*'):
            if file_path.is_dir():
                continue
            resolved = ensure_within_workspace(project_dir, file_path)
            zf.write(resolved, resolved.relative_to(project_dir).as_posix())
    filename = f"workspace-{project.id}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/workspace/host-export-command", response_model=WorkspaceHostExportCommandOut)
async def get_project_workspace_host_export_command(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    project_dir = _get_workspace_dir(project)
    if project_dir is None or not project_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace projet introuvable")

    repo_name = project_dir.name
    if not repo_name or "/" in repo_name or repo_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Nom de workspace invalide")

    destination = f"/opt/{repo_name}"
    command = f"cd /opt/sefako_ai_studio && ./scripts/export_workspace_to_host.sh {project.id}"
    return WorkspaceHostExportCommandOut(
        project_dir=str(project_dir),
        repo_name=repo_name,
        destination=destination,
        command=command,
    )


@router.get("/{project_id}/openhands/status", response_model=OpenHandsStatusOut)
async def get_project_openhands_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_admin),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    project_dir = _get_workspace_dir(project)
    base_url = _normalize_base_url(getattr(settings, "openhands_internal_url", None) or getattr(settings, "openhands_base_url", None))
    if not base_url:
        return OpenHandsStatusOut(
            enabled=False,
            workspace_dir=str(project_dir) if project_dir else None,
            notes=["Renseigne OPENHANDS_INTERNAL_URL pour connecter OpenHands local."],
        )

    alive = _probe_url(urljoin(base_url + '/', 'alive'))
    health = _probe_url(urljoin(base_url + '/', 'health'))
    ready = _probe_url(urljoin(base_url + '/', 'ready'))
    notes = [
        'OpenHands est configuré en local.',
        'Si l’interface n’embarque pas dans un iframe, ouvre-la dans un nouvel onglet.',
    ]
    conversation_id = None
    suggested_url = None
    embed_url = None

    if project_dir and project_dir.exists():
        try:
            conversation = await ensure_project_conversation(project_id, project.title, project_dir, project.input_text, project.final_deliverables)
            conversation_id = conversation.get('conversation_id')
            suggested_url = conversation.get('suggested_url')
            embed_url = conversation.get('embed_url')
            notes.extend(conversation.get('notes') or [])
        except Exception as exc:
            notes.append(f"Impossible d\'initialiser la conversation OpenHands: {exc}")

    if project_dir:
        notes.append(f'Workspace projet: {project_dir}')

    public_base = _normalize_base_url(getattr(settings, "openhands_public_url", None) or getattr(settings, "openhands_base_url", None) or base_url)
    if not suggested_url and public_base:
        suggested_url = f'{public_base.rstrip("/")}/conversations/{project_id}'
    if not embed_url:
        embed_url = suggested_url

    return OpenHandsStatusOut(
        enabled=True,
        base_url=base_url,
        alive=alive,
        health=health,
        ready=ready,
        workspace_dir=str(project_dir) if project_dir else None,
        conversation_id=conversation_id or project_id,
        suggested_url=suggested_url,
        embed_url=embed_url,
        notes=notes,
    )


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    if isinstance(project.final_deliverables, dict):
        settings = await get_workspace_settings(db)
        normalized = ensure_pipeline_metadata(dict(project.final_deliverables or {}), settings)
        if normalized != project.final_deliverables:
            project.final_deliverables = normalized
            await db.commit()
            await db.refresh(project)
    return project_to_dict(project)


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    await db.execute(delete(WorkflowEvent).where(WorkflowEvent.project_id == project_id))
    await db.delete(project)
    await db.commit()
    return {"success": True}
