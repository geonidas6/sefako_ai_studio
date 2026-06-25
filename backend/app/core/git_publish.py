from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_router import LLMRouter, PROVIDERS, decrypt_api_key, encrypt_api_key
from app.models.llm_config import LLMConfig
from app.models.git_integration import GitIntegration, GitRepositoryTarget
from app.models.project import Project


@dataclass
class GitConnectionState:
    enabled: bool
    provider: str
    username: str | None
    email: str | None
    has_token: bool
    default_branch: str


@dataclass
class GitRepoTargetState:
    id: str
    name: str
    repo_url: str
    default_branch: str
    is_active: bool


@dataclass
class GitHubConnectionState:
    connected: bool
    login: str | None
    name: str | None
    email: str | None
    avatar_url: str | None
    default_branch: str


@dataclass
class GitHubRepositoryState:
    name: str
    full_name: str
    clone_url: str
    html_url: str
    description: str | None
    private: bool
    default_branch: str


@dataclass
class GitHubCreateRepoState:
    name: str
    full_name: str
    clone_url: str
    html_url: str
    default_branch: str


@dataclass
class GitHubOAuthState:
    state: str
    expires_at: float


@dataclass
class GitHubOAuthCredentialsState:
    client_id: str | None
    has_client_secret: bool
    source: str


@dataclass
class CommitMessageGenerationState:
    provider: str
    model: str
    source: str


class GitPublishError(RuntimeError):
    pass


class GitHubOAuthError(RuntimeError):
    pass


_GITHUB_OAUTH_STATES: dict[str, GitHubOAuthState] = {}
_GITHUB_OAUTH_METADATA_KEY = "oauth"
_GITHUB_PROFILE_METADATA_KEY = "profile"
COMMIT_MESSAGE_CONFIG_KEY = "git_commit_message"


def _mask_token(url: str) -> str:
    if not url:
        return url
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def _sanitize_branch_name(branch: str | None, fallback: str = "main") -> str:
    candidate = (branch or fallback or "main").strip()
    candidate = re.sub(r"[^A-Za-z0-9._/-]+", "-", candidate)
    candidate = candidate.strip("-")
    return candidate or "main"


def _github_api_base() -> str:
    return "https://api.github.com"


def _github_authorize_base() -> str:
    return "https://github.com/login/oauth/authorize"


def _github_token_base() -> str:
    return "https://github.com/login/oauth/access_token"


def _github_redirect_uri() -> str:
    return f"https://{settings.api_domain}/api/admin/github/oauth/callback"


def _frontend_admin_url(*, github_status: str | None = None) -> str:
    url = f"https://{settings.frontend_domain}/admin"
    if github_status:
        return f"{url}?github={quote(github_status, safe='')}"
    return url


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sefako-ai-studio",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_request_sync(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    url = path if path.startswith("http://") or path.startswith("https://") else f"{_github_api_base()}{path}"
    body = None
    headers = _github_headers(token)
    headers.update(extra_headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            if not raw:
                return {}
            return json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        try:
            parsed = json.loads(detail or "{}")
            message = parsed.get("message") or detail
        except Exception:
            message = detail or str(exc)
        raise GitPublishError(f"GitHub API error ({exc.code}): {message}") from exc
    except URLError as exc:
        raise GitPublishError(f"GitHub API inaccessible: {exc.reason}") from exc


async def _github_request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    return await asyncio.to_thread(
        _github_request_sync,
        method,
        path,
        token=token,
        payload=payload,
        extra_headers=extra_headers,
    )


def _github_oauth_state_cleanup() -> None:
    now = datetime.now(timezone.utc).timestamp()
    expired = [key for key, value in _GITHUB_OAUTH_STATES.items() if value.expires_at < now]
    for key in expired:
        _GITHUB_OAUTH_STATES.pop(key, None)


def create_github_oauth_state() -> str:
    _github_oauth_state_cleanup()
    state = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc).timestamp() + 600
    _GITHUB_OAUTH_STATES[state] = GitHubOAuthState(state=state, expires_at=expires_at)
    return state


def consume_github_oauth_state(state: str) -> bool:
    _github_oauth_state_cleanup()
    return _GITHUB_OAUTH_STATES.pop(state, None) is not None


