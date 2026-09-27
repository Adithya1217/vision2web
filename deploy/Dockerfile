# Single-container image: Next.js (public, $PORT) + FastAPI (internal, 127.0.0.1:8000).
# Build from the repository root:  docker build -f deploy/Dockerfile .

FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_API_URL=/api/v1 NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim AS node

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend /src/.next/standalone frontend/
COPY --from=frontend /src/.next/static frontend/.next/static
COPY --from=frontend /src/public frontend/public
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh && useradd --create-home app && chown -R app /app
USER app
EXPOSE 10000
CMD ["/app/start.sh"]
