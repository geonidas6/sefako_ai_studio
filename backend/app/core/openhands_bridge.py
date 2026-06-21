from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.workflow_runner import publish_project_event


OPENHANDS_SESSION_KEY_RE = re.compile(r'__AGENT_CANVAS_SESSION_API_KEY__="([^"]+)"')


def _get_agent_server_url() -> str:
    return _normalize_text(os.getenv('OPENHANDS_AGENT_SERVER_URL')) or 'http://openhands:18000'


def _get_public_openhands_url() -> str | None:
    return _normalize_text(os.getenv('OPENHANDS_PUBLIC_URL')) or _normalize_text(os.getenv('OPENHANDS_BASE_URL')) or None


async def _get_session_api_key() -> str | None:
    candidate_urls = [
        _normalize_text(os.getenv('OPENHANDS_PUBLIC_URL')) or None,
        'http://openhands:8000',
    ]
    for candidate in candidate_urls:
        if not candidate:
            continue
        try:
            async with httpx.AsyncClient(base_url=candidate, timeout=10.0, follow_redirects=True) as client:
                response = await client.get('/')
                response.raise_for_status()
                match = OPENHANDS_SESSION_KEY_RE.search(response.text)
                if match:
                    return match.group(1)
        except Exception:
            continue
    return None


def _project_context_docs(project_dir: Path) -> str:
    candidate_paths = [
        project_dir / 'README.md',
        project_dir / 'DEPLOY.md',
        project_dir / 'docs/cdc.md',
        project_dir / 'docs/mcd.md',
        project_dir / 'docs/architecture.md',
        project_dir / 'docs/roadmap.md',
        project_dir / 'docs/notes_synthese.md',
        project_dir / 'docs/implementation_plan.md',
        project_dir / 'docs/requirements_matrix.md',
    ]
    sections: list[str] = []
    for doc_path in candidate_paths:
        if not doc_path.exists() or not doc_path.is_file():
            continue
        try:
            relative = doc_path.relative_to(project_dir).as_posix()
            content = doc_path.read_text(encoding='utf-8', errors='ignore').strip()
        except Exception:
            continue
        if not content:
            continue
        sections.append(f'## {relative}\n\n{content[:4000].rstrip()}')
    if not sections:
        return ''
    return '\n\n'.join(sections)


def _build_project_seed_message(project_title: str, project_dir: Path, brief: str | None = None, deliverables: dict[str, Any] | None = None) -> str:
    seed = [
        f'You are OpenHands for the project `{project_title}`.',
        f'Workspace: `{project_dir}`',
        'Use this conversation as the canonical project workspace thread.',
        'Read the project context, then keep all changes inside the workspace.',
    ]
    context_docs = _project_context_docs(project_dir)
    if context_docs:
        seed.append('')
        seed.append('Project context documents:')
        seed.append(context_docs)
    deliverable_docs = _project_deliverable_docs(deliverables)
    if deliverable_docs:
        seed.append('')
        seed.append('Generated project documents:')
        seed.append(deliverable_docs)
    brief_text = _normalize_text(brief)
    if brief_text:
        seed.append('')
        seed.append('Initial brief:')
        seed.append(brief_text)
    return '\n'.join(seed).strip()


def _project_deliverable_docs(deliverables: dict[str, Any] | None) -> str:
    if not isinstance(deliverables, dict):
        return ''
    sections: list[str] = []
    for key, filename in [
        ('cdc', 'cdc.md'),
        ('mcd', 'mcd.md'),
        ('architecture', 'architecture.md'),
        ('roadmap', 'roadmap.md'),
        ('notes_synthese', 'notes_synthese.md'),
        ('implementation_plan', 'implementation_plan.md'),
        ('requirements_matrix', 'requirements_matrix.md'),
    ]:
        value = deliverables.get(key)
        if not isinstance(value, str):
            continue
        content = value.strip()
        if not content:
            continue
        sections.append(f'## deliverables/{filename}\n\n{content[:4000].rstrip()}')
    if not sections:
        return ''
    return '\n\n'.join(sections)