def _normalize_metadata_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _get_integration_oauth_payload(integration: GitIntegration | None) -> dict[str, Any]:
    if integration is None:
        return {}
    payload = _normalize_metadata_payload(integration.profile_json)
    oauth = payload.get(_GITHUB_OAUTH_METADATA_KEY)
    return oauth if isinstance(oauth, dict) else {}


def _get_integration_profile_payload(integration: GitIntegration | None) -> dict[str, Any]:
    if integration is None:
        return {}
    payload = _normalize_metadata_payload(integration.profile_json)
    profile = payload.get(_GITHUB_PROFILE_METADATA_KEY)
    return profile if isinstance(profile, dict) else {}


async def get_github_oauth_credentials(db: AsyncSession) -> GitHubOAuthCredentialsState:
    integration = await _get_git_integration(db)
    oauth = _get_integration_oauth_payload(integration)
    client_id = str(oauth.get("client_id") or "").strip() or None
    has_client_secret = bool(str(oauth.get("client_secret_encrypted") or "").strip())
    if client_id:
        return GitHubOAuthCredentialsState(client_id=client_id, has_client_secret=has_client_secret, source="database")
    return GitHubOAuthCredentialsState(
        client_id=settings.github_oauth_client_id.strip() or None,
        has_client_secret=bool(settings.github_oauth_client_secret.strip()),
        source="environment",
    )


async def get_github_oauth_secret(db: AsyncSession) -> str | None:
    integration = await _get_git_integration(db)
    oauth = _get_integration_oauth_payload(integration)
    encrypted = str(oauth.get("client_secret_encrypted") or "").strip()
    if encrypted:
        try:
            return decrypt_api_key(encrypted)
        except Exception:
            return None
    secret = settings.github_oauth_client_secret.strip()
    return secret or None


def build_github_oauth_url(state: str, client_id: str | None = None) -> str:
    resolved_client_id = (client_id or settings.github_oauth_client_id or "").strip()
    if not resolved_client_id:
        raise GitHubOAuthError("Le client_id GitHub OAuth n'est pas configuré.")
    query = urlencode({
        "client_id": resolved_client_id,
        "redirect_uri": _github_redirect_uri(),
        "scope": "repo read:user user:email",
        "state": state,
        "allow_signup": "true",
    })
    return f"{_github_authorize_base()}?{query}"


