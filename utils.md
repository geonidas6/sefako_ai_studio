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