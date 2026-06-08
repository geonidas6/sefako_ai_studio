"""
LangGraph Orchestrator — 3-round multi-agent workflow.

Round 1: 4 agents produce initial analysis in parallel.
Round 2: Each agent critiques the others.
Round 3: Orchestrator synthesizes into final deliverables.

Events are streamed via asyncio.Queue for WebSocket delivery.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TypedDict, Optional, Any

from langgraph.graph import StateGraph, START, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_router import LLMRouter


# ──────────────────────────────────────────────
# State definition
# ──────────────────────────────────────────────

class AiaState(TypedDict):
    project_id: str
    input_text: str
    # Round 1 outputs
    strategy_r1: str
    ux_r1: str
    engineering_r1: str
    devops_r1: str
    # Round 2 critiques
    strategy_critique: str
    ux_critique: str
    engineering_critique: str
    devops_critique: str
    # Final
    final_deliverables: dict
    error: Optional[str]


# ──────────────────────────────────────────────
# System prompts
# ──────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "strategy": """Tu es le Département Stratégie & Growth d'une agence IA d'élite.
Ton rôle: analyser la viabilité marché, définir les KPIs, positionner le produit.
Réponds en Markdown structuré. Sois concis, précis et orienté résultats business.
Inclus toujours: Analyse marché, KPIs proposés, Positionnement différenciateur.""",

    "ux": """Tu es le Département Conception & UX d'une agence IA d'élite.
Ton rôle: modéliser le parcours utilisateur, identifier la friction, définir l'ergonomie.
Réponds en Markdown structuré. Pense toujours à l'utilisateur final.
Inclus toujours: Parcours utilisateur, Points de friction, Recommandations UX, User Stories clés.""",

    "engineering": """Tu es le Département Ingénierie & Architecture d'une agence IA d'élite.
Ton rôle: définir la stack technique, créer le MCD, garantir la modularité et scalabilité.
Réponds en Markdown structuré avec du code ou des schémas si pertinent.
Inclus toujours: MCD (entités et relations), Stack recommandée, Modules MVP, Risques techniques.""",

    "devops": """Tu es le Département DevOps & Sécurité d'une agence IA d'élite.
Ton rôle: configurer l'infrastructure, sécuriser les flux, planifier la maintenance.
Réponds en Markdown structuré.
Inclus toujours: Infrastructure recommandée, Checklist sécurité, Pipeline CI/CD, Plan de monitoring.""",

    "orchestrator": """Tu es l'Orchestrateur d'une agence IA d'élite.
Tu reçois les analyses de 4 départements spécialisés et leurs critiques mutuelles.
Ton rôle: synthétiser tout cela en livrables cohérents, résoudre les contradictions, produire le livrable final.
Produis un JSON structuré avec les clés: cdc, mcd, architecture, roadmap, notes_synthese.""",
}


# ──────────────────────────────────────────────
# Agent node functions
# ──────────────────────────────────────────────

def make_r1_prompt(input_text: str, agent: str) -> str:
    return f"""Voici la description du projet à analyser:

---
{input_text}
---

Produis ton analyse complète en tant que Département {agent.upper()}. 
Sois exhaustif, structuré et actionnable."""


def make_critique_prompt(input_text: str, my_analysis: str, other_analyses: dict, agent: str) -> str:
    others_text = "\n\n".join([
        f"### Département {k.upper()}\n{v}"
        for k, v in other_analyses.items()
    ])
    return f"""Projet analysé:
{input_text}

Ton analyse initiale (Département {agent.upper()}):
{my_analysis}

Analyses des autres départements:
{others_text}

Ta mission: 
1. Valide ce qui est cohérent avec ta vision.
2. Identifie les contradictions ou risques que les autres n'ont pas vus.
3. Propose des ajustements si nécessaire.
Sois direct et constructif."""


def make_synthesis_prompt(input_text: str, r1: dict, critiques: dict) -> str:
    r1_text = "\n\n".join([f"### {k.upper()}\n{v}" for k, v in r1.items()])
    critiques_text = "\n\n".join([f"### Critique {k.upper()}\n{v}" for k, v in critiques.items()])

    return f"""Tu dois synthétiser les travaux de 4 départements IA sur ce projet:

PROJET:
{input_text}

ANALYSES INITIALES (Round 1):
{r1_text}

CRITIQUES CROISÉES (Round 2):
{critiques_text}