async def exchange_github_oauth_code(code: str, *, client_id: str | None = None, client_secret: str | None = None) -> str:
    resolved_client_id = (client_id or settings.github_oauth_client_id or "").strip()
    resolved_client_secret = (client_secret or settings.github_oauth_client_secret or "").strip()
    if not resolved_client_id or not resolved_client_secret:
        raise GitHubOAuthError("La configuration GitHub OAuth est incomplète.")
    payload = urlencode({
        "client_id": resolved_client_id,
        "client_secret": resolved_client_secret,
        "code": code,
        "redirect_uri": _github_redirect_uri(),
    }).encode("utf-8")

    def _exchange() -> dict[str, Any]:
        request = Request(
            _github_token_base(),
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "sefako-ai-studio",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                return json.loads(raw or "{}")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            try:
                parsed = json.loads(detail or "{}")
                message = parsed.get("error_description") or parsed.get("error") or detail
            except Exception:
                message = detail or str(exc)
            raise GitHubOAuthError(f"GitHub OAuth error ({exc.code}): {message}") from exc
        except URLError as exc:
            raise GitHubOAuthError(f"GitHub OAuth inaccessible: {exc.reason}") from exc

    response = await asyncio.to_thread(_exchange)
    token = str(response.get("access_token") or "").strip()
    if not token:
        raise GitHubOAuthError("Impossible d'obtenir un access token GitHub.")
    return token


async def fetch_github_user_profile(token: str) -> dict[str, Any]:
    user = await _github_request("GET", "/user", token=token)
    emails = await _github_request("GET", "/user/emails", token=token)
    primary_email = None
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("primary") and item.get("verified"):
                primary_email = item.get("email")
                break
    if primary_email is None and isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("email"):
                primary_email = item.get("email")
                break
    login = str(user.get("login") or "").strip() or None
    if not primary_email and login:
        primary_email = f"{login}@users.noreply.github.com"
    return {
        "login": login,
        "name": str(user.get("name") or "").strip() or None,
        "email": str(primary_email or user.get("email") or "").strip() or None,
        "avatar_url": str(user.get("avatar_url") or "").strip() or None,
    }


async def fetch_github_repositories(token: str) -> list[GitHubRepositoryState]:
    repos: list[GitHubRepositoryState] = []
    page = 1
    while True:
        response = await _github_request(
            "GET",
            f"/user/repos?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator,organization_member",
            token=token,
        )
        if not isinstance(response, list) or not response:
            break
        for item in response:
            if not isinstance(item, dict):
                continue
            repos.append(GitHubRepositoryState(
                name=str(item.get("name") or "").strip(),
                full_name=str(item.get("full_name") or "").strip(),
                clone_url=str(item.get("clone_url") or "").strip(),
                html_url=str(item.get("html_url") or "").strip(),
                description=str(item.get("description") or "").strip() or None,
                private=bool(item.get("private")),
                default_branch=str(item.get("default_branch") or "main").strip() or "main",
            ))
        if len(response) < 100:
            break
        page += 1
    return repos


async def create_github_repository(
    token: str,
    *,
    name: str,
    description: str | None = None,
    private: bool = True,
) -> GitHubCreateRepoState:
    response = await _github_request(
        "POST",
        "/user/repos",
        token=token,
        payload={
            "name": name,
            "description": description or "",
            "private": bool(private),
            "auto_init": False,
        },
    )
    return GitHubCreateRepoState(
        name=str(response.get("name") or name).strip() or name,
        full_name=str(response.get("full_name") or "").strip(),
        clone_url=str(response.get("clone_url") or "").strip(),
        html_url=str(response.get("html_url") or "").strip(),
        default_branch=str(response.get("default_branch") or "main").strip() or "main",
    )


def _build_authenticated_remote_url(repo_url: str, username: str | None, token: str | None) -> str:
    candidate = (repo_url or "").strip()
    if not candidate:
        raise GitPublishError("URL du dépôt Git manquante.")
    if candidate.startswith("git@") or candidate.startswith("ssh://"):
        return candidate

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return candidate

    hostname = parsed.hostname or parsed.netloc
    auth_username = (username or "oauth2").strip() or "oauth2"
    auth_password = (token or "").strip()
    if not auth_password:
        return candidate

    netloc = f"{quote(auth_username, safe='')}:{quote(auth_password, safe='')}@{hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


async def _run_git(args: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **(env or {})},
    )
    stdout, stderr = await process.communicate()
    out = stdout.decode(errors="ignore").strip()
    err = stderr.decode(errors="ignore").strip()
    if process.returncode != 0:
        raise GitPublishError(err or out or f"git {' '.join(args)} a échoué.")
    return out, err


async def _ensure_git_repository(cwd: Path, branch: str) -> None:
    git_dir = cwd / ".git"
    if not git_dir.exists():
        await _run_git(["init"], cwd)
    await _run_git(["checkout", "-B", branch], cwd)


