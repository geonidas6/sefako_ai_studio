import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.db.database import get_db
from app.models.project import Project

router = APIRouter()


class ProjectCreateIn(BaseModel):
    title: str
    input_text: str


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
    await db.delete(project)
    await db.commit()
    return {"success": True}
