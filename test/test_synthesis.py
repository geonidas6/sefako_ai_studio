import asyncio
import sys
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Import from our application packages
from app.core.config import settings
from app.core.llm_router import LLMRouter
from app.agents.orchestrator import make_synthesis_prompt, SYSTEM_PROMPTS
from app.models.project import Project

async def test_synthesis():
    print("Connecting to database...")
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("Fetching project...")
        project_id = "0185d095-8373-4f4d-bfda-ef4fffa03239"
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()

        if not project:
            print("Project not found in DB!")
            return

        print(f"Project Title: {project.title}")
        
        # Prepare inputs
        r1 = {
            "strategy": project.strategy_r1 or "",
            "ux": project.ux_r1 or "",
            "engineering": project.engineering_r1 or "",
            "devops": project.devops_r1 or "",
        }
        critiques = dict(project.critiques or {})

        prompt = make_synthesis_prompt(project.input_text, r1, critiques)
        print("Prompt prepared (length:", len(prompt), ")")

        # Initialize LLM Router
        router = LLMRouter(db)
        
        # Call generate
        print("Calling LLM Router generate for orchestrator...")
        try:
            raw_response = await router.generate(
                prompt,
                "orchestrator",
                SYSTEM_PROMPTS["orchestrator"]
            )
            print("--- LLM RESPONSE START ---")
            print(raw_response)
            print("--- LLM RESPONSE END ---")
            
            # Clean and parse JSON
            clean = raw_response.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
                if clean.endswith("```"):
                    clean = clean[:-3]
            try:
                deliverables = json.loads(clean.strip())
                print("Success! JSON parsed correctly.")
                print("Keys found:", list(deliverables.keys()))
            except Exception as e:
                print("Failed to parse JSON response:", e)

        except Exception as e:
            print("Error during generation:", e)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_synthesis())
