"""
LangGraph Orchestrator — checkpointed multi-agent workflow.

Round 1: departments produce initial analysis.
Round 2..N: departments run configurable cross-critiques/debate rounds.
Final round: orchestrator synthesizes into final deliverables.

Events are streamed via asyncio.Queue for WebSocket delivery.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import TypedDict, Optional, Any

REQUIRED_DELIVERABLE_KEYS = {"cdc", "mcd", "architecture", "roadmap", "notes_synthese"}

from langgraph.graph import StateGraph, START, END
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agency import get_employee_profiles
from app.core.llm_router import LLMRouter
from app.models.workflow_event import WorkflowEvent


class WorkflowPaused(Exception):
    """Raised when a user pauses a running workflow."""


class ValidationQuestionsRequired(WorkflowPaused):
    """Raised when the orchestrator needs user validation before continuing."""

    def __init__(self, questions: list[dict[str, Any]]):
        super().__init__("Questions de validation en attente.")
        self.questions = questions



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
    validation_questions: list[dict]
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

    "orchestrator_validation": """Tu es l'Orchestrateur d'une agence IA d'élite.
Tu ne produis pas de livrables finaux ici.
Ton rôle est de formuler des questions de validation réellement utiles au client à partir du brief et des analyses déjà produites.
Réponds uniquement en JSON valide, sans markdown ni texte supplémentaire.""",
}



EMPLOYEES = {
    "strategy": {
        "lead": {"name": "Aminata", "role": "Lead Growth", "avatar": "AG"},
        "reviewer": {"name": "Noam", "role": "Analyste marché", "avatar": "NM"},
        "label": "Stratégie",
    },
    "ux": {
        "lead": {"name": "Maya", "role": "UX Researcher", "avatar": "UX"},
        "reviewer": {"name": "Lina", "role": "Product Designer", "avatar": "PD"},
        "label": "UX",
    },
    "engineering": {
        "lead": {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR"},
        "reviewer": {"name": "Sara", "role": "Data modeler", "avatar": "DB"},
        "label": "Ingénierie",
    },
    "devops": {
        "lead": {"name": "Karim", "role": "DevSecOps", "avatar": "DS"},
        "reviewer": {"name": "Inès", "role": "Cloud engineer", "avatar": "CE"},
        "label": "DevOps",
    },
    "orchestrator": {
        "lead": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
        "reviewer": {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO"},
        "label": "Orchestrateur",
    },
}


def excerpt(text: str, limit: int = 260) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit].rstrip()}..."


def clamp_text(text: str, limit: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit].rstrip()}\n\n[Contenu tronqué automatiquement pour maîtriser les tokens et éviter les erreurs API.]"

def extract_mermaid_block(text: str) -> str:
    match = re.search(r"```mermaid\s*([\s\S]*?)```", text or "", re.IGNORECASE)
    return match.group(1).strip() if match else ""


def count_mermaid_entities(text: str) -> int:
    mermaid = extract_mermaid_block(text)
    if not mermaid:
        return 0
    return len(re.findall(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*\{", mermaid, re.MULTILINE))


def inject_mermaid_block(text: str, mermaid: str) -> str:
    fenced = f"```mermaid\n{mermaid.strip()}\n```"
    if re.search(r"```mermaid\s*[\s\S]*?```", text or "", re.IGNORECASE):
        return re.sub(r"```mermaid\s*[\s\S]*?```", fenced, text, count=1, flags=re.IGNORECASE)
    base = (text or "").strip()
    return f"{base}\n\n{fenced}".strip()


def _strip_code_fences(text: str) -> str:
    clean = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", clean, re.IGNORECASE)
    return fenced.group(1).strip() if fenced else clean


def _extract_balanced_json(text: str) -> str:
    source = text or ""
    start = source.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return ""


def _parse_deliverables_json(raw: str) -> dict:
    candidates: list[str] = []
    clean = _strip_code_fences(raw)
    if clean:
        candidates.append(clean)
    json_block = re.search(r"```json\s*([\s\S]*?)```", raw or "", re.IGNORECASE)
    if json_block:
        candidates.append(json_block.group(1).strip())
    balanced = _extract_balanced_json(clean or raw or "")
    if balanced:
        candidates.append(balanced.strip())
    if raw and raw.strip():
        candidates.append(raw.strip())

    decoder = json.JSONDecoder()
    incomplete_error: RuntimeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed, _ = decoder.raw_decode(candidate[candidate.find('{'):] if '{' in candidate else candidate)
            except Exception:
                continue
        if not isinstance(parsed, dict):
            continue
        missing = [key for key in REQUIRED_DELIVERABLE_KEYS if not str(parsed.get(key) or "").strip()]
        if missing:
            incomplete_error = RuntimeError(
                "L'orchestrateur IA a renvoyé un JSON incomplet pour les livrables. "
                f"Champs manquants: {', '.join(missing)}"
            )
            continue
        return {key: str(parsed.get(key) or "").strip() for key in REQUIRED_DELIVERABLE_KEYS}
    if incomplete_error:
        raise incomplete_error
    raise RuntimeError("L'orchestrateur IA n'a pas retourné un JSON valide pour les livrables.")


def preserve_deliverable_depth(deliverables: dict, r1: dict) -> dict:
    enriched = dict(deliverables or {})

    source_mcd = r1.get("engineering") or ""
    final_mcd = enriched.get("mcd") or ""
    source_entities = count_mermaid_entities(source_mcd)
    final_entities = count_mermaid_entities(final_mcd)

    if source_entities >= 5 and final_entities and final_entities < source_entities:
        source_mermaid = extract_mermaid_block(source_mcd)
        if source_mermaid:
            enriched["mcd"] = inject_mermaid_block(
                final_mcd,
                source_mermaid,
            ) + "\n\n> Le graphe MCD détaillé du round d'ingénierie a été conservé car il était plus complet que la première synthèse finale."
    elif source_entities >= 5 and not final_entities:
        source_mermaid = extract_mermaid_block(source_mcd)
        if source_mermaid:
            enriched["mcd"] = inject_mermaid_block(final_mcd or "## MCD\n", source_mermaid)

    return enriched


def has_complete_final_deliverables(deliverables: dict | None) -> bool:
    if not isinstance(deliverables, dict):
        return False
    if deliverables.get("error"):
        return False
    return all(str(deliverables.get(key) or "").strip() for key in REQUIRED_DELIVERABLE_KEYS)

# ──────────────────────────────────────────────
# Agent node functions
# ──────────────────────────────────────────────

def make_r1_prompt(input_text: str, agent: str) -> str:
    return f"""Voici la description du projet à analyser:

