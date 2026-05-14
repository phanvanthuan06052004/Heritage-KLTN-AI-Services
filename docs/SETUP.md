# Setup Guide

Two ways to run Heritage AI Services: **Docker** (recommended for production) or **Development** (for local development and contributing).

---

## Option A — Docker (Production)

### Prerequisites
- Docker Engine 24+
- Docker Compose v2+
- An API key for your AI provider (Google, OpenAI, or Anthropic)

### 1. Clone and configure

```bash
git clone https://github.com/nduckmink/heritage-ai.git
cd heritage-ai
cp .env.docker.example .env.docker
```

> Heritage AI Services ships **two** env templates: `.env.docker.example` for `docker compose`, and `.env.local.example` for local development (Option B). They differ only in service hostnames (container names vs. `localhost`).

Edit `.env.docker`:

```env
# Required: generate a strong random secret
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_urlsafe(32))">

# Required: admin account created on first startup
DEFAULT_ADMIN_EMAIL=admin@yourcompany.com
DEFAULT_ADMIN_PASSWORD=your-secure-password

# Required: PostgreSQL credentials — must be consistent across all three vars and DATABASE_URL
POSTGRES_USER=heritage-ai
POSTGRES_PASSWORD=your-postgres-password
POSTGRES_DB=heritage-ai
DATABASE_URL=postgresql+asyncpg://heritage-ai:your-postgres-password@postgres:5432/heritage-ai

# Required: MinIO credentials — MINIO_ACCESS_KEY / MINIO_SECRET_KEY initialise the MinIO
# container on first run; changing them after first start requires resetting the volume
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=your-minio-secret

# Optional: restrict CORS in production
CORS_ORIGINS=https://your-domain.com

# Required: your public API URL (used by the frontend browser)
NEXT_PUBLIC_API_URL=https://your-domain.com
```

> The full `.env.docker.example` documents every available variable.

### 2. Start

```bash
docker compose --env-file .env.docker up -d --build
```

This starts all containers:
| Container | Purpose |
|---|---|
| `heritage-ai_postgres` | PostgreSQL 16 with pgvector (port 5432) |
| `heritage-ai_redis` | Redis 7 job queue (port 6379) |
| `heritage-ai_minio` | MinIO file storage (port 9000, console 9001) |
| `heritage-ai_api` | FastAPI backend + MCP server (port 5055) |
| `heritage-ai_worker` | Background worker — document ingestion + wiki compilation |
| `heritage-ai_worker_skills` | Background worker — AI skill processing |
| `heritage-ai_frontend` | Next.js admin portal (port 3119) |

Workers start only after `heritage-ai_api` passes its health check, so there is no race condition on startup.

> **Important:** always pass `--env-file .env.docker` explicitly — both for `build` and `up`. Without it, Docker Compose falls back to `.env` (your local dev config). This causes two classes of errors:
> - MinIO `SignatureDoesNotMatch` — credentials mismatch
> - Frontend still calls `localhost:5055` — `NEXT_PUBLIC_API_URL` is a **build-time** variable baked into the JS bundle by Next.js. Changing `.env.docker` and restarting the container has no effect; you must rebuild the image with the correct `--env-file`.

### 3. First login

Open **http://your-server:3119** and log in with the credentials from `.env.docker`.

### 4. Configure AI providers

Go to **Settings** and configure:

| Setting | Required | Notes |
|---|---|---|
| **Embedding model** | Yes | Used for semantic wiki search. E.g. `text-embedding-004` (Google) |
| **LLM** | Yes | Used for wiki compilation. Choose a large-context model. |
| **Vision model** | No | Enables image captioning during PDF ingestion |

Recommended LLMs for wiki compilation (large context window):
- `gemini-2.5-pro` (Google) — best results
- `gpt-4o` (OpenAI)
- `claude-sonnet-4-5` or newer (Anthropic)

### 5. Run database migrations

```bash
docker exec heritage-ai_api alembic upgrade head
```

> On first startup, the API runs migrations automatically before serving requests. You only need to run this manually after upgrading Heritage AI Services.

---

## Option A2 — Deploying to a Linux server

This section covers what changes when running on a remote server (Ubuntu 22.04+ recommended) instead of a local machine.

### 1. Install Docker Engine

On the server (do **not** install Docker Desktop — use Docker Engine directly):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

Verify:

```bash
docker version
docker compose version   # must be v2+
```

### 2. Open firewall ports

Heritage AI Services needs these ports accessible from users' browsers:

```bash
sudo ufw allow 3119/tcp   # Frontend
sudo ufw allow 5055/tcp   # API (and MCP endpoint)
sudo ufw allow 9000/tcp   # MinIO (presigned file URLs)
sudo ufw enable
```

> Do **not** expose port 5432 (PostgreSQL), 6379 (Redis), or 9001 (MinIO console) externally.

