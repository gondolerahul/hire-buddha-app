# Quick Start Guide

Get the HireBuddha platform running on a fresh machine in under 10 minutes.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Poetry | latest | `poetry --version` |
| Node.js | 20 LTS | `node --version` |
| Docker | 24+ | `docker --version` |
| Git | any | `git --version` |

> **New VM?** Run `./setup_production_vm.sh` first — it installs all prerequisites automatically.

---

## 1. Clone & Install

```bash
git clone https://github.com/gondolerahul/hb-proto-3.git
cd hb-proto-3

# Backend dependencies (Poetry)
cd backend
poetry install
cd ..

# Frontend dependencies (npm)
cd frontend
npm install --legacy-peer-deps
cd ..
```

## 2. Configure Environment

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Set production values for `SECRET_KEY`, `DATABASE_URL`, and `CORS_ORIGINS`. See `backend/.env.example` for all options.

## 3. Start Infrastructure

```bash
cd backend
docker compose up -d db redis
```

Wait a few seconds, then verify:

```bash
docker ps
# Should show hirebuddha-db (port 5433) and hirebuddha-redis (port 6379)
```

## 4. Initialize Database

```bash
cd backend

# Run migrations
.venv/bin/alembic upgrade head

# Seed the admin user
.venv/bin/python db-scripts/seed_admin_user.py
```

## 5. Start All Services

```bash
# From the project root
./start_services.sh
```

This starts 5 processes:

| # | Service | Port | Description |
|---|---------|------|-------------|
| 1 | PostgreSQL + Redis | 5433, 6379 | Database & cache (Docker) |
| 2 | Backend API | 8000 | Main FastAPI application |
| 3 | Unified Gateway | 8001 | REST proxy, webhooks, WebSocket |
| 4 | Arq Worker | — | Background task processor |
| 5 | Frontend | 3000 | React application (Vite) |

## 6. Verify

```bash
# Check all ports are listening
lsof -i :8000 -i :8001 -i :3000 -i :5433 -i :6379 | grep LISTEN

# Check Docker containers
docker ps

# Check Python processes
ps aux | grep -E "(uvicorn|arq)" | grep -v grep
```

Access the application:

| URL | Service |
|-----|---------|
| http://localhost:3000 | Frontend |
| http://localhost:8000/docs | Backend API (Swagger) |
| http://localhost:8001/docs | Gateway API (Swagger) |

---

## Stop All Services

```bash
./stop_services.sh
```

---

## Apache Reverse Proxy (Production)

For production with SSL and subdomain routing:

```bash
# After DNS A records point to your VM
chmod +x deploy/apache/setup_apache.sh
sudo ./deploy/apache/setup_apache.sh
```

This sets up Apache, configures 5 subdomains, obtains Let's Encrypt SSL, and applies security hardening. See [deploy/apache/](deploy/apache/) for details.

---

## AI Model Setup

After the platform is running, configure AI providers:

1. Read the [AI Model Credentials Guide](AI_MODEL_CREDENTIALS_GUIDE.md)
2. Set up GCP Vertex AI (Gemini + Claude) and/or Azure OpenAI (GPT-4o)
3. Register credentials in the Integration Registry via the API
4. Configure task defaults for model routing

---

## Viewing Logs

All service logs are in the `logs/` directory:

```bash
tail -f logs/backend_api.log       # Backend API
tail -f logs/unified_gateway.log   # Unified Gateway
tail -f logs/arq_worker.log        # Background worker
tail -f logs/frontend.log          # Frontend dev server
```

---

## Manual Service Management

If you need to start services individually:

```bash
cd backend

# Backend API
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# Unified Gateway (separate terminal)
.venv/bin/python -m uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 --reload

# Arq Worker (separate terminal)
.venv/bin/python -m arq src.ai.worker.WorkerSettings
```

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

---

## Troubleshooting

### Port already in use

```bash
lsof -i :PORT_NUMBER          # Find the process
kill -9 PID                    # Kill it
```

### Database connection failed

```bash
docker ps                                              # Is PostgreSQL running?
docker exec -it hirebuddha-db psql -U postgres -d hirebuddha   # Test connection
docker compose up -d db                                # Restart if needed
```

### Redis connection failed

```bash
docker exec -it hirebuddha-redis redis-cli ping        # Should return PONG
```

### Backend won't start

```bash
ls -la backend/.venv/          # Does the venv exist?
cd backend && poetry install   # Reinstall dependencies
cat logs/backend_api.log       # Check error logs
```

### Frontend build errors

```bash
cd frontend
rm -rf node_modules
npm install --legacy-peer-deps
npm run dev
```
