# Cahier des Charges : Projet "Agence IA Automatisée" (AIA)

**Version :** 1.2  
**Date :** Juin 2026  
**Auteur :** Sefako  
**Statut :** En cours de validation

---

## 1. Vision & Justification (Le Pourquoi)

### 1.1 La Raison (Le Constat)

Le développement logiciel traditionnel est devenu trop lent par rapport à l'évolution des idées. Les développeurs perdent un temps précieux sur la configuration, la structure répétitive et la coordination, au détriment de l'innovation et de l'expérience utilisateur.

### 1.2 La Cause (Le Problème)

Il existe un fossé entre **l'idée** (le besoin client) et **l'exécution** (le code fonctionnel). Ce fossé est causé par :

- Des erreurs de communication et d'interprétation des besoins.
- Une mauvaise anticipation des contraintes UX et sociales.
- Une architecture technique souvent mal préparée dès le départ.
- Un manque de standardisation des livrables entre les équipes.

### 1.3 L'Objectif

Créer une plateforme capable de **transformer instantanément des données non structurées** (notes de réunion, ébauches d'idées, PDF, audio) en un système de développement complet. L'objectif est d'atteindre une **automatisation de l'excellence** où l'IA ne se contente pas de coder, mais *réfléchit* et *débat* comme une équipe d'agence de haut niveau, sous supervision humaine.

### 1.4 Mode d'Interaction

L'AIA sera accessible via une **interface web (application Flutter Web / Desktop)**. L'utilisateur soumet son input via une interface conversationnelle. L'orchestrateur distribue le travail aux agents et restitue les livrables dans un tableau de bord structuré.

---

## 2. Description Fonctionnelle (Le Système Multi-Agents)

L'application agit comme un **orchestrateur central**. Elle reçoit les inputs et les transmet à quatre **Départements IA** qui collaborent et se challengent mutuellement :

| Département | Rôle | Outputs |
|---|---|---|
| **Stratégie & Growth** | Analyse la viabilité, le marché, définit les KPIs | Analyse marché, KPIs, positionnement |
| **Conception & UX** | Modélise le parcours utilisateur, anticipe la friction, définit l'ergonomie | User stories, wireframes textuels, matrice UX |
| **Ingénierie & Architecture** | Définit la stack, crée le MCD, assure la modularité | MCD, diagrammes de flux, architecture modulaire |
| **DevOps & Sécurité** | Configure l'infrastructure, sécurise les flux, planifie la maintenance | Docker Compose, checklist sécurité, CI/CD config |

### 2.1 Mécanisme de Débat Contradictoire

Le "brainstorming" entre agents n'est pas un simple échange séquentiel. Il suit un protocole structuré en **3 rounds** orchestré via **LangGraph** :

1. **Round 1 — Proposition :** Chaque département produit son analyse initiale en parallèle.
2. **Round 2 — Critique :** Chaque département examine les outputs des autres et soulève des objections formelles (ex : le département Ingénierie peut rejeter une feature UX si elle est techniquement non viable dans le délai prévu).
3. **Round 3 — Consensus :** L'orchestrateur synthétise les positions et produit une version consolidée soumise au Point de Contrôle Humain.

> **Choix d'orchestration : LangGraph** (vs CrewAI). LangGraph est retenu pour son contrôle fin des flux d'états et la gestion explicite des boucles de révision entre agents. CrewAI sera évalué pour les versions ultérieures si la vélocité de prototypage prime.

---

## 3. Spécifications Techniques (La Stack Sefako)

### 3.1 Stack Principale

| Couche | Technologie | Justification |
|---|---|---|
| **Front-end** | Flutter (Web + Desktop) | Multiplateforme, interface hautement réactive, UI riche |
| **Back-end** | Python / FastAPI | Puissance de calcul, gestion asynchrone, intégration native LLM |
| **Orchestration** | LangGraph | Contrôle fin des flux d'états multi-agents, gestion des révisions |
| **Intelligence** | Multi-LLM (Gemini, Grok, Claude, GPT-4…) | Abstraction via couche LLM Router — configurable par l'admin |
| **Infrastructure** | Docker Compose + Traefik + CrowdSec | Isolation des services, reverse proxy sécurisé, protection IPS |

### 3.2 Pipeline de Génération du MCD

La transformation d'un input non structuré vers un MCD valide suit ce pipeline interne :

```
Input brut (texte/PDF/audio)
    │
    ▼
[Agent Ingénierie] Extraction des entités métier
    │  → Identification des noms, verbes, relations clés
    ▼
[Agent Ingénierie] Proposition du MCD v1
    │
    ▼
[Agent UX] Validation des entités côté parcours utilisateur
    │  → Vérification : chaque entité est-elle accessible/utile en front ?
    ▼
[Agent DevOps] Validation des entités côté infrastructure
    │  → Vérification : volumétrie, index nécessaires, contraintes de sécurité
    ▼
[Orchestrateur] MCD consolidé v2 → soumis au Point de Contrôle Humain
```

### 3.3 Types de Projets Supportés (MVP)

L'AIA génère du code pour des projets **FastAPI (back-end) + Flutter (front-end)** en priorité. Le support d'autres stacks (Next.js, Django, etc.) est prévu en **Phase 3**.

---

### 3.4 Gestion Multi-LLM (Admin Panel)

L'AIA n'est **pas liée à un seul fournisseur d'IA**. Elle intègre une couche d'abstraction **LLM Router** qui permet à l'administrateur de configurer et combiner plusieurs modèles selon ses besoins et son budget.

#### 3.4.1 Fournisseurs Supportés

| Fournisseur | Modèles cibles | Points forts |
|---|---|---|
| **Google Gemini** | Gemini 2.5 Pro / Flash | Contexte long, multimodal, raisonnement |
| **xAI Grok** | Grok-3 / Grok-3 Mini | Vitesse, données temps réel via X |
| **Anthropic Claude** | Claude Opus 4 / Sonnet 4 | Précision, rédaction, analyse nuancée |
| **OpenAI GPT** | GPT-4o / o3 | Polyvalence, large écosystème |
| **Mistral** | Mistral Large / Codestral | Open-source, optimisé pour le code |
| **LLM local (Ollama)** | LLaMA 3, Qwen, DeepSeek | Confidentialité totale, coût zéro |

> D'autres fournisseurs peuvent être ajoutés via l'interface admin sans modification du code source.

#### 3.4.2 Interface d'Administration LLM

L'admin accède à un **panneau de configuration dédié** avec les fonctionnalités suivantes :

- **Activation / Désactivation** de chaque fournisseur (toggle ON/OFF).
- **Saisie des clés API** par fournisseur (stockées chiffrées en base, jamais en clair).
- **Sélection du modèle actif** par fournisseur (ex : choisir `gemini-2.5-flash` vs `gemini-2.5-pro`).
- **Assignation par Département** : chaque département IA peut utiliser un LLM différent.
- **Mode Failover** : si le LLM principal est indisponible, basculement automatique sur le LLM de secours configuré.
- **Monitoring des coûts** : tableau de bord des tokens consommés et coût estimé par fournisseur.

#### 3.4.3 Assignation par Département IA

L'admin peut assigner un LLM spécifique à chaque département pour optimiser le rapport qualité/coût :

```
Département Stratégie & Growth   → Gemini 2.5 Pro   (raisonnement profond)
Département Conception & UX      → Claude Sonnet 4  (nuance, créativité)
Département Ingénierie           → Mistral Codestral (optimisé code)
Département DevOps & Sécurité    → Grok-3 Mini      (vitesse, règles précises)
Orchéstrateur (synthèse)         → Gemini 2.5 Pro   (contexte long)
```

> Cette configuration est modifiable à tout moment depuis le panneau admin, sans redémarrage du système.

#### 3.4.4 Architecture Technique du LLM Router

```
                    ┌──────────────────────┐
    Agents LangGraph │    LLM Router        │
    ─────────────── ▶│  (couche d'abstraction)│
                    │                      │
                    └──┬───┬───┬───┬───┬───┘
                       │   │   │   │   │
                    Gemini Grok Claude GPT Ollama
                     API   API   API  API (local)
```

Le LLM Router expose une interface unifiée (`generate(prompt, config)`) et gère :
- La sérialisation des prompts selon le format de chaque provider.
- La gestion des rate limits et retries.
- Le logging des appels pour le monitoring des coûts.

---

## 4. Workflow de Production (Le Cycle de Vie d'un Projet)

```
┌─────────────────────────────────────────────────────────┐
│  PHASE 1 : RÉCEPTION                                    │
│  Input → Notes / PDF / Audio / Idée brute               │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  PHASE 2 : BRAINSTORMING IA (3 Rounds contradictoires)  │
│  4 Départements → Proposition → Critique → Consensus    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  PHASE 3 : POINT DE CONTRÔLE HUMAIN ✅                  │
│  Validation des orientations stratégiques + MCD         │
│  L'utilisateur peut corriger, rejeter ou valider        │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  PHASE 4 : BUILD ITÉRATIF                               │
│  Génération module par module                           │
│  Validation automatique par l'agent DevOps à chaque PR  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  PHASE 5 : SYNTHÈSE FINALE                              │
│  Export : CDC final + MCD + Roadmap + Code source       │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Livrables Attendus

L'application doit produire automatiquement les livrables suivants, **par projet** :

### 5.1 Documentation

- **Cahier des charges complet** : Analyse de marché, objectifs, KPIs, hors-scope.
- **Architecture technique** : Schémas MCD (format texte Mermaid + PNG exportable), diagrammes de flux des agents.
- **Roadmap détaillée** : Du MVP au déploiement, avec estimations de durée par phase.

### 5.2 Code Source

- **Back-end FastAPI** : Structure modulaire (routers, services, repositories), modèles Pydantic, migrations Alembic.
- **Front-end Flutter** : Composants réutilisables, navigation, gestion d'état (Riverpod).
- **Infrastructure** : `docker-compose.yml`, configuration Traefik, fichiers `.env.example`.

### 5.3 Qualité

- **Tests unitaires** générés pour les routes critiques.
- **Checklist sécurité** produite par l'agent DevOps.
- **README** de déploiement pour chaque projet.

---

## 6. Contraintes & Hors-Scope (MVP v1)

### 6.1 Contraintes Techniques

- Le code généré **nécessite une revue humaine finale** avant déploiement en production. L'AIA ne garantit pas un code production-ready sans validation.
- Les projets dépassant **15 modules métier** sont hors scope du MVP — ils seront découpés en sous-projets.
- L'audio en input est limité à **60 minutes** et aux langues **français / anglais**.

### 6.2 Hors-Scope (Phase 1)

- ❌ Génération de code mobile natif (iOS Swift / Android Kotlin).
- ❌ Support de stacks autres que FastAPI + Flutter.
- ❌ Déploiement automatique en production (CI/CD d'intégration seulement).
- ❌ Gestion multi-utilisateurs / collaboration temps réel.

---

## 7. Métriques de Succès

L'AIA sera considérée comme fonctionnelle si elle atteint les critères suivants :

| Métrique | Cible MVP | Méthode de Mesure |
|---|---|---|
| Temps de génération d'un CDC complet | < 5 minutes | Mesure chronométrique |
| Pertinence du MCD généré | Validé sans modification majeure dans ≥ 70% des cas | Feedback utilisateur |
| Qualité du code (tests passants) | ≥ 80% des tests unitaires générés passent | CI automatisée |
| Satisfaction utilisateur | Score NPS > 50 | Questionnaire post-session |
| Réduction du temps de cadrage projet | − 60% vs méthode manuelle | Comparaison avec baseline |

---

## 8. Roadmap (Phases du Projet)

### Phase 1 — MVP (Mois 1–3)
- Orchestrateur LangGraph fonctionnel avec 4 agents.
- Interface Flutter Web minimaliste (input + tableau de bord de résultats).
- Génération de CDC + MCD textuel + architecture de base.
- Stack : FastAPI + Flutter uniquement.
- **LLM Router** avec support Gemini + Grok + Claude (admin panel de configuration).
- Panneau admin : gestion des clés API, sélection du modèle actif, assignation par département.

### Phase 2 — Consolidation (Mois 4–6)
- Ajout de la génération de code modulaire (FastAPI + Flutter).
- Export PDF des livrables.
- Amélioration du débat contradictoire (scoring des objections).
- Tests automatisés générés par l'agent DevOps.

### Phase 3 — Expansion (Mois 7–12)
- Support multi-stack (Next.js, Django, etc.).
- Collaboration multi-utilisateurs.
- Déploiement CI/CD automatisé.
- Évaluation de CrewAI comme alternative à LangGraph.
- Marketplace de templates de projets pré-configurés.

---

*Ce document est vivant. Il sera mis à jour à chaque jalon de validation.*