---
{clamp_text(input_text, 5000)}
---

Produis ton analyse complète en tant que Département {agent.upper()}.
Limite ta réponse à 900 mots maximum. Sois structuré et actionnable, sans répétition."""


def make_critique_prompt(input_text: str, my_analysis: str, other_analyses: dict, agent: str) -> str:
    others_text = "\n\n".join([
        f"### Département {k.upper()}\n{clamp_text(v, 1400)}"
        for k, v in other_analyses.items()
    ])
    return f"""Projet analysé:
{clamp_text(input_text, 3500)}

Ton analyse initiale (Département {agent.upper()}):
{clamp_text(my_analysis, 1600)}

Analyses synthétisées des autres départements:
{others_text}

Ta mission:
1. Valide ce qui est cohérent avec ta vision.
2. Identifie les contradictions ou risques majeurs.
3. Propose des ajustements.
Limite ta critique à 500 mots maximum. Sois direct et constructif."""


def make_synthesis_prompt(input_text: str, r1: dict, critiques: dict) -> str:
    r1_text = "\n\n".join([f"### {k.upper()}\n{clamp_text(v, 1800)}" for k, v in r1.items()])
    critiques_text = "\n\n".join([f"### Critique {k.upper()}\n{clamp_text(v, 1200)}" for k, v in critiques.items()])

    return f"""Tu dois synthétiser les travaux de 4 départements IA sur ce projet:

PROJET:
{clamp_text(input_text, 3500)}

ANALYSES INITIALES SYNTHÉTISÉES (Round 1):
{r1_text}

CRITIQUES CROISÉES SYNTHÉTISÉES (Round 2):
{critiques_text}

RÈGLE ABSOLUE DE CONSOLIDATION :
- La synthèse finale ne doit jamais être plus pauvre que les analyses déjà validées.
- Tu dois conserver toutes les entités, relations, modules, contraintes, décisions et points structurants confirmés par les rounds précédents.
- Si un élément du Round 1 reste valable et n'est pas invalidé par une critique, il doit rester visible dans le livrable final.
- Le MCD final doit être au moins aussi riche que le MCD d'ingénierie validé auparavant.
- N'abrège pas à l'excès : préfère une synthèse consolidée et complète à une version trop courte.

