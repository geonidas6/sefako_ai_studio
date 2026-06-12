from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select

from app.agents.orchestrator import WorkflowPaused, run_project_workflow
from app.core.workflow_control import WORKFLOW_CANCEL_EVENTS
from app.db.database import AsyncSessionLocal
from app.models.project import Project
from app.models.workflow_event import WorkflowEvent

ACTIVE_WORKFLOW_TASKS: dict[str, asyncio.Task] = {}
WORKFLOW_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = {}
PROJECT_LOCKS: dict[str, asyncio.Lock] = {}
EVENT_LOCKS: dict[str, asyncio.Lock] = {}


def _project_lock(project_id: str) -> asyncio.Lock:
    lock = PROJECT_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        PROJECT_LOCKS[project_id] = lock
    return lock


def _event_lock(project_id: str) -> asyncio.Lock:
    lock = EVENT_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        EVENT_LOCKS[project_id] = lock
    return lock


async def get_project_events(project_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.project_id == project_id, WorkflowEvent.sequence > after_sequence)
            .order_by(WorkflowEvent.sequence)
        )
        return [event.payload for event in result.scalars().all()]


async def clear_project_events(project_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(WorkflowEvent).where(WorkflowEvent.project_id == project_id))
        await db.commit()


async def publish_project_event(project_id: str, event: dict[str, Any]) -> None:
    if event is None:
        return

    event = dict(event)
    event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    event_type = str(event.get("type", "event"))

    async with _event_lock(project_id):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.coalesce(func.max(WorkflowEvent.sequence), 0)).where(WorkflowEvent.project_id == project_id)
            )
            sequence = int(result.scalar_one() or 0) + 1
            event["sequence"] = sequence
            db.add(WorkflowEvent(
                project_id=project_id,
                sequence=sequence,
                event_type=event_type,
                payload=event,
            ))
            await db.commit()

    for queue in list(WORKFLOW_SUBSCRIBERS.get(project_id, set())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


class PersistentEventSink:
    def __init__(self, project_id: str):
        self.project_id = project_id

    async def put(self, event: dict[str, Any] | None) -> None:
        if event is None:
            return
        await publish_project_event(self.project_id, event)


async def subscribe_project(project_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    WORKFLOW_SUBSCRIBERS.setdefault(project_id, set()).add(queue)
    return queue


def unsubscribe_project(project_id: str, queue: asyncio.Queue) -> None:
    subscribers = WORKFLOW_SUBSCRIBERS.get(project_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        WORKFLOW_SUBSCRIBERS.pop(project_id, None)


def is_workflow_active(project_id: str) -> bool:
    task = ACTIVE_WORKFLOW_TASKS.get(project_id)
    return bool(task and not task.done())


async def request_pause(project_id: str) -> bool:
    cancel_event = WORKFLOW_CANCEL_EVENTS.get(project_id)
    if cancel_event:
        cancel_event.set()
        return True
    return False


async def recover_interrupted_workflows() -> int:
    """Convert stale running projects to paused after a backend restart."""
    message = (
        "Analyse interrompue : le backend a redémarré ou la tâche a été coupée pendant l'exécution. "
        "Le projet a été mis en pause automatiquement. Vous pouvez reprendre depuis le dernier checkpoint."
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.status == "running"))
        projects = result.scalars().all()
        if not projects:
            return 0

        recovered_ids: list[str] = []
        for project in projects:
            project.status = "paused"
            project.completed_at = None
            project.final_deliverables = {"error": message, "reason": "interrupted"}
            recovered_ids.append(project.id)

        await db.commit()

    for project_id in recovered_ids:
        await publish_project_event(project_id, {
            "type": "workflow_paused",
            "message": message,
            "reason": "interrupted",
        })

    return len(recovered_ids)


async def start_project_workflow(project_id: str, reset: bool = False) -> dict[str, Any]:
    async with _project_lock(project_id):
        active = ACTIVE_WORKFLOW_TASKS.get(project_id)
        if active and not active.done():
            return {"started": False, "already_running": True}

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                raise ValueError("Projet non trouvé")

            if reset:
                project.strategy_r1 = None
                project.ux_r1 = None
                project.engineering_r1 = None
                project.devops_r1 = None
                project.critiques = None
                project.final_deliverables = None
                project.completed_at = None
                await db.commit()
                await clear_project_events(project_id)

            if project.status == "completed" and not reset:
                return {"started": False, "already_completed": True}

            if project.status != "running":
                project.status = "running"
                project.completed_at = None
                if project.final_deliverables and project.final_deliverables.get("error"):
                    project.final_deliverables = None
                await db.commit()

            input_text = project.input_text

        await publish_project_event(project_id, {"type": "workflow_started", "message": "Analyse lancée côté serveur."})

        cancel_event = WORKFLOW_CANCEL_EVENTS.setdefault(project_id, asyncio.Event())
        cancel_event.clear()

        async def runner() -> None:
            sink = PersistentEventSink(project_id)
            try:
                async with AsyncSessionLocal() as db:
                    await run_project_workflow(project_id, input_text, db, sink, cancel_event)
            except WorkflowPaused:
                pass
            except Exception as exc:
                await publish_project_event(project_id, {
                    "type": "workflow_error",
                    "error": str(exc),
                    "message": str(exc),
                })
            finally:
                current_event = WORKFLOW_CANCEL_EVENTS.get(project_id)
                if current_event is cancel_event:
                    WORKFLOW_CANCEL_EVENTS.pop(project_id, None)
                ACTIVE_WORKFLOW_TASKS.pop(project_id, None)

        task = asyncio.create_task(runner())
        ACTIVE_WORKFLOW_TASKS[project_id] = task
        return {"started": True, "already_running": False}
