"""WebSocket endpoint for observing project workflow events.

The workflow itself runs as a backend task started through the REST API.
This socket only replays persisted history and streams new events, so closing
the browser no longer stops the analysis.
"""
import asyncio

from fastapi import APIRouter, WebSocket
from sqlalchemy import select

from app.core.workflow_runner import get_project_events, subscribe_project, unsubscribe_project
from app.db.database import AsyncSessionLocal
from app.models.project import Project

router = APIRouter()


@router.websocket("/ws/projects/{project_id}")
async def project_websocket(project_id: str, websocket: WebSocket):
    await websocket.accept()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()

    if not project:
        await websocket.send_json({"type": "error", "message": "Projet non trouvé"})
        await websocket.close()
        return

    queue = await subscribe_project(project_id)
    try:
        history = await get_project_events(project_id)
        for event in history:
            await websocket.send_json(event)

        if project.status == "completed" and project.final_deliverables and not any(e.get("type") == "workflow_complete" for e in history):
            await websocket.send_json({
                "type": "workflow_complete",
                "deliverables": project.final_deliverables,
            })

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_json(event)
                queue.task_done()
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except Exception:
        pass
    finally:
        unsubscribe_project(project_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass
