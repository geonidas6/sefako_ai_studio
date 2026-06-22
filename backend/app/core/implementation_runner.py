from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.project_workspace import (
    IMPLEMENTATION_PIPELINE_KEY,
    IMPLEMENTATION_WORKSPACE_KEY,
    WorkspaceSettings,
    detect_application_stack,
    ensure_pipeline_metadata,
    generate_application_foundation,
    get_workspace_settings,
    initialize_project_workspace,
    set_pipeline_phase,
    validate_workspace_delivery,
)
from app.core.workflow_runner import publish_project_event
from app.core.openhands_bridge import ensure_project_conversation
from app.db.database import AsyncSessionLocal
from app.models.project import Project
from app.core.llm_router import LLMRouter

ACTIVE_IMPLEMENTATION_TASKS: dict[str, asyncio.Task] = {}
IMPLEMENTATION_LOCKS: dict[str, asyncio.Lock] = {}


PHASES = [
    ('technical_design', 'Conception technique'),
    ('documentation_pack', 'Pack documentaire'),
    ('openhands_bootstrap', 'Handoff OpenHands'),
    ('requirements_coverage', 'Couverture du CDC'),
    ('automated_validation', 'Validation documentaire'),
    ('delivery_review', 'Revue de livraison'),
]


def _lock(project_id: str) -> asyncio.Lock:
    lock = IMPLEMENTATION_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        IMPLEMENTATION_LOCKS[project_id] = lock
    return lock


def is_implementation_active(project_id: str) -> bool:
    task = ACTIVE_IMPLEMENTATION_TASKS.get(project_id)
    return bool(task and not task.done())


async def _load_project(db, project_id: str) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def _save_pipeline(project_id: str, pipeline: dict[str, Any], deliverables: dict[str, Any] | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        project = await _load_project(db, project_id)
        if not project:
            raise ValueError('Projet non trouvé')
        final_deliverables = dict(deliverables or project.final_deliverables or {})
        final_deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
        project.final_deliverables = final_deliverables
        await db.commit()
        return final_deliverables


async def _publish_pipeline(project_id: str, pipeline: dict[str, Any], message: str) -> None:
    await publish_project_event(project_id, {
        'type': 'implementation_status',
        'message': message,
        'pipeline': pipeline,
    })


async def _employee_message(project_id: str, agent: str, department: str, employee: dict[str, str], message: str, phase: str, target: str | None = None) -> None:
    await publish_project_event(project_id, {
        'type': 'employee_message',
        'agent': agent,
        'department': department,
        'employee': employee,
        'message': message,
        'phase': phase,
        'target': target,
        'round': 4,
    })


async def recover_interrupted_implementation_runs() -> int:
    message = (
        'La phase applicative a été interrompue par un redémarrage du backend. '
        'Le pipeline est repassé en pause logique et peut être relancé sans toucher hors du dossier projet.'
    )
    recovered = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project))
        projects = result.scalars().all()
        for project in projects:
            deliverables = dict(project.final_deliverables or {})
            pipeline = deliverables.get(IMPLEMENTATION_PIPELINE_KEY)
            if not isinstance(pipeline, dict):
                continue
            if pipeline.get('status') != 'running':
                continue
            pipeline = set_pipeline_phase(
                pipeline,
                pipeline.get('current_phase') or 'technical_design',
                'paused',
                overall_status='paused',
                last_error=message,
            )
            deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
            project.final_deliverables = deliverables
            recovered += 1
        if recovered:
            await db.commit()

    if recovered:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project))
            for project in result.scalars().all():
                deliverables = dict(project.final_deliverables or {})
                pipeline = deliverables.get(IMPLEMENTATION_PIPELINE_KEY)
                if isinstance(pipeline, dict) and pipeline.get('status') == 'paused':
                    await _publish_pipeline(project.id, pipeline, message)
    return recovered


