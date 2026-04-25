# Running S.A.M. with Docker

This is the operational playbook for the Dockerised S.A.M. backend. All commands assume your shell is in the project root.

> If the `docker` group hasn't taken effect for your user yet, prefix every command with `sudo`. To drop the prefix, run `newgrp docker` in this terminal (or log out and back in).

---

## 1. What's in the stack

`docker-compose.yml` brings up four services on a private `sam_default` bridge network:

| Service       | Image                   | Purpose                            | Port (host → container) |
|---------------|-------------------------|------------------------------------|-------------------------|
| `db`          | `postgres:15-alpine`    | Application database               | `5432 → 5432`           |
| `redis`       | `redis:7-alpine`        | Celery broker / cache / pub-sub    | `6379 → 6379`           |
| `backend`     | built from `./Dockerfile` | FastAPI app (uvicorn)            | `8000 → 8000`           |
| `worker`      | built from `./Dockerfile` | Celery worker (`src.worker`)     | none (internal only)    |

Persistent volume:

| Volume              | Mounted at (in container)        | What it holds            |
|---------------------|----------------------------------|--------------------------|
| `sam_postgres_data` | `/var/lib/postgresql/data`       | Postgres on-disk state   |

Project root is bind-mounted into `backend` and `worker` at `/app` for live code reloads in dev.

---

## 2. Prerequisites

- Docker Engine + Docker Compose plugin installed (`docker --version`, `docker compose version`).
- The `docker` daemon is running: `systemctl is-active docker` should print `active`.
- A populated `.env` in the project root (see next section).

---

## 3. Required `.env` keys

The backend calls `Config.validate()` at import time and exits with a `CRITICAL ERROR` line if any of these is missing.

```dotenv
# Postgres (consumed by the db service AND assembled into DATABASE_URL)
DB_USER=sam
DB_PASSWORD=samdev
DB_NAME=sam
DATABASE_URL=postgresql://sam:samdev@db:5432/sam

# Redis (must point at the compose service hostname, not localhost)
REDIS_URL=redis://redis:6379/0

# Auth
SECRET_KEY=<long random string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Google OAuth + Calendar/Gmail
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_PROJECT_ID=...
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_API_SCOPES=https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/gmail.send

# Outbound mail (Gmail App Password, not the account password)
SENDER_EMAIL=...
SENDER_PASSWORD=...

# NVIDIA (OpenAI-compatible LLM endpoint)
NVIDIA_API_KEY=...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1   # optional override
NVIDIA_MODEL_ID=google/gemma-3-27b-it                 # optional override

# WhatsApp Cloud API (Meta)
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...
WHATSAPP_GRAPH_VERSION=v20.0    # optional override
```

Hostnames `db` and `redis` are resolved by Docker's internal DNS — never use `localhost` from inside `backend`/`worker`.

If you don't have real WhatsApp credentials yet, you can use stub values (`=stub`) to bring the rest of the platform up; only `/webhooks/whatsapp` will be broken until you replace them.

---

## 4. First-time bring-up

```bash
docker compose up -d --build
docker compose ps
```

Initial build is slow (~10–25 min) because pip has to compile psycopg2 and download the full ML/web stack. Subsequent builds are seconds because layers are cached.

`docker compose ps` should converge to:

```
sam-db-1       postgres:15-alpine   Up (healthy)   0.0.0.0:5432->5432/tcp
sam-redis-1    redis:7-alpine       Up             0.0.0.0:6379->6379/tcp
sam-backend-1  sam-backend          Up (healthy)   0.0.0.0:8000->8000/tcp
sam-worker-1   sam-worker           Up
```

The `backend` healthcheck polls `/api/v1/health` every 30 s. It can take ~20 s after start to flip from `health: starting` to `healthy`.

The `worker` container shows `health: starting → unhealthy` because it doesn't expose HTTP — that's expected and harmless. It still works.

---

## 5. Initialise the database schema (one-time per fresh DB)

```bash
docker compose exec backend python scripts/init_meetings_tables.py
docker compose exec backend python scripts/migrate_v3_features.py
docker compose exec backend python scripts/migrate_phone_and_student.py
```

Run these only on a fresh Postgres volume. Re-running them is generally safe (the scripts use `IF NOT EXISTS`), but unnecessary.

---

## 6. Smoke-test the API

From the host:

```bash
curl -s http://localhost:8000/                          # root health
curl -s http://localhost:8000/api/v1/health | python -m json.tool   # full dependency report
curl -s -o /dev/null -w "docs: %{http_code}\n" http://localhost:8000/docs   # Swagger UI
```

A healthy response from `/api/v1/health` looks like:

```json
"summary": { "total_endpoints": 35, "live": 33, "broken": 2, ... },
"dependencies": {
  "database":      {"status": "live"},
  "redis":         {"status": "live"},
  "llm_nvidia":    {"status": "live"},
  "google_oauth":  {"status": "live"},
  "smtp":          {"status": "live"},
  "whatsapp_graph":{"status": "live"}
}
```

