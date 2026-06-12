import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete
from pydantic import BaseModel

from app.db.database import get_db
from app.models.project import Project
from app.models.workflow_event import WorkflowEvent
from app.core.workflow_runner import get_project_events, is_workflow_active, publish_project_event, request_pause, start_project_workflow

router = APIRouter()


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


@router.get("/", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).order_by(desc(Project.created_at)).limit(50)
    )
    return [project_to_dict(p) for p in result.scalars().all()]


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

    return {"success": True}


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


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
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
