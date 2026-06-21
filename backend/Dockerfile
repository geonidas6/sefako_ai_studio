FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl ca-certificates nodejs npm && rm -rf /var/lib/apt/lists/*

RUN npm install -g @qwen-code/qwen-code@latest && mkdir -p /root/.qwen

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY app ./app

# Install the package from the local source tree so the app code is available
# during wheel building.
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