Produis maintenant un JSON valide (sans markdown, juste le JSON brut) avec cette structure exacte:
{{
  "cdc": "Cahier des charges complet en Markdown",
  "mcd": "Description du MCD en Markdown avec les entités et relations",
  "architecture": "Architecture technique en Markdown",
  "roadmap": "Roadmap détaillée en Markdown",
  "notes_synthese": "Notes de synthèse et points d'attention"
}}"""


# ──────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────

def build_graph(llm_router: LLMRouter, event_queue: asyncio.Queue):
    """Build and return a compiled LangGraph AIA workflow."""

    async def emit(event_type: str, **kwargs):
        await event_queue.put({"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **kwargs})

    async def round1_node(state: AiaState) -> dict:
        await emit("round_start", round=1, message="Lancement des analyses initiales...")

        async def run_agent(agent_key: str) -> str:
            await emit("agent_start", agent=agent_key, round=1)
            try:
                result = await llm_router.generate(
                    make_r1_prompt(state["input_text"], agent_key),
                    agent_key,
                    SYSTEM_PROMPTS[agent_key],
                )
                await emit("agent_complete", agent=agent_key, round=1, preview=result[:200])
                return result
            except Exception as e:
                await emit("agent_error", agent=agent_key, error=str(e))
                return f"Erreur agent {agent_key}: {e}"

        results = await asyncio.gather(
            run_agent("strategy"),
            run_agent("ux"),
            run_agent("engineering"),
            run_agent("devops"),
        )

        await emit("round_complete", round=1)
        return {
            "strategy_r1": results[0],
            "ux_r1": results[1],
            "engineering_r1": results[2],
            "devops_r1": results[3],
        }

    async def round2_node(state: AiaState) -> dict:
        await emit("round_start", round=2, message="Critiques croisées entre départements...")

        r1_outputs = {
            "strategy": state["strategy_r1"],
            "ux": state["ux_r1"],
            "engineering": state["engineering_r1"],
            "devops": state["devops_r1"],
        }

        async def run_critique(agent_key: str) -> str:
            await emit("agent_start", agent=agent_key, round=2)
            others = {k: v for k, v in r1_outputs.items() if k != agent_key}
            try:
                result = await llm_router.generate(
                    make_critique_prompt(state["input_text"], r1_outputs[agent_key], others, agent_key),
                    agent_key,
                    SYSTEM_PROMPTS[agent_key],
                )
                await emit("agent_complete", agent=agent_key, round=2, preview=result[:150])
                return result
            except Exception as e:
                await emit("agent_error", agent=agent_key, error=str(e))
                return f"[Critique non disponible: {e}]"

        results = await asyncio.gather(
            run_critique("strategy"),
            run_critique("ux"),
            run_critique("engineering"),
            run_critique("devops"),
        )

        critiques = {
            "strategy": results[0],
            "ux": results[1],
            "engineering": results[2],
            "devops": results[3],
        }

        await emit("round_complete", round=2)
        return {
            "strategy_critique": critiques["strategy"],
            "ux_critique": critiques["ux"],
            "engineering_critique": critiques["engineering"],
            "devops_critique": critiques["devops"],
            "critiques": critiques,
        }

    async def round3_node(state: AiaState) -> dict:
        await emit("round_start", round=3, message="Synthèse finale en cours...")

        r1 = {
            "strategy": state["strategy_r1"],
            "ux": state["ux_r1"],
            "engineering": state["engineering_r1"],
            "devops": state["devops_r1"],
        }
        critiques = {
            "strategy": state["strategy_critique"],
            "ux": state["ux_critique"],
            "engineering": state["engineering_critique"],
            "devops": state["devops_critique"],
        }

        try:
            raw = await llm_router.generate(
                make_synthesis_prompt(state["input_text"], r1, critiques),
                "orchestrator",
                SYSTEM_PROMPTS["orchestrator"],
            )

            # Try to parse JSON from the response
            try:
                # Handle cases where LLM wraps JSON in markdown
                clean = raw.strip()
                if clean.startswith("```"):
                    clean = "\n".join(clean.split("\n")[1:])
                    if clean.endswith("```"):
                        clean = clean[:-3]
                deliverables = json.loads(clean.strip())
            except json.JSONDecodeError:
                # Fallback: treat as plain text
                deliverables = {
                    "cdc": raw,
                    "mcd": "Voir l'analyse du département Ingénierie.",
                    "architecture": r1.get("engineering", ""),
                    "roadmap": "À définir selon les priorités validées.",
                    "notes_synthese": "Synthèse générée en mode dégradé.",
                }

            await emit("round_complete", round=3)
            await emit("workflow_complete", deliverables=deliverables)
            return {"final_deliverables": deliverables}

        except Exception as e:
            await emit("workflow_error", error=str(e))
            return {"error": str(e), "final_deliverables": {}}

    # Build the graph
    graph = StateGraph(AiaState)
    graph.add_node("round1", round1_node)
    graph.add_node("round2", round2_node)
    graph.add_node("round3", round3_node)

    graph.add_edge(START, "round1")
    graph.add_edge("round1", "round2")
    graph.add_edge("round2", "round3")
    graph.add_edge("round3", END)

    return graph.compile()


# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────

async def run_project_workflow(
    project_id: str,
    input_text: str,
    db: AsyncSession,
    event_queue: asyncio.Queue,
) -> dict:
    """
    Run the full 3-round AIA workflow for a project.
    Streams events via event_queue.
    Returns final deliverables.
    """
    from app.models.project import Project
    from sqlalchemy import select

    llm_router = LLMRouter(db)
    graph = build_graph(llm_router, event_queue)

    initial_state: AiaState = {
        "project_id": project_id,
        "input_text": input_text,
        "strategy_r1": "",
        "ux_r1": "",
        "engineering_r1": "",
        "devops_r1": "",
        "strategy_critique": "",
        "ux_critique": "",
        "engineering_critique": "",
        "devops_critique": "",
        "final_deliverables": {},
        "error": None,
    }

    try:
        final_state = await graph.ainvoke(initial_state)

        # Persist results to DB
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.strategy_r1 = final_state.get("strategy_r1", "")
            project.ux_r1 = final_state.get("ux_r1", "")
            project.engineering_r1 = final_state.get("engineering_r1", "")
            project.devops_r1 = final_state.get("devops_r1", "")
            project.critiques = {
                "strategy": final_state.get("strategy_critique", ""),
                "ux": final_state.get("ux_critique", ""),
                "engineering": final_state.get("engineering_critique", ""),
                "devops": final_state.get("devops_critique", ""),
            }
            project.final_deliverables = final_state.get("final_deliverables", {})
            project.status = "completed"
            project.completed_at = datetime.now(timezone.utc)
            await db.commit()

        return final_state.get("final_deliverables", {})

    except Exception as e:
        # Update project as failed
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "failed"
            await db.commit()
        raise