Produis maintenant un JSON valide (sans markdown, juste le JSON brut) avec cette structure exacte:
{{
  "cdc": "Cahier des charges complet en Markdown, avec objectifs, périmètre, utilisateurs, fonctionnalités, contraintes, flux clés et critères d'acceptation.",
  "mcd": "Description du MCD en Markdown. Inclus obligatoirement un bloc fenced Mermaid commençant par ```mermaid puis erDiagram, avec les entités, attributs et relations principales. Ne supprime aucune entité importante déjà identifiée si elle reste pertinente.",
  "architecture": "Architecture technique en Markdown, avec composants backend/frontend, données, sécurité, intégrations et décisions techniques.",
  "roadmap": "Roadmap détaillée en Markdown, avec phases, priorités, MVP, dépendances et jalons.",
  "notes_synthese": "Notes de synthèse, arbitrages, risques, points ouverts et recommandations de suite."
}}"""


def make_validation_questions_prompt(input_text: str, r1: dict, critiques: dict) -> str:
    r1_text = "\n\n".join([f"### {k.upper()}\n{clamp_text(v, 1600)}" for k, v in r1.items()])
    critiques_text = "\n\n".join([f"### Critique {k.upper()}\n{clamp_text(v, 1200)}" for k, v in critiques.items() if str(v or "").strip()])
    return f"""Tu es l'Orchestrateur d'une agence IA.
À partir du brief, des analyses Round 1 et des critiques Round 2, tu dois formuler des questions de validation réellement utiles au client.

PROJET:
{clamp_text(input_text, 3000)}

ANALYSES ROUND 1:
{r1_text}

CRITIQUES ROUND 2:
{critiques_text or "(aucune critique disponible)"}

RÈGLES:
- Les questions doivent venir du besoin réel, pas d'une liste générique.
- Chaque question doit débloquer une décision, une validation ou une précision.
- Évite les questions trop larges ou redondantes.
- Si une décision importante est déjà claire, ne la répète pas.
- Produis entre 2 et 5 questions maximum.
- Chaque question doit être concrète, courte et actionnable.

Retourne uniquement un JSON valide avec la structure exacte:
{{
  "questions": [
    {{
      "id": "strategie-01",
      "department": "strategy",
      "question": "Question concise à poser au client",
      "why_it_matters": "Pourquoi cette validation est importante",
      "answer_type": "yes_no"
    }}
  ]
}}