async def _get_git_integration(db: AsyncSession) -> GitIntegration | None:
    result = await db.execute(select(GitIntegration).order_by(GitIntegration.updated_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def get_git_connection_state(db: AsyncSession) -> GitConnectionState:
    integration = await _get_git_integration(db)
    if integration is None:
        return GitConnectionState(
            enabled=False,
            provider="github",
            username=None,
            email=None,
            has_token=False,
            default_branch="main",
        )
    return GitConnectionState(
        enabled=bool(integration.is_enabled),
        provider=integration.provider or "github",
        username=integration.username,
        email=integration.email,
        has_token=bool(integration.token_encrypted),
        default_branch=integration.default_branch or "main",
    )


async def get_github_connection_state(db: AsyncSession) -> GitHubConnectionState:
    integration = await _get_git_integration(db)
    if integration is None:
        return GitHubConnectionState(
            connected=False,
            login=None,
            name=None,
            email=None,
            avatar_url=None,
            default_branch="main",
        )
    metadata = _get_integration_profile_payload(integration)
    return GitHubConnectionState(
        connected=bool(integration.is_enabled and integration.token_encrypted),
        login=integration.username,
        name=metadata.get("name"),
        email=integration.email,
        avatar_url=metadata.get("avatar_url"),
        default_branch=integration.default_branch or "main",
    )


async def save_git_connection_state(
    db: AsyncSession,
    *,
    provider: str = "github",
    username: str | None = None,
    email: str | None = None,
    token: str | None = None,
    default_branch: str = "main",
    is_enabled: bool = False,
    metadata: dict[str, Any] | None = None,
) -> GitConnectionState:
    result = await db.execute(select(GitIntegration).order_by(GitIntegration.updated_at.desc()).limit(1))
    integration = result.scalar_one_or_none()
    if integration is None:
        integration = GitIntegration()
        db.add(integration)

    integration.provider = (provider or "github").strip() or "github"
    integration.username = (username or "").strip() or None
    integration.email = (email or "").strip() or None
    integration.default_branch = _sanitize_branch_name(default_branch, "main")
    integration.is_enabled = bool(is_enabled)
    if token and token.strip():
        integration.token_encrypted = encrypt_api_key(token.strip())
    if metadata is not None:
        existing_payload = _normalize_metadata_payload(integration.profile_json)
        existing_payload[_GITHUB_PROFILE_METADATA_KEY] = metadata
        if _GITHUB_OAUTH_METADATA_KEY not in existing_payload:
            existing_payload[_GITHUB_OAUTH_METADATA_KEY] = _get_integration_oauth_payload(integration)
        integration.profile_json = json.dumps(existing_payload, ensure_ascii=True)
    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(integration)
    return GitConnectionState(
        enabled=bool(integration.is_enabled),
        provider=integration.provider,
        username=integration.username,
        email=integration.email,
        has_token=bool(integration.token_encrypted),
        default_branch=integration.default_branch,
    )


async def disconnect_github(db: AsyncSession) -> GitConnectionState:
    integration = await _get_git_integration(db)
    if integration is None:
        return GitConnectionState(enabled=False, provider="github", username=None, email=None, has_token=False, default_branch="main")
    integration.token_encrypted = None
    integration.is_enabled = False
    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return GitConnectionState(
        enabled=False,
        provider=integration.provider or "github",
        username=integration.username,
        email=integration.email,
        has_token=False,
        default_branch=integration.default_branch or "main",
    )


async def save_github_profile(
    db: AsyncSession,
    *,
    token: str,
    profile: dict[str, Any],
) -> GitConnectionState:
    return await save_git_connection_state(
        db,
        provider="github",
        username=str(profile.get("login") or "").strip() or None,
        email=str(profile.get("email") or "").strip() or None,
        token=token,
        default_branch="main",
        is_enabled=True,
        metadata=profile,
    )


async def save_github_oauth_credentials(
    db: AsyncSession,
    *,
    client_id: str,
    client_secret: str | None = None,
) -> GitHubOAuthCredentialsState:
    integration = await _get_git_integration(db)
    if integration is None:
        integration = GitIntegration(provider="github")
        db.add(integration)

    payload = _normalize_metadata_payload(integration.profile_json)
    oauth_payload = payload.get(_GITHUB_OAUTH_METADATA_KEY) if isinstance(payload.get(_GITHUB_OAUTH_METADATA_KEY), dict) else {}
    oauth_payload = dict(oauth_payload or {})
    oauth_payload["client_id"] = client_id.strip() or None
    if client_secret is not None:
        secret = client_secret.strip()
        oauth_payload["client_secret_encrypted"] = encrypt_api_key(secret) if secret else None
    payload[_GITHUB_OAUTH_METADATA_KEY] = oauth_payload
    if _GITHUB_PROFILE_METADATA_KEY not in payload:
        payload[_GITHUB_PROFILE_METADATA_KEY] = {}
    integration.profile_json = json.dumps(payload, ensure_ascii=True)
    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(integration)
    return GitHubOAuthCredentialsState(
        client_id=str(oauth_payload.get("client_id") or "").strip() or None,
        has_client_secret=bool(str(oauth_payload.get("client_secret_encrypted") or "").strip()),
        source="database",
    )


def _normalize_commit_provider(provider: str | None) -> str:
    candidate = (provider or "").strip()
    if candidate in PROVIDERS:
        return candidate
    return "gemini"


def _normalize_commit_model(provider: str, model: str | None) -> str:
    models = PROVIDERS.get(provider, {}).get("models", [])
    candidate = (model or "").strip()
    if candidate and candidate in models:
        return candidate
    return str(PROVIDERS.get(provider, {}).get("default_model") or "gpt-4o").strip() or "gpt-4o"


async def get_commit_message_generation_state(db: AsyncSession) -> CommitMessageGenerationState:
    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == COMMIT_MESSAGE_CONFIG_KEY))
    cfg = result.scalar_one_or_none()
    provider = _normalize_commit_provider(cfg.value if cfg else None)
    model = _normalize_commit_model(provider, cfg.active_model if cfg else None)
    return CommitMessageGenerationState(
        provider=provider,
        model=model,
        source="database" if cfg else "default",
    )


