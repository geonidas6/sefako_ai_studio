#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
DEST_ROOT="${2:-/opt}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project_id> [destination_root]" >&2
  exit 1
fi

if [[ "$DEST_ROOT" != "/opt" && "$DEST_ROOT" != /opt/* ]]; then
  echo "Destination refusee: $DEST_ROOT" >&2
  echo "Seul /opt ou un sous-dossier de /opt est autorise." >&2
  exit 1
fi

BACKEND_CONTAINER="$(docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml ps -q backend 2>/dev/null || true)"
if [[ -z "$BACKEND_CONTAINER" ]]; then
  BACKEND_CONTAINER="$(docker compose -f docker-compose.yml -f docker-compose.traefik.yml ps -q backend 2>/dev/null || true)"
fi

if [[ -z "$BACKEND_CONTAINER" ]]; then
  echo "Conteneur backend introuvable. Lance cette commande depuis /opt/sefako_ai_studio." >&2
  exit 1
fi

CONTAINER_WORKSPACE="$(docker exec -i "$BACKEND_CONTAINER" python - "$PROJECT_ID" <<'PY'
import asyncio
import sys
from pathlib import Path
from sqlalchemy import select

from app.core.project_workspace import IMPLEMENTATION_PIPELINE_KEY, IMPLEMENTATION_WORKSPACE_KEY
from app.db.database import AsyncSessionLocal
from app.models.project import Project

project_id = sys.argv[1]

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise SystemExit("PROJECT_NOT_FOUND")

        deliverables = dict(project.final_deliverables or {})
        workspace = deliverables.get(IMPLEMENTATION_WORKSPACE_KEY)
        project_dir = workspace.get("project_dir") if isinstance(workspace, dict) else None

        if not project_dir:
            pipeline = deliverables.get(IMPLEMENTATION_PIPELINE_KEY)
            project_dir = pipeline.get("project_dir") if isinstance(pipeline, dict) else None

        if not project_dir:
            raise SystemExit("WORKSPACE_NOT_FOUND")

        path = Path(project_dir).resolve()
        if not str(path).startswith("/projects/"):
            raise SystemExit("WORKSPACE_OUTSIDE_PROJECTS")

        print(path)

asyncio.run(main())
PY
)"
CONTAINER_WORKSPACE="$(printf '%s
' "$CONTAINER_WORKSPACE" | awk '/^\/projects\// { value = $0 } END { print value }')"

if [[ -z "$CONTAINER_WORKSPACE" ]]; then
  echo "Workspace introuvable dans le conteneur backend." >&2
  exit 1
fi

REPO_NAME="$(basename "$CONTAINER_WORKSPACE")"
if [[ -z "$REPO_NAME" || "$REPO_NAME" == "." || "$REPO_NAME" == ".." || "$REPO_NAME" == */* ]]; then
  echo "Nom de repo invalide: $REPO_NAME" >&2
  exit 1
fi

DEST_ROOT="${DEST_ROOT%/}"
DEST_PATH="$DEST_ROOT/$REPO_NAME"

if [[ -e "$DEST_PATH" ]]; then
  echo "Destination deja existante: $DEST_PATH" >&2
  echo "Ecrasement en cours..." >&2
  rm -rf "$DEST_PATH"
fi

mkdir -p "$DEST_ROOT"
docker cp "$BACKEND_CONTAINER:$CONTAINER_WORKSPACE" "$DEST_ROOT/"
chmod -R u+rwX,go+rX "$DEST_PATH"

echo "Workspace exporte vers $DEST_PATH"