Valeurs autorisées pour department: strategy, ux, engineering, devops, orchestrator.
Valeurs autorisées pour answer_type: yes_no, choice, free_text.
"""


def _parse_validation_questions_json(raw: str) -> list[dict[str, Any]]:
    candidates: list[str] = []
    clean = _strip_code_fences(raw)
    if clean:
        candidates.append(clean)
    json_block = re.search(r"```json\s*([\s\S]*?)```", raw or "", re.IGNORECASE)
    if json_block:
        candidates.append(json_block.group(1).strip())
    balanced = _extract_balanced_json(clean or raw or "")
    if balanced:
        candidates.append(balanced.strip())
    if raw and raw.strip():
        candidates.append(raw.strip())

    parsed: dict[str, Any] | None = None
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                loaded, _ = decoder.raw_decode(candidate[candidate.find('{'):] if '{' in candidate else candidate)
            except Exception:
                continue
        if isinstance(loaded, dict):
            parsed = loaded
            break

    if not parsed:
        return []

    questions = parsed.get("questions")
    if not isinstance(questions, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        department = str(item.get("department") or "orchestrator").strip().lower()
        normalized.append({
            "id": str(item.get("id") or f"validation-{index}").strip(),
            "department": department if department in {"strategy", "ux", "engineering", "devops", "orchestrator"} else "orchestrator",
            "question": question,
            "why_it_matters": str(item.get("why_it_matters") or "").strip(),
            "answer_type": str(item.get("answer_type") or "free_text").strip().lower(),
        })
    return normalized


# ──────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────

def build_graph(llm_router: LLMRouter, event_queue: asyncio.Queue, cancel_event: asyncio.Event | None = None):
    """Build and return a compiled LangGraph AIA workflow."""

    employee_profiles: dict[str, dict] | None = None
    workflow_settings_cache: dict[str, int] | None = None

    async def emit(event_type: str, **kwargs):
        await event_queue.put({"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **kwargs})

    async def get_profiles() -> dict[str, dict]:
        nonlocal employee_profiles
        if employee_profiles is None:
            db_profiles = await get_employee_profiles(llm_router.db)
            employee_profiles = {**EMPLOYEES, **db_profiles}
        return employee_profiles

    async def speak(agent_key: str, employee_key: str, message: str, round: int, phase: str, target: str | None = None):
        profiles = await get_profiles()
        profile_group = profiles.get(agent_key, EMPLOYEES[agent_key])
        profile = profile_group.get(employee_key) or profile_group.get("lead") or EMPLOYEES[agent_key]["lead"]
        await emit(
            "employee_message",
            agent=agent_key,
            department=profile_group.get("label", EMPLOYEES[agent_key]["label"]),
            employee=profile,
            message=message,
            round=round,
            phase=phase,
            target=target,
        )

    def ensure_not_paused():
        if cancel_event and cancel_event.is_set():
            raise WorkflowPaused("Analyse mise en pause par l'utilisateur.")

    async def get_debate_rounds() -> int:
        nonlocal workflow_settings_cache
        if workflow_settings_cache is not None:
            return workflow_settings_cache["debate_rounds"]

        from app.models.llm_config import LLMConfig

        result = await llm_router.db.execute(
            select(LLMConfig).where(
                LLMConfig.provider.in_(["workflow_debate_rounds", "workflow_final_json_retry_count"])
            )
        )
        configs = {cfg.provider: cfg for cfg in result.scalars().all()}
        try:
            configured_raw = configs.get("workflow_debate_rounds").value if configs.get("workflow_debate_rounds") else None
            configured = int(1 if configured_raw is None else configured_raw)
        except (TypeError, ValueError):
            configured = 1
        try:
            retries_raw = configs.get("workflow_final_json_retry_count").value if configs.get("workflow_final_json_retry_count") else None
            json_retries = int(2 if retries_raw is None else retries_raw)
        except (TypeError, ValueError):
            json_retries = 2
        workflow_settings_cache = {
            "debate_rounds": max(0, min(configured, 3)),
            "final_json_retry_count": max(0, min(json_retries, 5)),
        }
        return workflow_settings_cache["debate_rounds"]

    async def get_final_json_retry_count() -> int:
        nonlocal workflow_settings_cache
        if workflow_settings_cache is None:
            await get_debate_rounds()
        return workflow_settings_cache["final_json_retry_count"]

    async def persist_project_field(project_id: str, field: str, value: Any) -> None:
        from app.models.project import Project

        result = await llm_router.db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return
        setattr(project, field, value)
        project.completed_at = None
        await llm_router.db.commit()

    async def persist_project_critique(project_id: str, agent_key: str, value: str) -> None:
        from app.models.project import Project

        result = await llm_router.db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return
        critiques = dict(project.critiques or {})
        critiques[agent_key] = value
        project.critiques = critiques
        project.completed_at = None
        await llm_router.db.commit()

    async def enriched_input(state: AiaState) -> str:
        result = await llm_router.db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.project_id == state["project_id"], WorkflowEvent.event_type == "user_message")
            .order_by(WorkflowEvent.sequence)
        )
        messages = result.scalars().all()
        additions = []
        for event in messages:
            payload = event.payload or {}
            content = (payload.get("content") or payload.get("message") or "").strip()
            if content:
                author = payload.get("author") or "Utilisateur"
                additions.append(f"- {author}: {content}")

        memory_items = [
            ("Analyse Stratégie déjà produite", state.get("strategy_r1")),
            ("Analyse UX déjà produite", state.get("ux_r1")),
            ("Analyse Ingénierie déjà produite", state.get("engineering_r1")),
            ("Analyse DevOps déjà produite", state.get("devops_r1")),
            ("Critique Stratégie déjà produite", state.get("strategy_critique")),
            ("Critique UX déjà produite", state.get("ux_critique")),
            ("Critique Ingénierie déjà produite", state.get("engineering_critique")),
            ("Critique DevOps déjà produite", state.get("devops_critique")),
        ]
        validation_context = state.get("final_deliverables") or {}
        validation_questions = validation_context.get("validation_questions") if isinstance(validation_context, dict) else []
        validation_answers = validation_context.get("validation_answers") if isinstance(validation_context, dict) else []
        if isinstance(validation_questions, list) and validation_questions:
            memory_items.append(("Questions de validation générées", "\n".join(
                f"- {str(item.get('question') or '').strip()}".strip()
                for item in validation_questions
                if isinstance(item, dict) and str(item.get("question") or "").strip()
            )))
        if isinstance(validation_answers, list) and validation_answers:
            memory_items.append(("Réponses utilisateur aux questions de validation", "\n".join(
                f"- {str(item.get('question') or item.get('id') or 'Question')}: {str(item.get('answer') or '').strip()}"
                for item in validation_answers
                if isinstance(item, dict) and str(item.get("answer") or "").strip()
            )))
        memory = [
            f"### {title}\\n{clamp_text(value, 900)}"
            for title, value in memory_items
            if isinstance(value, str) and value.strip()
        ]

        sections = []
        if additions:
            sections.append("INFORMATIONS COMPLEMENTAIRES FOURNIES PAR L'UTILISATEUR PENDANT L'ANALYSE:\\n" + chr(10).join(additions))
        if memory:
            sections.append("MEMOIRE DE REPRISE / CHECKPOINTS DEJA PRODUITS:\\n" + "\\n\\n".join(memory))

        if not sections:
            return state["input_text"]
        return f"""{state["input_text"]}