### 3. Clone and configure

```bash
git clone https://github.com/nduckmink/heritage-ai.git
cd heritage-ai
cp .env.docker.example .env.docker
```

Edit `.env.docker` — the key differences from local Docker setup:

```env
# Generate strong secrets
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(32))">
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=heritage-ai
DATABASE_URL=postgresql+asyncpg://heritage-ai:<strong-random-password>@postgres:5432/heritage-ai
MINIO_SECRET_KEY=<strong-random-password>

# Admin account
DEFAULT_ADMIN_EMAIL=admin@yourcompany.com
DEFAULT_ADMIN_PASSWORD=<strong-password>

# Use the server's public IP or domain — NOT localhost
MINIO_PUBLIC_ENDPOINT=<server-ip-or-domain>:9000
NEXT_PUBLIC_API_URL=http://<server-ip-or-domain>:5055

# Restrict CORS to your frontend URL
CORS_ORIGINS=http://<server-ip-or-domain>:3119
```

> **`MINIO_PUBLIC_ENDPOINT` is the most important difference.** On a local machine it's `localhost:9000`. On a server it must be the server's public IP or domain, otherwise presigned image/file URLs will point to an unreachable address.

### 4. Start

```bash
docker compose --env-file .env.docker up -d --build
```

Check all containers are healthy:

```bash
docker compose ps
```

All services should show `healthy` or `running`. The `worker` and `worker_skills` containers start only after `heritage-ai_api` passes its health check (~30 seconds).

### 5. Verify

```bash
# API health
curl http://localhost:5055/health

# Should return: {"status": "ok", ...}
```

Open `http://<server-ip>:3119` from your browser and log in.

---

### Optional: Nginx reverse proxy (custom domain + SSL)

If you have a domain and want HTTPS, put Nginx in front:

```nginx
# /etc/nginx/sites-available/heritage-ai
server {
    listen 80;
    server_name heritage-ai.yourcompany.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name heritage-ai.yourcompany.com;

    ssl_certificate     /etc/letsencrypt/live/heritage-ai.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/heritage-ai.yourcompany.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://localhost:3119;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:5055;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # MCP
    location /mcp {
        proxy_pass http://localhost:5055;
        proxy_set_header Host $host;
    }
}

# MinIO (for presigned URLs)
server {
    listen 443 ssl;
    server_name minio.yourcompany.com;

    ssl_certificate     /etc/letsencrypt/live/minio.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/minio.yourcompany.com/privkey.pem;

    location / {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
    }
}
```

With HTTPS, update `.env.docker`:

```env
NEXT_PUBLIC_API_URL=https://heritage-ai.yourcompany.com
MINIO_PUBLIC_ENDPOINT=minio.yourcompany.com
MINIO_SECURE=true
CORS_ORIGINS=https://heritage-ai.yourcompany.com
```

Then get a certificate with Certbot:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d heritage-ai.yourcompany.com -d minio.yourcompany.com
```

Restart containers after changing env:

```bash
docker compose --env-file .env.docker up -d --build
```

---

## Option B — Development

### Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 – 3.14 | Backend runtime |
| Node.js | 20+ | Frontend (Next.js) |
| PostgreSQL | 15+ with pgvector | Main database |
| Redis | 7+ | Background job queue |
| MinIO | Latest | File storage |

### 1. Infrastructure

Start infrastructure services with Docker:

```bash
# PostgreSQL with pgvector
docker run -d --name heritage-ai-pg \
  -e POSTGRES_USER=heritage-ai \
  -e POSTGRES_PASSWORD=heritage-ai_secret \
  -e POSTGRES_DB=heritage-ai \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Redis
docker run -d --name heritage-ai-redis -p 6379:6379 redis:7-alpine

# MinIO
docker run -d --name heritage-ai-minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin123 \
  -p 9000:9000 -p 9001:9001 \
  minio/minio server /data --console-address ":9001"
```

### 2. Configure environment

```bash
cp .env.local.example .env.local
```

For local development, the defaults in `.env.local.example` work out of the box except:

```env
SECRET_KEY=dev-only-not-for-production
DEFAULT_ADMIN_EMAIL=admin@heritage-ai.local
DEFAULT_ADMIN_PASSWORD=admin123
MINIO_SECRET_KEY=minioadmin123
```

### 3. Python backend

```bash
# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head
```

### 4. Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:5055
```

### 5. Start all services (3 terminals)

