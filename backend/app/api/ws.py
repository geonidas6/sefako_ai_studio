"""
WebSocket endpoint for real-time streaming of agent workflow.

Client connects to: ws://localhost:8000/ws/projects/{project_id}
Then sends: {"action": "start"}
Server streams: events (agent_start, agent_complete, round_complete, workflow_complete, ...)
"""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db, AsyncSessionLocal
from app.models.project import Project
from app.agents.orchestrator import run_project_workflow

router = APIRouter()


@router.websocket("/ws/projects/{project_id}")
async def project_websocket(project_id: str, websocket: WebSocket):
    await websocket.accept()

    # Verify project exists
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()

    if not project:
        await websocket.send_json({"type": "error", "message": "Projet non trouvé"})
        await websocket.close()
        return

    # If already completed, send existing results
    if project.status == "completed" and project.final_deliverables:
        await websocket.send_json({
            "type": "workflow_complete",
            "deliverables": project.final_deliverables,
        })
        await websocket.close()
        return

    try:
        # Wait for "start" action from client
        data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        msg = json.loads(data)
        if msg.get("action") != "start":
            await websocket.send_json({"type": "error", "message": "Action invalide"})
            await websocket.close()
            return
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "message": "Timeout d'attente"})
        await websocket.close()
        return

    # Set up event streaming
    event_queue: asyncio.Queue = asyncio.Queue()

    async def stream_events():
        """Forward events from queue to WebSocket."""
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=120)
                if event is None:  # sentinel
                    break
                await websocket.send_json(event)
                event_queue.task_done()
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                break

    async def run_workflow():
        """Run the workflow and push a sentinel when done."""
        async with AsyncSessionLocal() as db:
            # Mark as running
            result = await db.execute(select(Project).where(Project.id == project_id))
            proj = result.scalar_one_or_none()
            if proj:
                proj.status = "running"
                await db.commit()

        async with AsyncSessionLocal() as db:
            try:
                await run_project_workflow(project_id, project.input_text, db, event_queue)
            except Exception as e:
                await event_queue.put({"type": "error", "message": str(e)})
            finally:
                await event_queue.put(None)  # sentinel to stop streaming

    # Run both concurrently
    await asyncio.gather(
        stream_events(),
        run_workflow(),
    )

    try:
        await websocket.close()
    except Exception:
        pass
