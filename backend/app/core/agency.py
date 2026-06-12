from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department, Employee


DEFAULT_AGENCY_DEPARTMENTS = [
    {
        "key": "strategy",
        "label": "Stratégie",
        "description": "Analyse marché, positionnement, KPIs et modèle économique.",
        "mission": "Analyser la viabilité business, prioriser les risques marché et produire une stratégie MVP claire.",
        "sort_order": 10,
        "employees": [
            {"name": "Aminata", "role": "Lead Growth", "avatar": "AG", "briefing": "Cadre la stratégie, les KPIs et la proposition de valeur.", "sort_order": 10},
            {"name": "Noam", "role": "Analyste marché", "avatar": "NM", "briefing": "Challenge les hypothèses marché, concurrence et pricing.", "sort_order": 20},
        ],
    },
    {
        "key": "ux",
        "label": "UX",
        "description": "Parcours utilisateur, friction, ergonomie et user stories.",
        "mission": "Transformer le besoin en expérience utilisable, fluide et compréhensible par les utilisateurs finaux.",
        "sort_order": 20,
        "employees": [
            {"name": "Maya", "role": "UX Researcher", "avatar": "UX", "briefing": "Analyse les parcours, attentes et points de friction.", "sort_order": 10},
            {"name": "Lina", "role": "Product Designer", "avatar": "PD", "briefing": "Conçoit les écrans clés, les user stories et les interactions.", "sort_order": 20},
        ],
    },
    {
        "key": "engineering",
        "label": "Ingénierie",
        "description": "Architecture logicielle, MCD, modules et risques techniques.",
        "mission": "Définir une architecture robuste, modulaire et réaliste pour construire le produit.",
        "sort_order": 30,
        "employees": [
            {"name": "Elias", "role": "Architecte logiciel", "avatar": "AR", "briefing": "Structure les modules, APIs, choix techniques et flux backend/frontend.", "sort_order": 10},
            {"name": "Sara", "role": "Data modeler", "avatar": "DB", "briefing": "Modélise les entités, relations, contraintes et données critiques.", "sort_order": 20},
        ],
    },
    {
        "key": "devops",
        "label": "DevOps",
        "description": "Déploiement, sécurité, monitoring, CI/CD et exploitation.",
        "mission": "Sécuriser l'infrastructure, prévoir le déploiement et garantir l'observabilité.",
        "sort_order": 40,
        "employees": [
            {"name": "Karim", "role": "DevSecOps", "avatar": "DS", "briefing": "Identifie les risques sécurité, secrets, accès, sauvegardes et CI/CD.", "sort_order": 10},
            {"name": "Inès", "role": "Cloud engineer", "avatar": "CE", "briefing": "Cadre les environnements Docker, reverse proxy, scaling et monitoring.", "sort_order": 20},
        ],
    },
    {
        "key": "orchestrator",
        "label": "Orchestrateur",
        "description": "Chef de projet IA qui affecte, arbitre et synthétise le travail.",
        "mission": "Affecter le projet, provoquer les critiques croisées et produire la synthèse finale.",
        "sort_order": 50,
        "employees": [
            {"name": "Sefako Orchestrateur", "role": "Chef de projet IA", "avatar": "SO", "briefing": "Coordonne les départements et arbitre les contradictions.", "sort_order": 10},
        ],
    },
]


def default_agency_dict() -> dict[str, dict]:
    return {department["key"]: department for department in DEFAULT_AGENCY_DEPARTMENTS}


def department_to_dict(department: Department) -> dict:
    return {
        "id": department.id,
        "key": department.key,
        "label": department.label,
        "description": department.description or "",
        "mission": department.mission or "",
        "sort_order": department.sort_order,
        "is_enabled": department.is_enabled,
        "employees": [
            {
                "id": employee.id,
                "name": employee.name,
                "role": employee.role,
                "avatar": employee.avatar,
                "briefing": employee.briefing or "",
                "sort_order": employee.sort_order,
                "is_enabled": employee.is_enabled,
            }
            for employee in sorted(department.employees, key=lambda item: item.sort_order)
            if employee.is_enabled
        ],
    }


async def seed_default_agency(db: AsyncSession) -> None:
    result = await db.execute(select(Department.key))
    existing = set(result.scalars().all())
    changed = False

    for item in DEFAULT_AGENCY_DEPARTMENTS:
        if item["key"] in existing:
            continue
        department = Department(
            key=item["key"],
            label=item["label"],
            description=item.get("description"),
            mission=item.get("mission"),
            sort_order=item.get("sort_order", 0),
            is_enabled=True,
        )
        for employee_data in item.get("employees", []):
            department.employees.append(Employee(
                name=employee_data["name"],
                role=employee_data["role"],
                avatar=employee_data["avatar"],
                briefing=employee_data.get("briefing"),
                sort_order=employee_data.get("sort_order", 0),
                is_enabled=True,
            ))
        db.add(department)
        changed = True

    if changed:
        await db.commit()


async def get_agency_departments(db: AsyncSession, include_disabled: bool = False) -> list[dict]:
    await seed_default_agency(db)
    stmt = select(Department).options(selectinload(Department.employees)).order_by(Department.sort_order)
    if not include_disabled:
        stmt = stmt.where(Department.is_enabled.is_(True))
    result = await db.execute(stmt)
    departments = result.scalars().all()
    return [department_to_dict(department) for department in departments]


async def get_employee_profiles(db: AsyncSession) -> dict[str, dict]:
    departments = await get_agency_departments(db)
    profiles: dict[str, dict] = {}
    for department in departments:
        employees = department.get("employees", [])
        if not employees:
            continue
        lead = employees[0]
        reviewer = employees[1] if len(employees) > 1 else employees[0]
        profiles[department["key"]] = {
            "lead": {"name": lead["name"], "role": lead["role"], "avatar": lead["avatar"]},
            "reviewer": {"name": reviewer["name"], "role": reviewer["role"], "avatar": reviewer["avatar"]},
            "label": department["label"],
            "mission": department.get("mission") or "",
        }
    return profiles