**Terminal 1 — API server:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 5055 --reload
```

On first startup you should see:
```
SUCCESS  MinIO bucket ready
SUCCESS  Default admin created: admin@heritage-ai.local
SUCCESS  Heritage AI Services MCP Server ready at /mcp
SUCCESS  Heritage AI Services API started successfully
```

**Terminal 2 — Wiki worker:**
```bash
python -m arq app.worker.WorkerSettings
```

**Terminal 3 — Frontend:**
```bash
cd frontend
npm run dev
```

Open **http://localhost:3000**.

> Documents will stay at `pending` status until the worker is running.

---

## First steps after setup

### 1. Configure AI providers
Settings → configure embedding model, LLM, and vision model.

### 2. Create a department
Admin Portal → Departments → New Department.

### 3. Create a knowledge type
Admin Portal → Knowledge Types → New Type (e.g. "SOP", "Product Docs").

### 4. Upload a document
Knowledge Base → Upload → select file or paste URL → choose knowledge type → submit.

Watch the progress indicator. Once complete, click Wiki to browse the compiled pages.

### 5. Create an employee and generate an MCP token
Admin Portal → Employees → New Employee → assign department and role.

On the employee detail page, click **Generate Token** to create their MCP token.

### 6. Connect Claude Desktop
See [MCP & Claude](MCP.md) for the connection guide.

---

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `heritage-ai` | PostgreSQL username — used to initialise the postgres container |
| `POSTGRES_PASSWORD` | — | PostgreSQL password — must match the value in `DATABASE_URL` |
| `POSTGRES_DB` | `heritage-ai` | PostgreSQL database name — must match the value in `DATABASE_URL` |
| `DATABASE_URL` | — | Full asyncpg connection string — must be consistent with `POSTGRES_*` vars |
| `SECRET_KEY` | — | JWT signing secret. Must be changed in production. |
| `DEFAULT_ADMIN_EMAIL` | `admin@heritage-ai.local` | Admin account email (created on first startup) |
| `DEFAULT_ADMIN_PASSWORD` | `admin123` | Admin account password |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO server address used internally by the API (Docker service name; local: `localhost:9000`) |
| `MINIO_PUBLIC_ENDPOINT` | _(same as `MINIO_ENDPOINT`)_ | Public MinIO address embedded in presigned URLs. Must be browser-accessible: `localhost:9000` on local Docker, `<server-ip>:9000` on a remote server |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO root user — initialises the container on first run |
| `MINIO_SECRET_KEY` | — | MinIO root password — initialises the container on first run; changing it after first start requires `docker compose down -v` |
| `MINIO_BUCKET` | `heritage-ai-files` | Bucket name for uploaded files |
| `MINIO_SECURE` | `false` | Use HTTPS for MinIO (`true` in production) |
| `REDIS_HOST` | `redis` | Redis host (Docker: service name; local: `localhost`) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | _(empty)_ | Redis password |
| `WORKER_MAX_JOBS` | `3` | Max concurrent background jobs |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:5055` | Public API URL (used by the browser) |
| `INTERNAL_API_URL` | `http://api:5055` | Internal API URL used by the Next.js server for proxying (Docker only) |

AI provider settings (embedding, LLM, vision, API keys) are configured through the Admin Portal → Settings, not in env files.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `connection refused` on port 5432 | PostgreSQL not running |
| `pgvector extension not found` | Use `pgvector/pgvector` Docker image |
| Documents stuck at `pending` | Wiki worker not running |
| Wiki pages not created after upload | Check LLM config in Settings; check worker logs |
| Frontend shows API error | Backend not running, or `NEXT_PUBLIC_API_URL` incorrect |
| CORS errors in browser | Add frontend URL to `CORS_ORIGINS` in `.env.docker` (or `.env.local` for dev) |
| `requires Python 3.11` | Use `py -3.11 -m venv .venv` to select correct version |
| MCP connection refused | Ensure the API is accessible from outside (check firewall/proxy) |
| MinIO `SignatureDoesNotMatch` | Credentials mismatch — likely caused by running `docker compose up` without `--env-file .env.docker`, which makes Docker Compose use your local `.env` to initialise MinIO. Fix: `docker compose down -v` then `docker compose --env-file .env.docker up -d --build` |
| MinIO `Invalid Request (invalid hostname)` | `MINIO_ENDPOINT` contains an underscore (e.g. `heritage-ai_minio`). Use the Docker Compose service name instead: `minio:9000` |
| Images/files not loading in browser (`ERR_NAME_NOT_RESOLVED`) | Presigned URLs are pointing to an internal hostname. Set `MINIO_PUBLIC_ENDPOINT` to a browser-accessible address: `localhost:9000` for local Docker, `<server-ip>:9000` for a remote server |
| Frontend still calls `localhost:5055` after changing `NEXT_PUBLIC_API_URL` | `NEXT_PUBLIC_*` variables in Next.js are baked into the bundle at **build time**, not runtime. Changing `.env.docker` and restarting the container has no effect. You must rebuild the image: `docker compose --env-file .env.docker build --no-cache frontend && docker compose --env-file .env.docker up -d` |
