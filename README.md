# Sefako AI Studio

Plateforme d'agence IA multi-agents basée sur FastAPI, Next.js, PostgreSQL et LangGraph.

## Démarrage via Docker Manager

Le dépôt est prêt pour être importé dans `docker_manager` grâce à :

- `docker-manager.yml`
- `docker-compose.yml`
- `docker-compose.traefik.yml`
- `.env.example`

### Variables à préparer

1. Copie `.env.example` en `.env`.
2. Renseigne au minimum :
   - `SECRET_KEY`
   - `ADMIN_PASSWORD`
   - `ENCRYPTION_KEY` si tu veux chiffrer les clés LLM
   - `FRONTEND_DOMAIN`
   - `API_DOMAIN`

### Déploiement manuel

```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build
```

Si tu déploies sans Traefik, lance simplement :

```bash
docker compose up -d --build
```

### Mode développement sans rebuild

Pour modifier le backend ou le frontend sans reconstruire les images à chaque changement, utilise l'override de développement :

```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d
```

Ce mode active :

- Backend FastAPI en `uvicorn --reload`
- Montage de `./backend/app` vers `/app/app`
- Frontend Next.js en `next dev`
- Montage de `./frontend` vers `/app`
- Volumes Docker pour garder `node_modules` et `.next`

Si tu ajoutes ou modifies des dépendances Python/Node, il faut quand même reconstruire :

```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d --build
```

Pour revenir au mode production :

```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build
```

## Services

- Frontend: Next.js
- Backend: FastAPI
- Base de données: PostgreSQL 16
- Orchestration IA: LangGraph

## Points d'accès

- Frontend: `https://sefako-ai-studio.it-sefako.com`
- API: `https://api-sefako-ai-studio.it-sefako.com`
- Health API: `/health`

## Fonctionnement

1. Créer un projet depuis le studio.
2. Ouvrir la page du projet.
3. Lancer le workflow multi-agents.
4. Consulter les analyses Round 1, les critiques Round 2 et les livrables finaux Round 3.

## Remarques

- Le projet repose sur des clés LLM optionnelles. Sans clé, le mode `mock` prend le relais.
- Les modèles et assignations sont configurables depuis le panneau admin.