async def start_implementation_pipeline(project_id: str) -> dict[str, Any]:
    async with _lock(project_id):
        active = ACTIVE_IMPLEMENTATION_TASKS.get(project_id)
        if active and not active.done():
            return {'started': False, 'already_running': True}

        async with AsyncSessionLocal() as db:
            project = await _load_project(db, project_id)
            if not project:
                raise ValueError('Projet non trouvé')
            if project.status != 'completed':
                raise ValueError("La phase applicative n'est disponible qu'après une analyse terminée.")

            settings = await get_workspace_settings(db)
            deliverables = ensure_pipeline_metadata(project.final_deliverables or {}, settings)
            pipeline = dict(deliverables.get(IMPLEMENTATION_PIPELINE_KEY) or {})
            if pipeline.get('status') == 'awaiting_admin_approval':
                raise PermissionError('Validation administrateur requise avant de lancer la phase applicative.')

            workspace = deliverables.get(IMPLEMENTATION_WORKSPACE_KEY)
            if not isinstance(workspace, dict) or not workspace.get('project_dir'):
                raise ValueError('Le workspace technique doit être initialisé avant la phase applicative.')

            pipeline = set_pipeline_phase(
                pipeline,
                pipeline.get('current_phase') or 'technical_design',
                'running',
                overall_status='running',
                project_dir=workspace.get('project_dir'),
                generated_files=workspace.get('files') or [],
                last_error=None,
            )
            deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
            project.final_deliverables = deliverables
            await db.commit()
            input_text = project.input_text
            project_title = project.title

        await _publish_pipeline(project_id, pipeline, 'Phase lancée. Les employés préparent le pack documentaire et le relais OpenHands.')

        async def runner() -> None:
            try:
                await _run_pipeline(project_id, project_title, input_text)
            finally:
                ACTIVE_IMPLEMENTATION_TASKS.pop(project_id, None)

        task = asyncio.create_task(runner())
        ACTIVE_IMPLEMENTATION_TASKS[project_id] = task
        return {'started': True, 'already_running': False}