def _build_openhands_llm_payload() -> dict[str, Any] | None:
    model = _normalize_text(os.getenv('OPENHANDS_LLM_MODEL')) or _normalize_text(os.getenv('LLM_MODEL')) or 'gpt-5.5'
    api_key = (
        _normalize_text(os.getenv('OPENHANDS_LLM_API_KEY'))
        or _normalize_text(os.getenv('LLM_API_KEY'))
        or _normalize_text(os.getenv('OPENAI_API_KEY'))
        or None
    )
    base_url = _normalize_text(os.getenv('OPENHANDS_LLM_BASE_URL')) or _normalize_text(os.getenv('LLM_BASE_URL')) or None
    llm_payload: dict[str, Any] = {'model': model}
    if api_key:
        llm_payload['api_key'] = api_key
    if base_url:
        llm_payload['base_url'] = base_url
    return llm_payload


def _build_openhands_agent_payload() -> dict[str, Any]:
    llm_payload = _build_openhands_llm_payload() or {'model': 'gpt-5.5'}
    return {
        'kind': 'Agent',
        'llm': llm_payload,
        'tools': [
            {'name': 'terminal', 'params': {}},
            {'name': 'file_editor', 'params': {}},
            {'name': 'task_tracker', 'params': {}},
        ],
        'confirmation_policy': {'kind': 'NeverConfirm'},
        'system_prompt_kwargs': {'cli_mode': False},
    }


def _bootstrap_tag_value(seed_message: str) -> str:
    return hashlib.sha256(seed_message.encode('utf-8')).hexdigest()


async def ensure_project_conversation(
    project_id: str,
    project_title: str,
    project_dir: Path,
    brief: str | None = None,
    deliverables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent_server_url = _get_agent_server_url()
    public_url = _get_public_openhands_url()
    conversation_id = project_id
    public_base = public_url.rstrip('/') if public_url else None
    suggested_url = f'{public_base}/conversations/{conversation_id}' if public_base else None
    seed_message = _build_project_seed_message(project_title, project_dir, brief, deliverables)
    bootstrap_hash = _bootstrap_tag_value(seed_message)
    llm_payload = _build_openhands_llm_payload()

    session_api_key = await _get_session_api_key()
    if not session_api_key:
        return {
            'conversation_id': conversation_id,
            'suggested_url': suggested_url,
            'embed_url': suggested_url,
            'created': False,
            'notes': ['Impossible de récupérer la clé de session OpenHands.'],
        }

    headers = {'X-Session-API-Key': session_api_key}
    payload = {
        'conversation_id': conversation_id,
        'workspace': {'working_dir': str(project_dir), 'kind': 'LocalWorkspace'},
        'initial_message': {
            'role': 'user',
            'content': [{'type': 'text', 'text': seed_message}],
            'run': True,
        },
        'agent': _build_openhands_agent_payload(),
        'max_iterations': 1,
        'stuck_detection': True,
        'autotitle': True,
        'tags': {'aiabootstrap': bootstrap_hash},
    }

    async with httpx.AsyncClient(base_url=agent_server_url, timeout=30.0, follow_redirects=True, headers=headers) as client:
        response = await client.get(f'/api/conversations/{conversation_id}')
        if response.status_code == 404:
            create_response = await client.post('/api/conversations', json=payload)
            create_response.raise_for_status()
            conversation = create_response.json()
            created = True
        else:
            response.raise_for_status()
            conversation = response.json()
            created = False
            existing_tags = conversation.get('tags') if isinstance(conversation, dict) else {}
            if not isinstance(existing_tags, dict):
                existing_tags = {}

            if llm_payload and not conversation.get('current_model_id'):
                try:
                    llm_response = await client.post(
                        f'/api/conversations/{conversation_id}/switch_llm',
                        json={'llm': llm_payload},
                    )
                    llm_response.raise_for_status()
                except Exception:
                    pass

            if existing_tags.get('aiabootstrap') != bootstrap_hash:
                send_response = await client.post(
                    f'/api/conversations/{conversation_id}/events',
                    json={
                        'role': 'user',
                        'content': [{'type': 'text', 'text': seed_message}],
                        'run': True,
                    },
                )
                send_response.raise_for_status()
                new_tags = dict(existing_tags)
                new_tags['aiabootstrap'] = bootstrap_hash
                try:
                    tag_response = await client.patch(
                        f'/api/conversations/{conversation_id}',
                        json={'tags': new_tags},
                    )
                    tag_response.raise_for_status()
                except Exception:
                    pass

    workspace = conversation.get('workspace') if isinstance(conversation, dict) else None
    return {
        'conversation_id': conversation.get('id', conversation_id) if isinstance(conversation, dict) else conversation_id,
        'suggested_url': suggested_url,
        'embed_url': suggested_url,
        'created': created,
        'workspace': workspace,
        'notes': [f'Conversation OpenHands prête pour {project_title}.'],
    }

def _normalize_text(value: str | None) -> str:
    return (value or '').strip()


def _workspace_snapshot(project_dir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for file_path in sorted(project_dir.rglob('*')):
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(project_dir).as_posix()
            content = file_path.read_bytes()
            snapshot[rel] = hashlib.sha256(content).hexdigest()
        except Exception:
            continue
    return snapshot


def _build_instruction(project_title: str, brief: str, project_dir: Path) -> str:
    return f"""You are OpenHands working on the project `{project_title}`.

Constraints:
- Stay strictly inside this workspace: `{project_dir}`
- Do not modify files outside the repository root.
- Prefer the existing architecture and conventions of the project.
- If you need to inspect or edit files, use the workspace tools available to you.

User brief:
{brief}

After making the requested changes, summarize what you changed and any follow-up needed.
"""


def _resolve_llm_config() -> tuple[str, str | None, str | None]:
    model = _normalize_text(os.getenv('OPENHANDS_LLM_MODEL')) or _normalize_text(os.getenv('LLM_MODEL')) or 'gpt-5.2-codex'
    api_key = (
        _normalize_text(os.getenv('OPENHANDS_LLM_API_KEY'))
        or _normalize_text(os.getenv('LLM_API_KEY'))
        or _normalize_text(os.getenv('OPENAI_API_KEY'))
        or _normalize_text(os.getenv('ANTHROPIC_API_KEY'))
        or None
    )
    base_url = _normalize_text(os.getenv('OPENHANDS_LLM_BASE_URL')) or _normalize_text(os.getenv('LLM_BASE_URL')) or None
    return model, api_key, base_url


def _run_openhands_sync(project_dir: Path, instruction: str) -> None:
    from openhands.sdk import Agent, Conversation, LLM, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.task_tracker import TaskTrackerTool
    from openhands.tools.terminal import TerminalTool

    model, api_key, base_url = _resolve_llm_config()
    llm = LLM(model=model, api_key=api_key, base_url=base_url)
    agent = Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ],
    )
    conversation = Conversation(agent=agent, workspace=str(project_dir))
    conversation.send_message(instruction)
    conversation.run()


