# Project Rules

## Deployment & Service Management

**NEVER start local services (uvicorn, vite dev server, etc.) when Docker containers are managing the deployment.**

Before starting/restarting any service:
1. Read `docker-compose.yml` first to understand the deployment setup
2. Check which ports Docker maps to (e.g., 8090->8000, 3010->3000)
3. Use `docker compose restart` or `docker compose up -d --build` — not local processes
4. Starting local services on different ports creates conflicts and wastes time

This project runs via Docker Compose: api (8090), frontend (3010), flower (5555), postgres (5432), redis (6379), worker.

## Skill Usage Preferences

Do not use `superpowers` or `dev-pipeline` unless the user explicitly asks for either skill by name or explicitly requests that workflow.
