from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.core.project_workspace import generate_application_foundation


async def test_workspace_generates_documents_only() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        project_dir = Path(tmp_dir) / "demo-project"
        result = await generate_application_foundation(
            project_dir=str(project_dir),
            project_id="demo-123",
            project_title="Mon Projet Test",
            input_text=(
                "Backend FastAPI, frontend React, base PostgreSQL, "
                "sans application mobile. Le studio doit produire les documents Markdown."
            ),
            deliverables={
                "cdc": "Un super projet de cadrage documentaire.",
                "architecture": "FastAPI + React + PostgreSQL.",
                "roadmap": "Phase 1: cadrage",
            },
            llm_router=None,
        )

        generated_files = result["files"]
        assert generated_files, "Le workspace doit produire au moins un fichier documentaire."
        assert all("backend/" not in path and "frontend/" not in path for path in generated_files)
        assert any(path.endswith("README.md") for path in generated_files)
        assert any(path.endswith("docs/architecture.md") for path in generated_files)
        assert any(path.endswith("docs/global_environment.md") for path in generated_files)
        assert any(path.endswith("docs/stack_decision.md") for path in generated_files)
        assert any(path.endswith("docs/user_stories.md") for path in generated_files)
        assert any(path.endswith("docs/functional_spec.md") for path in generated_files)
        assert any(path.endswith("docs/interface_spec.md") for path in generated_files)
        assert any(path.endswith("docs/mld.md") for path in generated_files)
        assert any(path.endswith("docs/api_contract.md") for path in generated_files)
        assert any(path.endswith("docs/ide_generation_prompt.md") for path in generated_files)

        readme = (project_dir / "README.md").read_text(encoding="utf-8")
        global_environment = (project_dir / "docs/global_environment.md").read_text(encoding="utf-8")
        architecture = (project_dir / "docs/architecture.md").read_text(encoding="utf-8")
        ide_prompt = (project_dir / "docs/ide_generation_prompt.md").read_text(encoding="utf-8")
        user_stories = (project_dir / "docs/user_stories.md").read_text(encoding="utf-8")
        functional_spec = (project_dir / "docs/functional_spec.md").read_text(encoding="utf-8")
        interface_spec = (project_dir / "docs/interface_spec.md").read_text(encoding="utf-8")
        mld = (project_dir / "docs/mld.md").read_text(encoding="utf-8")
        api_contract = (project_dir / "docs/api_contract.md").read_text(encoding="utf-8")

        assert "éditeur web" in readme.lower()
        assert "markdown" in readme.lower()
        assert "docker_manager" in global_environment
        assert "traefik_master" in global_environment
        assert "portfolio_grace" in global_environment
        assert "kaba-compta" in global_environment
        assert "couches" in architecture.lower() or "couche" in architecture.lower()
        assert "proxy_net" in architecture
        assert "postgresql" in architecture.lower()
        assert "user stories" in user_stories.lower()
        assert "fonctionnal" in functional_spec.lower()
        assert "écran" in interface_spec.lower() or "ecran" in interface_spec.lower()
        assert "mld" in mld.lower()
        assert "endpoint" in api_contract.lower()
        assert "user stories" in ide_prompt.lower()
        assert "mld" in ide_prompt.lower()
        assert "contrats api" in ide_prompt.lower()


def main() -> None:
    asyncio.run(test_workspace_generates_documents_only())
    print("Les documents de cadrage sont générés sans code applicatif.")


if __name__ == "__main__":
    main()
