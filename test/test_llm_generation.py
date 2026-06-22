import asyncio
import json
from pathlib import Path
from typing import Any

from app.core.project_workspace import (
    _parse_json_response,
    _backend_file_specs,
    _frontend_file_specs,
    generate_application_foundation
)

def test_parse_json_response():
    print("Testing _parse_json_response...")
    
    # Test 1: JSON parfait
    raw1 = '{"files": [{"path": "backend/app/main.py", "content": "print(\'hello\')"}]}'
    res1 = _parse_json_response(raw1)
    assert res1 is not None
    assert res1["files"][0]["path"] == "backend/app/main.py"
    print("Test 1 OK")
    
    # Test 2: JSON enveloppé de markdown triple backticks
    raw2 = """```json
{
  "files": [
    {"path": "backend/Dockerfile", "content": "FROM python"}
  ]
}
```"""
    res2 = _parse_json_response(raw2)
    assert res2 is not None
    assert res2["files"][0]["path"] == "backend/Dockerfile"
    print("Test 2 OK")

    # Test 3: Texte avant/après le JSON
    raw3 = """Voici la réponse demandée:
{
  "files": [
    {"path": "test.txt", "content": "ok"}
  ]
}
Et voilà."""
    res3 = _parse_json_response(raw3)
    assert res3 is not None
    assert res3["files"][0]["path"] == "test.txt"
    print("Test 3 OK")

async def test_fallback_specs():
    print("Testing fallback specs generation...")
    project_title = "Mon Projet Test"
    deliverables = {
        "cdc": "Un super projet",
        "architecture": "FastAPI + Next.js",
        "roadmap": "Phase 1: MVP"
    }
    stack = {
        "backend": "fastapi",
        "frontend": "nextjs",
        "generation_backend": "fastapi",
        "generation_frontend": "nextjs"
    }
    
    # Test sans llm_router (fallback sur templates statiques)
    backend_specs = await _backend_file_specs(project_title, deliverables, stack, llm_router=None)
    assert len(backend_specs) > 0
    assert any(path == "backend/app/main.py" for path, _ in backend_specs)
    print("Backend Fallback OK")

    frontend_specs = await _frontend_file_specs(project_title, deliverables, stack, llm_router=None)
    assert len(frontend_specs) > 0
    assert any(path == "frontend/app/page.tsx" for path, _ in frontend_specs)
    print("Frontend Fallback OK")

class MockLLMRouter:
    def __init__(self, response_text: str):
        self.response_text = response_text
    async def generate(self, prompt: str, agent_type: str, system_prompt: str = "") -> str:
        return self.response_text

async def test_llm_generation_with_router():
    print("Testing generate_application_foundation with a mock LLMRouter...")
    
    # Réponse simulée du LLM pour le backend
    mock_backend_json = """{
      "files": [
        {"path": "backend/Dockerfile", "content": "FROM python:3.11-slim"},
        {"path": "backend/app/main.py", "content": "# Code FastAPI généré par l'IA\\nprint('App active')\\n"}
      ]
    }"""
    
    # Création d'un mock router
    mock_router = MockLLMRouter(mock_backend_json)
    
    project_title = "Mon Projet Test"
    deliverables = {"cdc": "Un super projet"}
    stack = {"backend": "fastapi"}
    
    backend_specs = await _backend_file_specs(project_title, deliverables, stack, llm_router=mock_router)
    
    assert len(backend_specs) == 2
    assert backend_specs[0][0] == "backend/Dockerfile"
    assert "FROM python:3.11-slim" in backend_specs[0][1]
    assert backend_specs[1][0] == "backend/app/main.py"
    assert "App active" in backend_specs[1][1]
    print("Mock LLMRouter specs generation OK")

async def main():
    test_parse_json_response()
    await test_fallback_specs()
    await test_llm_generation_with_router()
    print("Tous les tests de génération de code ont réussi !")

if __name__ == "__main__":
    asyncio.run(main())