Any `broken` dependency is reflected in the per-route list with a `broken_due_to` field. Fix the underlying credential / network issue and the routes flip back automatically.

To exercise an authenticated endpoint, mint a JWT inside the container:

```bash
TOKEN=$(docker compose exec -T backend python -c "
import time, jwt
from src.utils.config_loader import Config
print(jwt.encode({'user_id': 1, 'org_id': 1, 'email': 'dev@local',
                  'exp': int(time.time())+3600},
                 Config.SECRET_KEY, algorithm=Config.ALGORITHM))
")
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/test-secure | python -m json.tool
```

---

## 7. Run the test suite

```bash
docker compose exec backend python -m unittest discover -s tests -v
```

Just the new health-endpoint tests:

```bash
docker compose exec backend python -m unittest tests.test_health_endpoint -v
```

---

## 8. Day-to-day operations

| Task                                          | Command                                              |
|-----------------------------------------------|------------------------------------------------------|
| Start the stack                               | `docker compose up -d`                               |
| Stop the stack (data preserved)               | `docker compose down`                                |
| Stop and **wipe** the Postgres volume         | `docker compose down -v`                             |
| Restart one service (re-reads `.env`)         | `docker compose restart backend worker`              |
| Rebuild image after Dockerfile / req changes  | `docker compose up -d --build`                       |
| Tail backend logs                             | `docker compose logs -f backend`                     |
| Tail all logs                                 | `docker compose logs -f`                             |
| Last 100 lines of one service                 | `docker compose logs backend --tail=100`             |
| Open a shell in a running container           | `docker compose exec backend bash`                   |
| One-off command (no shell)                    | `docker compose exec backend python -V`              |
| Status of every service                       | `docker compose ps`                                  |
| Resource usage                                | `docker stats`                                       |

`.env` is loaded by `python-dotenv` at process startup, so any change to it requires a **container restart** (not just a uvicorn reload). Code changes under `src/` are picked up live via uvicorn `--reload` because the project root is bind-mounted into the container.

---

## 9. Ports exposed on the host

| Port | Service   | URL                                |
|------|-----------|------------------------------------|
| 8000 | `backend` | http://localhost:8000              |
| 5432 | `db`      | `postgres://sam:samdev@localhost:5432/sam` |
| 6379 | `redis`   | `redis://localhost:6379/0`         |

Backend Swagger UI: http://localhost:8000/docs
Backend OpenAPI JSON: http://localhost:8000/openapi.json
Public health endpoint: http://localhost:8000/api/v1/health

---

## 10. Troubleshooting

**`CRITICAL ERROR: Missing configuration keys in .env`** — one of the keys in section 3 is unset. Add it, then `docker compose restart backend worker`.

**`backend` healthcheck stays `starting`/`unhealthy`** — `docker compose logs backend --tail=80`. Most common causes: missing `.env` keys, `DATABASE_URL` pointing at `localhost` instead of `db`, or a Python import error. Postgres being unreachable also blocks startup.

**`/api/v1/health` reports `database: broken`** — usually `DATABASE_URL` is wrong, or the db container is still booting. `docker compose ps` should show `sam-db-1` as `Up (healthy)`.

**`/api/v1/health` reports `smtp: probe timed out`** — Gmail STARTTLS auth can be slow; the probe budget is 5 s. If it consistently times out, your `SENDER_PASSWORD` is probably your regular Google password instead of an App Password. Generate one at *Google Account → Security → 2-Step Verification → App passwords*.

**`/api/v1/health` reports `whatsapp_graph: HTTP 401`** — the `WHATSAPP_*` values are wrong (or are still `stub`). Replace them with real Meta Cloud API credentials and restart the backend.

**`Container sam-db-1 is unhealthy`** during `up` — Postgres took longer than compose waited. Just re-run `docker compose up -d` once db is up; the dependent services will start.

**Build context is hundreds of MB** — `.dockerignore` excludes the obvious offenders (`.git`, `.venv`, `__pycache__`, `data/uploads`, etc.). If you've added a heavy directory (e.g. local virtualenv, model weights), append it to `.dockerignore` and rebuild.

**Code changes aren't picked up** — uvicorn's `--reload` watches the bind mount, but inotify can be flaky on bind mounts from NTFS partitions. Workaround: `docker compose restart backend`.

**Permission denied on `docker` commands** — your user isn't in the `docker` group yet, or the group hasn't been re-evaluated for this shell. Run `newgrp docker` (current shell only) or log out/in (system-wide).

---

## 11. Tearing it all down

```bash
docker compose down -v          # stop containers + remove the postgres volume
docker rmi sam-backend sam-worker   # optional: remove the built images
docker system prune -f          # optional: reclaim space from dangling layers
```