async def save_commit_message_generation_state(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
) -> CommitMessageGenerationState:
    normalized_provider = _normalize_commit_provider(provider)
    normalized_model = _normalize_commit_model(normalized_provider, model)

    result = await db.execute(select(LLMConfig).where(LLMConfig.provider == COMMIT_MESSAGE_CONFIG_KEY))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = LLMConfig(provider=COMMIT_MESSAGE_CONFIG_KEY)
        db.add(cfg)
    cfg.value = normalized_provider
    cfg.active_model = normalized_model
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return CommitMessageGenerationState(
        provider=normalized_provider,
        model=normalized_model,
        source="database",
    )


async def list_git_repo_targets(db: AsyncSession) -> list[GitRepoTargetState]:
    result = await db.execute(select(GitRepositoryTarget).where(GitRepositoryTarget.is_active.is_(True)).order_by(GitRepositoryTarget.updated_at.desc()))
    return [
        GitRepoTargetState(
            id=item.id,
            name=item.name,
            repo_url=item.repo_url,
            default_branch=item.default_branch,
            is_active=bool(item.is_active),
        )
        for item in result.scalars().all()
    ]


async def add_git_repo_target(
    db: AsyncSession,
    *,
    name: str,
    repo_url: str | None = None,
    repo_full_name: str | None = None,
    default_branch: str,
) -> GitRepoTargetState:
    normalized_repo_url = (repo_url or "").strip()
    normalized_repo_full_name = (repo_full_name or "").strip()
    if not normalized_repo_url and normalized_repo_full_name:
        normalized_repo_url = f"https://github.com/{normalized_repo_full_name}.git"
    target = GitRepositoryTarget(
        name=(name or "").strip()[:256],
        repo_url=normalized_repo_url,
        default_branch=_sanitize_branch_name(default_branch, "main"),
        is_active=True,
    )
    if not target.name:
        raise GitPublishError("Le nom du repo cible est requis.")
    if not target.repo_url:
        raise GitPublishError("L'URL du repo cible est requise.")
    db.add(target)
    await db.commit()
    await db.refresh(target)
    return GitRepoTargetState(
        id=target.id,
        name=target.name,
        repo_url=target.repo_url,
        default_branch=target.default_branch,
        is_active=bool(target.is_active),
    )


def get_project_git_selection(project: Project) -> dict[str, Any]:
    deliverables = dict(project.final_deliverables or {})
    selection = deliverables.get("git_publish")
    return selection if isinstance(selection, dict) else {}


async def set_project_git_target(
    db: AsyncSession,
    project: Project,
    *,
    target_id: str,
    branch: str | None = None,
) -> dict[str, Any]:
    target = await db.get(GitRepositoryTarget, target_id)
    if target is None or not target.is_active:
        raise GitPublishError("Repo cible introuvable ou désactivé.")

    deliverables = dict(project.final_deliverables or {})
    deliverables["git_publish"] = {
        "target_id": target.id,
        "target_name": target.name,
        "repo_url": target.repo_url,
        "branch": _sanitize_branch_name(branch, target.default_branch),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_commit_sha": deliverables.get("git_publish", {}).get("last_commit_sha") if isinstance(deliverables.get("git_publish"), dict) else None,
        "last_commit_message": deliverables.get("git_publish", {}).get("last_commit_message") if isinstance(deliverables.get("git_publish"), dict) else None,
    }
    project.final_deliverables = deliverables
    await db.commit()
    await db.refresh(project)
    return deliverables["git_publish"]