async def _run_pipeline(project_id: str, project_title: str, input_text: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            project = await _load_project(db, project_id)
            if not project:
                raise ValueError('Projet non trouvé')
            settings = await get_workspace_settings(db)
            deliverables = ensure_pipeline_metadata(project.final_deliverables or {}, settings)
            workspace = deliverables.get(IMPLEMENTATION_WORKSPACE_KEY)
            if not isinstance(workspace, dict) or not workspace.get('project_dir'):
                workspace = await initialize_project_workspace(
                    root_path=settings.root_path,
                    project_id=project.id,
                    project_title=project.title,
                    deliverables={**deliverables, 'input_text': project.input_text},
                )
                deliverables[IMPLEMENTATION_WORKSPACE_KEY] = workspace
            pipeline = dict(deliverables.get(IMPLEMENTATION_PIPELINE_KEY) or {})
            project.final_deliverables = deliverables
            await db.commit()

        effective_input_text = input_text
        try:
            request_file = Path(str(workspace['project_dir'])).resolve() / 'docs/feature_requests.md'
            if request_file.exists():
                feature_requests = request_file.read_text(encoding='utf-8', errors='ignore')[-6000:]
                if feature_requests.strip():
                    effective_input_text += f"\n\nDemandes applicatives depuis l'IDE:\n{feature_requests}"
        except Exception:
            pass

        employees = {
            'strategy': {'name': 'Aminata', 'role': 'Lead Growth', 'avatar': 'AG'},
            'ux': {'name': 'Maya', 'role': 'UX Researcher', 'avatar': 'UX'},
            'engineering': {'name': 'Elias', 'role': 'Architecte logiciel', 'avatar': 'AR'},
            'devops': {'name': 'Karim', 'role': 'DevSecOps', 'avatar': 'DS'},
            'orchestrator': {'name': 'Sefako Orchestrateur', 'role': 'Chef de projet IA', 'avatar': 'SO'},
        }

        pipeline = set_pipeline_phase(pipeline, 'technical_design', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline)
        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], f"Conception technique validée. Le workspace documentaire est prêt dans {workspace['project_dir']}.", 'technical_design', 'workspace projet')
        await _publish_pipeline(project_id, pipeline, 'Conception technique validée. Préparation du pack documentaire...')

        pipeline = set_pipeline_phase(pipeline, 'documentation_pack', 'running', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'strategy', 'Stratégie', employees['strategy'], "Je consolide le cadrage Markdown: CDC, MCD, architecture, roadmap, matrice et handoff OpenHands.", 'documentation_pack', 'docs/openhands_handoff.md')
        await _publish_pipeline(project_id, pipeline, 'Pack documentaire préparé.')
        pipeline = set_pipeline_phase(pipeline, 'documentation_pack', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'openhands_bootstrap', 'running', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        openhands_thread = None
        try:
            openhands_thread = await ensure_project_conversation(
                project_id,
                project_title,
                Path(str(workspace['project_dir'])),
                brief=effective_input_text,
                deliverables=deliverables,
            )
            deliverables['openhands_conversation'] = openhands_thread
            await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], 'Le contexte Markdown a été transmis à OpenHands pour générer le code source.', 'openhands_bootstrap', 'OpenHands')
            await _publish_pipeline(project_id, pipeline, 'OpenHands a été initialisé avec le contexte du projet.')
            pipeline = set_pipeline_phase(pipeline, 'openhands_bootstrap', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
            deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        except Exception as exc:
            await _publish_pipeline(project_id, pipeline, f'OpenHands bootstrap en erreur: {exc}')

        pipeline = set_pipeline_phase(pipeline, 'requirements_coverage', 'running', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'strategy', 'Stratégie', employees['strategy'], "Je relis le CDC et la décision de stack pour vérifier que chaque exigence est couverte par les documents et le handoff.", 'requirements_coverage', 'docs/requirements_matrix.md')
        validation = validate_workspace_delivery(
            project_dir=workspace['project_dir'],
            project_id=project_id,
            project_title=project_title,
            input_text=effective_input_text,
            deliverables=deliverables,
        )
        pipeline = set_pipeline_phase(pipeline, 'requirements_coverage', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'automated_validation', 'running', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'devops', 'DevOps', employees['devops'], "Je lance les contrôles de conformité documentaire et le garde-fou workspace.", 'automated_validation', 'docs/test_report.md')
        if not validation.get('success'):
            raise ValueError('Validation documentaire échouée: ' + ', '.join(validation.get('missing_files') or ['contrôle statique invalide']))
        pipeline = set_pipeline_phase(pipeline, 'automated_validation', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'delivery_review', 'running', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], "Je consolide la revue finale: couverture documentaire, validation et handoff OpenHands.", 'delivery_review', 'docs/delivery_review.md')
        pipeline = set_pipeline_phase(pipeline, 'delivery_review', 'completed', overall_status='completed', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [], last_error=None)

        deliverables[IMPLEMENTATION_WORKSPACE_KEY] = {
            **workspace,
            'files': workspace.get('files') or [],
            'generated_at': workspace.get('generated_at'),
            'repo_name': workspace.get('repo_name'),
            'openhands_conversation': openhands_thread,
        }
        deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
        deliverables['implementation_validation'] = validation

        async with AsyncSessionLocal() as db:
            project = await _load_project(db, project_id)
            if project:
                project.final_deliverables = deliverables
                await db.commit()

        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], 'Le cadrage est prêt. OpenHands reçoit maintenant le contexte pour produire le code source dans le workspace dédié.', 'implementation_complete', 'OpenHands')
        await publish_project_event(project_id, {
            'type': 'implementation_complete',
            'message': 'Phase documentaire terminée. OpenHands a été relancé avec le contexte du projet.',
            'pipeline': pipeline,
            'workspace': deliverables[IMPLEMENTATION_WORKSPACE_KEY],
        })
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            project = await _load_project(db, project_id)
            if project:
                settings = await get_workspace_settings(db)
                deliverables = ensure_pipeline_metadata(project.final_deliverables or {}, settings)
                pipeline = dict(deliverables.get(IMPLEMENTATION_PIPELINE_KEY) or {})
                pipeline = set_pipeline_phase(
                    pipeline,
                    pipeline.get('current_phase') or 'technical_design',
                    'failed',
                    overall_status='failed',
                    last_error=str(exc),
                )
                deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
                project.final_deliverables = deliverables
                await db.commit()
                await publish_project_event(project_id, {
                    'type': 'implementation_error',
                    'message': str(exc),
                    'pipeline': pipeline,
                })
