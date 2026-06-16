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
from app.db.database import AsyncSessionLocal
from app.models.project import Project
from app.core.llm_router import LLMRouter

ACTIVE_IMPLEMENTATION_TASKS: dict[str, asyncio.Task] = {}
IMPLEMENTATION_LOCKS: dict[str, asyncio.Lock] = {}


PHASES = [
    ('technical_design', 'Conception technique'),
    ('repository_scaffold', 'Scaffold du repo'),
    ('backend_foundation', 'Socle backend'),
    ('frontend_foundation', 'Socle frontend'),
    ('docker_packaging', 'Compatibilité docker_manager'),
    ('requirements_coverage', 'Couverture du CDC'),
    ('automated_validation', 'Tests et validations'),
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

        await _publish_pipeline(project_id, pipeline, 'Phase applicative lancée. Les employés préparent le repo projet.')

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

        feature_requests = ''
        try:
            request_file = Path(str(workspace['project_dir'])).resolve() / 'docs/feature_requests.md'
            if request_file.exists():
                feature_requests = request_file.read_text(encoding='utf-8', errors='ignore')[-6000:]
        except Exception:
            feature_requests = ''
        effective_input_text = input_text + (f"\n\nDemandes applicatives depuis l'IDE:\n{feature_requests}" if feature_requests.strip() else '')

        employees = {
            'strategy': {'name': 'Aminata', 'role': 'Lead Growth', 'avatar': 'AG'},
            'ux': {'name': 'Maya', 'role': 'UX Researcher', 'avatar': 'UX'},
            'engineering': {'name': 'Elias', 'role': 'Architecte logiciel', 'avatar': 'AR'},
            'devops': {'name': 'Karim', 'role': 'DevSecOps', 'avatar': 'DS'},
            'orchestrator': {'name': 'Sefako Orchestrateur', 'role': 'Chef de projet IA', 'avatar': 'SO'},
        }

        # Phase 1: technical design confirmation
        pipeline = set_pipeline_phase(pipeline, 'technical_design', 'completed', overall_status='running', project_dir=workspace['project_dir'], generated_files=workspace.get('files') or [])
        deliverables = await _save_pipeline(project_id, pipeline)
        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], f"Conception technique validée. Le workspace sécurisé est prêt dans {workspace['project_dir']}.", 'technical_design', 'workspace projet')
        await _publish_pipeline(project_id, pipeline, 'Conception technique validée. Préparation du repo...')

        # Phase 2..5: repo/app generation
        stack = detect_application_stack(project_title, effective_input_text, deliverables)
        backend_label = 'Laravel / PHP' if stack.get('backend') == 'laravel' else 'FastAPI'
        frontend_label = 'Next.js' if stack.get('frontend') == 'nextjs' else 'frontend statique'

        async with AsyncSessionLocal() as db:
            llm_router = LLMRouter(db)
            repo_info = await generate_application_foundation(
                project_dir=workspace['project_dir'],
                project_id=project_id,
                project_title=project_title,
                input_text=effective_input_text,
                deliverables=deliverables,
                llm_router=llm_router,
            )
        phase_messages = [
            ('repository_scaffold', 'strategy', 'Stratégie', "Je verrouille le périmètre MVP et j'aligne le scaffold repo sur les livrables validés."),
            ('backend_foundation', 'engineering', 'Ingénierie', f"Je structure le backend {backend_label} et les premiers points d'entrée API sans sortir du workspace projet."),
            ('frontend_foundation', 'ux', 'UX', f"Je prépare le socle {frontend_label} du projet pour matérialiser le produit dès la première itération installable."),
            ('docker_packaging', 'devops', 'DevOps', "Je finalise les fichiers Docker, Traefik et .env pour rester compatible avec le git deploy de docker_manager."),
        ]
        for phase_key, agent_key, department, message in phase_messages:
            pipeline = set_pipeline_phase(pipeline, phase_key, 'running', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
            deliverables = await _save_pipeline(project_id, pipeline, deliverables)
            await _employee_message(project_id, agent_key, department, employees[agent_key], message, phase_key, 'repo projet')
            await _publish_pipeline(project_id, pipeline, f'{department} travaille sur {phase_key}.')
            pipeline = set_pipeline_phase(pipeline, phase_key, 'completed', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
            deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'requirements_coverage', 'running', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'strategy', 'Stratégie', employees['strategy'], "Je relis le CDC et je transforme les exigences en matrice de couverture vérifiable.", 'requirements_coverage', 'docs/requirements_matrix.md')
        validation = validate_workspace_delivery(
            project_dir=repo_info['project_dir'],
            project_id=project_id,
            project_title=project_title,
            input_text=effective_input_text,
            deliverables=deliverables,
        )
        repo_info['files'] = validation.get('files') or repo_info['files']
        pipeline = set_pipeline_phase(pipeline, 'requirements_coverage', 'completed', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'automated_validation', 'running', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'devops', 'DevOps', employees['devops'], "Je lance les contrôles statiques de livraison: Docker, Traefik, .env, healthcheck, garde-fou workspace.", 'automated_validation', 'docs/test_report.md')
        if not validation.get('success'):
            raise ValueError('Validation de livraison échouée: ' + ', '.join(validation.get('missing_files') or ['contrôle statique invalide']))
        pipeline = set_pipeline_phase(pipeline, 'automated_validation', 'completed', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)

        pipeline = set_pipeline_phase(pipeline, 'delivery_review', 'running', overall_status='running', project_dir=repo_info['project_dir'], generated_files=repo_info['files'])
        deliverables = await _save_pipeline(project_id, pipeline, deliverables)
        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], "Je consolide la revue finale: couverture, validation, manifest et consignes de déploiement.", 'delivery_review', 'docs/delivery_review.md')
        pipeline = set_pipeline_phase(pipeline, 'delivery_review', 'completed', overall_status='completed', project_dir=repo_info['project_dir'], generated_files=repo_info['files'], last_error=None)

        deliverables[IMPLEMENTATION_WORKSPACE_KEY] = {
            **workspace,
            'files': repo_info['files'],
            'generated_at': repo_info['generated_at'],
            'repo_name': repo_info['repo_name'],
        }
        deliverables[IMPLEMENTATION_PIPELINE_KEY] = pipeline
        deliverables['implementation_validation'] = validation

        async with AsyncSessionLocal() as db:
            project = await _load_project(db, project_id)
            if project:
                project.final_deliverables = deliverables
                await db.commit()

        await _employee_message(project_id, 'orchestrator', 'Orchestrateur', employees['orchestrator'], 'Le repo technique est prêt. Il reste autonome, compatible docker_manager et confiné au dossier projet.', 'implementation_complete', 'repo projet')
        await publish_project_event(project_id, {
            'type': 'implementation_complete',
            'message': 'Phase applicative terminée. Repo compatible docker_manager prêt.',
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