async def _generate_commit_message(
    db: AsyncSession,
    *,
    project: Project,
    changed_files: list[str],
    status_lines: list[str],
) -> str:
    summary = "\n".join(status_lines[:30]).strip()
    file_list = "\n".join(f"- {path}" for path in changed_files[:25]) or "- (aucun fichier détecté)"
    prompt = f"""
Tu génères un message de commit Git concis et utile.
Retourne uniquement une ligne, sans guillemets, sans liste, sans bloc Markdown.
La ligne doit idéalement suivre le format conventional commits.
Maximum 72 caractères si possible.

Projet: {project.title}
Résumé des changements:
{summary or "- changements de workspace"}

Fichiers concernés:
{file_list}
""".strip()

    llm_router = LLMRouter(db)
    commit_settings = await get_commit_message_generation_state(db)
    try:
        response = await llm_router.generate_with_provider(
            commit_settings.provider,
            commit_settings.model,
            prompt=prompt,
            system_prompt="Tu rédiges des messages de commit git courts, précis et professionnels.",
        )
        candidate = (response or "").strip().splitlines()[0].strip().strip('"').strip("'")
        candidate = candidate[:120].strip()
        if candidate:
            return candidate
    except Exception:
        pass

    if changed_files:
        primary = changed_files[0]
        if len(changed_files) == 1:
            return f"chore: update {primary}"
        return f"chore: sync {len(changed_files)} workspace files"
    return "chore: sync workspace"


async def push_workspace_to_git(
    db: AsyncSession,
    *,
    project: Project,
    project_dir: Path,
    target: GitRepositoryTarget,
    integration: GitIntegration,
    branch_override: str | None = None,
) -> dict[str, Any]:
    if not project_dir.exists():
        raise GitPublishError("Workspace projet introuvable.")

    branch = _sanitize_branch_name(branch_override, target.default_branch or integration.default_branch or "main")
    await _ensure_git_repository(project_dir, branch)

    remote_url = _build_authenticated_remote_url(
        target.repo_url,
        integration.username,
        decrypt_api_key(integration.token_encrypted) if integration.token_encrypted else None,
    )

    if not integration.email:
        raise GitPublishError("Une adresse email Git est requise pour créer le commit.")

    await _run_git(["config", "user.name", integration.username or "AIA Studio"], project_dir)
    await _run_git(["config", "user.email", integration.email], project_dir)

    remotes_out, _ = await _run_git(["remote"], project_dir)
    if "origin" in remotes_out.split():
        await _run_git(["remote", "set-url", "origin", remote_url], project_dir)
    else:
        await _run_git(["remote", "add", "origin", remote_url], project_dir)

    await _run_git(["add", "-A"], project_dir)
    status_out, _ = await _run_git(["status", "--porcelain"], project_dir)
    status_lines = [line for line in status_out.splitlines() if line.strip()]
    if not status_lines:
        return {
            "pushed": False,
            "changed_files": [],
            "branch": branch,
            "remote_url": _mask_token(target.repo_url),
            "message": "Aucun changement à pousser.",
        }

    changed_files = []
    for line in status_lines:
        if len(line) > 3:
            changed_files.append(line[3:].strip())

    commit_message = await _generate_commit_message(
        db,
        project=project,
        changed_files=changed_files,
        status_lines=status_lines,
    )

    await _run_git(["commit", "-m", commit_message], project_dir)
    commit_sha, _ = await _run_git(["rev-parse", "HEAD"], project_dir)
    await _run_git(["push", "-u", "origin", f"HEAD:{branch}"], project_dir)

    deliverables = dict(project.final_deliverables or {})
    git_publish = dict(deliverables.get("git_publish") or {})
    git_publish.update({
        "target_id": target.id,
        "target_name": target.name,
        "repo_url": target.repo_url,
        "branch": branch,
        "last_commit_sha": commit_sha.strip(),
        "last_commit_message": commit_message,
        "last_pushed_at": datetime.now(timezone.utc).isoformat(),
    })
    deliverables["git_publish"] = git_publish
    project.final_deliverables = deliverables
    await db.commit()

    return {
        "pushed": True,
        "branch": branch,
        "commit_sha": commit_sha.strip(),
        "commit_message": commit_message,
        "remote_url": _mask_token(target.repo_url),
        "changed_files": changed_files,
    }