---
{chr(10).join(sections)}
---
Tu dois tenir compte de cette mémoire et continuer le travail sans répéter inutilement ce qui est déjà acquis."""

    async def round1_node(state: AiaState) -> dict:
        ensure_not_paused()
        profiles = await get_profiles()
        await emit("round_start", round=1, message="Lancement ou reprise des analyses initiales...")
        await speak("orchestrator", "lead", "J'affecte le projet aux départements. Les analyses déjà produites sont reprises comme checkpoints, puis les équipes restantes complètent le travail.", 1, "system_step")

        fields = {
            "strategy": "strategy_r1",
            "ux": "ux_r1",
            "engineering": "engineering_r1",
            "devops": "devops_r1",
        }
        results_by_agent = {agent: (state.get(field) or "") for agent, field in fields.items()}

        async def run_agent(agent_key: str) -> str:
            ensure_not_paused()
            existing = (results_by_agent.get(agent_key) or "").strip()
            if existing:
                await emit("agent_complete", agent=agent_key, round=1, preview=existing[:200], content=existing, resumed=True)
                await speak(
                    agent_key,
                    "lead",
                    "Checkpoint retrouvé : je conserve l'analyse déjà produite.\n\n" + existing,
                    1,
                    "checkpoint",
                )
                return existing

            await emit("agent_start", agent=agent_key, round=1)
            await speak(agent_key, "lead", f"Mission reçue. L'équipe {profiles[agent_key]['label']} démarre l'analyse du besoin et prépare ses hypothèses.", 1, "system_step")
            await speak(agent_key, "reviewer", "Je surveille les angles morts et je prépare les points à challenger au round suivant.", 1, "system_step")
            try:
                result = await llm_router.generate(
                    make_r1_prompt(await enriched_input(state), agent_key),
                    agent_key,
                    SYSTEM_PROMPTS[agent_key],
                )
                await persist_project_field(state["project_id"], fields[agent_key], result)
                await emit("agent_complete", agent=agent_key, round=1, preview=result[:200], content=result)
                await speak(agent_key, "lead", f"Analyse initiale prête :\n\n{result}", 1, "result")
                await speak(agent_key, "reviewer", "Je transmets cette proposition aux autres départements pour critique contradictoire.", 1, "system_step")
                return result
            except Exception as e:
                await emit("agent_error", agent=agent_key, round=1, error=str(e))
                raise

        ordered_agents = ["strategy", "ux", "engineering", "devops"]
        results = []
        for agent_key in ordered_agents:
            results.append(await run_agent(agent_key))

        ensure_not_paused()
        await emit("round_complete", round=1)
        return {
            "strategy_r1": results[0],
            "ux_r1": results[1],
            "engineering_r1": results[2],
            "devops_r1": results[3],
        }

    async def round2_node(state: AiaState) -> dict:
        ensure_not_paused()
        profiles = await get_profiles()
        debate_rounds = await get_debate_rounds()

        r1_outputs = {
            "strategy": state["strategy_r1"],
            "ux": state["ux_r1"],
            "engineering": state["engineering_r1"],
            "devops": state["devops_r1"],
        }
        existing_critiques = {
            "strategy": state.get("strategy_critique", "") or "",
            "ux": state.get("ux_critique", "") or "",
            "engineering": state.get("engineering_critique", "") or "",
            "devops": state.get("devops_critique", "") or "",
        }

        if all(value.strip() for value in existing_critiques.values()):
            await emit("round_start", round=2, message="Critiques déjà disponibles, reprise depuis checkpoint...")
            await speak("orchestrator", "lead", "Les critiques croisées sont déjà sauvegardées. Je reprends directement à partir de cette mémoire de travail.", 2, "checkpoint")
            await emit("round_complete", round=2, resumed=True)
            return {
                "strategy_critique": existing_critiques["strategy"],
                "ux_critique": existing_critiques["ux"],
                "engineering_critique": existing_critiques["engineering"],
                "devops_critique": existing_critiques["devops"],
                "critiques": existing_critiques,
            }

        current_outputs = r1_outputs
        final_critiques = dict(existing_critiques)

        for debate_index in range(debate_rounds):
            round_number = 2 + debate_index
            await emit("round_start", round=round_number, message=f"Débat critique {debate_index + 1}/{debate_rounds} entre départements...")
            await speak("orchestrator", "lead", f"Round de débat {debate_index + 1}/{debate_rounds}. Chaque équipe doit lire les propositions des autres, formuler ses objections et défendre ses arbitrages.", round_number, "system_step")

            async def run_critique(agent_key: str) -> str:
                ensure_not_paused()
                if debate_rounds == 1 and final_critiques.get(agent_key, "").strip():
                    existing = final_critiques[agent_key]
                    await emit("agent_complete", agent=agent_key, round=round_number, preview=existing[:150], content=existing, resumed=True)
                    await speak(
                        agent_key,
                        "lead",
                        "Critique déjà sauvegardée, je la conserve.\n\n" + existing,
                        round_number,
                        "checkpoint",
                        target="orchestrateur",
                    )
                    return existing

                await emit("agent_start", agent=agent_key, round=round_number)
                others = {k: v for k, v in current_outputs.items() if k != agent_key}
                base = current_outputs.get(agent_key) or r1_outputs[agent_key]
                await speak(agent_key, "lead", "Je relis les positions des autres départements et je cherche les contradictions concrètes.", round_number, "system_step")
                await speak(agent_key, "reviewer", f"Je challenge surtout {', '.join(profiles[key]['label'] for key in others.keys())} pour sécuriser notre consensus.", round_number, "system_step", target="autres départements")
                try:
                    result = await llm_router.generate(
                        make_critique_prompt(await enriched_input(state), base, others, agent_key),
                        agent_key,
                        SYSTEM_PROMPTS[agent_key],
                    )
                    await persist_project_critique(state["project_id"], agent_key, result)
                    await emit("agent_complete", agent=agent_key, round=round_number, preview=result[:150], content=result)
                    await speak(agent_key, "lead", f"Critique formulée :\n\n{result}", round_number, "critique_result", target="orchestrateur")
                    return result
                except Exception as e:
                    await emit("agent_error", agent=agent_key, round=round_number, error=str(e))
                    raise

            round_results = {}
            for agent_key in ["strategy", "ux", "engineering", "devops"]:
                round_results[agent_key] = await run_critique(agent_key)

            final_critiques = round_results
            current_outputs = round_results
            ensure_not_paused()
            await emit("round_complete", round=round_number)

        return {
            "strategy_critique": final_critiques["strategy"],
            "ux_critique": final_critiques["ux"],
            "engineering_critique": final_critiques["engineering"],
            "devops_critique": final_critiques["devops"],
            "critiques": final_critiques,
        }

    async def round3_node(state: AiaState) -> dict:
        ensure_not_paused()
        final_round = 2 + await get_debate_rounds()
        existing_deliverables = dict(state.get("final_deliverables") or {})
        if has_complete_final_deliverables(existing_deliverables):
            await emit("round_start", round=final_round, message="Livrables déjà disponibles, reprise depuis checkpoint...")
            await speak("orchestrator", "lead", "Les livrables consolidés existent déjà. Je les conserve au lieu de régénérer inutilement.", final_round, "checkpoint")
            await emit("workflow_complete", deliverables=existing_deliverables, resumed=True)
            return {
                "final_deliverables": existing_deliverables,
                "validation_questions": existing_deliverables.get("validation_questions", []) if isinstance(existing_deliverables, dict) else [],
            }

        await emit("round_start", round=final_round, message="Synthèse finale en cours...")
        await speak("orchestrator", "lead", "Je récupère les analyses et les objections. Je vais arbitrer les contradictions et produire les livrables finaux.", final_round, "system_step")

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
        validation_questions: list[dict[str, Any]] = []

        try:
            if isinstance(existing_deliverables.get("validation_questions"), list):
                validation_questions = [
                    item for item in existing_deliverables.get("validation_questions", [])
                    if isinstance(item, dict) and str(item.get("question") or "").strip()
                ]

            validation_answers = existing_deliverables.get("validation_answers") if isinstance(existing_deliverables, dict) else []
            has_pending_validation = bool(existing_deliverables.get("validation_questions")) and not (
                isinstance(validation_answers, list) and any(
                    isinstance(item, dict) and str(item.get("answer") or "").strip()
                    for item in validation_answers
                )
            )
            if has_pending_validation:
                await emit(
                    "implementation_status",
                    message="Attente des réponses de validation avant la synthèse finale.",
                )
                await speak(
                    "orchestrator",
                    "lead",
                    "Je conserve les questions de validation déjà générées. J'attends les réponses du client avant de lancer la synthèse finale.",
                    final_round,
                    "validation_wait",
                )
                raise ValidationQuestionsRequired(existing_deliverables.get("validation_questions", []))

            try:
                if not validation_questions and not has_pending_validation:
                    questions_raw = await llm_router.generate(
                        make_validation_questions_prompt(await enriched_input(state), r1, critiques),
                        "orchestrator",
                        SYSTEM_PROMPTS["orchestrator_validation"],
                    )
                    validation_questions = _parse_validation_questions_json(questions_raw)
                    if validation_questions:
                        deliverables_with_questions = dict(existing_deliverables or {})
                        deliverables_with_questions["validation_questions"] = validation_questions
                        deliverables_with_questions["validation_status"] = "awaiting_user"
                        await persist_project_field(state["project_id"], "final_deliverables", deliverables_with_questions)
                        await emit(
                            "implementation_status",
                            message=f"{len(validation_questions)} question(s) de validation générées par l'orchestrateur IA.",
                        )
                        await speak(
                            "orchestrator",
                            "lead",
                            "J'ai identifié les points qui méritent validation humaine avant de figer les livrables. Voici les questions prioritaires :\n\n"
                            + "\n".join([f"{index}. {item['question']}" for index, item in enumerate(validation_questions, start=1)]),
                            final_round,
                            "validation_questions",
                        )
                        raise ValidationQuestionsRequired(validation_questions)
            except Exception as questions_error:
                if isinstance(questions_error, ValidationQuestionsRequired):
                    raise
                await emit("implementation_status", message=f"Impossible de générer les questions de validation: {questions_error}")

            retry_count = await get_final_json_retry_count()
            last_error: Exception | None = None
            raw = ""
            for attempt in range(retry_count + 1):
                retry_notice = ""
                if attempt > 0:
                    retry_notice = (
                        "\n\nIMPORTANT: ta tentative précédente n'était pas exploitable. "
                        "Réponds uniquement avec un objet JSON brut strict, sans texte avant ni après, sans markdown."
                    )
                    await emit(
                        "implementation_status",
                        message=f"JSON final invalide détecté. Relance automatique {attempt}/{retry_count} de la synthèse orchestrateur.",
                    )
                    await speak(
                        "orchestrator",
                        "lead",
                        f"La réponse finale précédente n'était pas exploitable en JSON. Je relance une synthèse propre, tentative {attempt}/{retry_count}.",
                        final_round,
                        "retry",
                    )

                raw = await llm_router.generate(
                    make_synthesis_prompt(await enriched_input(state), r1, critiques) + retry_notice,
                    "orchestrator",
                    SYSTEM_PROMPTS["orchestrator"],
                )
                try:
                    deliverables = _parse_deliverables_json(raw)
                    break
                except Exception as parse_error:
                    last_error = parse_error
                    if attempt >= retry_count:
                        raise
            else:
                raise last_error or RuntimeError("L'orchestrateur IA n'a pas retourné un JSON valide pour les livrables.")

            deliverables = preserve_deliverable_depth(deliverables, r1)
            if validation_questions:
                deliverables["validation_questions"] = validation_questions
            if isinstance(validation_answers, list) and validation_answers:
                deliverables["validation_answers"] = validation_answers
            deliverables["validation_status"] = "completed"
            ensure_not_paused()
            await persist_project_field(state["project_id"], "final_deliverables", deliverables)
            await emit("round_complete", round=final_round)
            await speak("orchestrator", "lead", "Consensus obtenu. Les livrables consolidés sont prêts pour validation humaine.", final_round, "complete")
            await emit("workflow_complete", deliverables=deliverables)
            return {"final_deliverables": deliverables, "validation_questions": validation_questions}

        except ValidationQuestionsRequired:
            raise
        except Exception as e:
            await emit("workflow_error", error=str(e))
            raise

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
    cancel_event: asyncio.Event | None = None,
) -> dict:
    """
    Run the full 3-round AIA workflow for a project.
    Streams events via event_queue.
    Returns final deliverables.
    """
    from app.models.project import Project
    llm_router = LLMRouter(db)
    graph = build_graph(llm_router, event_queue, cancel_event)

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    critiques = dict(project.critiques or {}) if project else {}

    initial_state: AiaState = {
        "project_id": project_id,
        "input_text": input_text,
        "strategy_r1": (project.strategy_r1 if project else None) or "",
        "ux_r1": (project.ux_r1 if project else None) or "",
        "engineering_r1": (project.engineering_r1 if project else None) or "",
        "devops_r1": (project.devops_r1 if project else None) or "",
        "strategy_critique": critiques.get("strategy", "") or "",
        "ux_critique": critiques.get("ux", "") or "",
        "engineering_critique": critiques.get("engineering", "") or "",
        "devops_critique": critiques.get("devops", "") or "",
        "validation_questions": [],
        "final_deliverables": (project.final_deliverables if project else None) or {},
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
            from app.core.project_workspace import IMPLEMENTATION_PIPELINE_KEY, ensure_pipeline_metadata, get_workspace_settings, refresh_project_workspace_documents

            deliverables = dict(final_state.get("final_deliverables", {}) or {})
            validation_questions = final_state.get("validation_questions") or deliverables.get("validation_questions") or []
            if validation_questions:
                deliverables["validation_questions"] = validation_questions
            settings = await get_workspace_settings(db)
            deliverables = ensure_pipeline_metadata(deliverables, settings)
            project.final_deliverables = deliverables
            project.status = "completed"
            project.completed_at = datetime.now(timezone.utc)
            await db.commit()
            workspace = deliverables.get("implementation_workspace")
            if isinstance(workspace, dict) and workspace.get("project_dir"):
                try:
                    await refresh_project_workspace_documents(
                        project_dir=str(workspace["project_dir"]),
                        project_id=project.id,
                        project_title=project.title,
                        input_text=project.input_text,
                        deliverables=deliverables,
                        db=db,
                    )
                except Exception:
                    pass
            await event_queue.put({
                "type": "implementation_status",
                "message": "Analyse terminée. Validation admin requise avant conception technique." if settings.require_technical_approval else "Analyse terminée. La conception technique peut démarrer.",
                "pipeline": deliverables.get(IMPLEMENTATION_PIPELINE_KEY),
            })

        return deliverables

    except ValidationQuestionsRequired as e:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "paused"
            deliverables = dict(project.final_deliverables or {})
            if e.questions:
                deliverables["validation_questions"] = e.questions
            deliverables["validation_status"] = "awaiting_user"
            project.final_deliverables = deliverables or None
            project.completed_at = None
            await db.commit()
            workspace = deliverables.get("implementation_workspace")
            if isinstance(workspace, dict) and workspace.get("project_dir"):
                try:
                    from app.core.project_workspace import refresh_project_workspace_documents

                    await refresh_project_workspace_documents(
                        project_dir=str(workspace["project_dir"]),
                        project_id=project.id,
                        project_title=project.title,
                        input_text=project.input_text,
                        deliverables=deliverables,
                        db=db,
                    )
                except Exception:
                    pass
        await event_queue.put({
            "type": "workflow_paused",
            "message": str(e),
            "reason": "validation_required",
            "validation_questions": e.questions,
        })
        return dict(project.final_deliverables or {})

    except WorkflowPaused as e:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "paused"
            project.final_deliverables = {"error": str(e)}
            project.completed_at = None
            await db.commit()
        await event_queue.put({"type": "workflow_paused", "message": str(e)})
        raise

    except Exception as e:
        # Update project as failed
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "failed"
            project.final_deliverables = {"error": str(e)}
            project.completed_at = None
            await db.commit()
        raise
