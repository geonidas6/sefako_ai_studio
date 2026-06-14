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