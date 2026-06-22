docker compose \
  -f docker-compose.yml \
  -f docker-compose.traefik.yml \
  -f docker-compose.dev.yml \
  ps


  docker compose \
  -f docker-compose.yml \
  -f docker-compose.traefik.yml \
  -f docker-compose.dev.yml \
  up -d





  cd /opt/sefako_ai_studio
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml build backend
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d backend



====pour passer en prod===
cd /opt/sefako_ai_studio
docker compose -f docker-compose.yml -f docker-compose.traefik.yml down
docker compose -f docker-compose.yml -f docker-compose.traefik.yml build
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d

puis verifie

docker compose -f docker-compose.yml -f docker-compose.traefik.yml ps
docker compose -f docker-compose.yml -f docker-compose.traefik.yml logs -f frontend backend

======



Oui.

Depuis le dossier du projet, après `docker compose down`:

**Mode dev**
```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d --build
```
docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml restart backend frontend

docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d --force-recreate backend

docker compose -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.dev.yml up -d --force-recreate openhands

**Mode prod**
```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build
```

Si tu veux repartir proprement avant de relancer:
```bash
docker compose down
```

Puis l’une des deux commandes ci-dessus.

Si tu veux, je peux aussi te donner la version exacte selon que tu lances ça:
1. sur le VPS direct
2. via `docker_manager`
3. en local sans Traefik