async def run_openhands_task(project_id: str, project_title: str, project_dir: Path, brief: str) -> dict[str, Any]:
    brief = _normalize_text(brief)
    if not brief:
        raise ValueError('Le brief OpenHands est vide.')

    instruction = _build_instruction(project_title, brief, project_dir)
    before = _workspace_snapshot(project_dir)
    await publish_project_event(project_id, {
        'type': 'implementation_status',
        'message': 'OpenHands a reçu la tâche et commence le travail dans le workspace local.',
    })

    try:
        await asyncio.to_thread(_run_openhands_sync, project_dir, instruction)
    except ModuleNotFoundError as exc:
        await publish_project_event(project_id, {
            'type': 'implementation_error',
            'message': 'OpenHands SDK indisponible dans le backend. Installe openhands-sdk et openhands-tools.',
            'error': str(exc),
        })
        raise
    except Exception as exc:
        await publish_project_event(project_id, {
            'type': 'implementation_error',
            'message': 'OpenHands a échoué pendant l’exécution de la tâche.',
            'error': str(exc),
        })
        raise

    after = _workspace_snapshot(project_dir)
    changed_files = sorted(set(before) ^ set(after))
    touched_count = len(changed_files)

    await publish_project_event(project_id, {
        'type': 'implementation_complete',
        'message': f'OpenHands a terminé la tâche. {touched_count} fichier(s) modifié(s) ou ajoutés.',
        'workspace': {
            'project_dir': str(project_dir),
            'repo_name': project_dir.name,
            'files': changed_files,
        },
    })

    return {
        'project_dir': str(project_dir),
        'changed_files': changed_files,
        'changed_file_count': touched_count,
    }
