# HireBuddha Platform

> Enterprise multi-tenant AI orchestration platform with recursive multi-agent execution, real-time voice streaming, and a no-code entity builder.

---

## Architecture

```
                          Internet
                             │
                     ┌───────▼───────┐
                     │    Apache     │  SSL termination, reverse proxy
                     │  (ports 80/443) │
                     └──┬────┬────┬──┘
                        │    │    │
         ┌──────────────┘    │    └──────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌────────────────┐ ┌─────────────────┐
│ Unified Gateway │ │  Backend API   │ │    Frontend      │
│  (Port 8001)    │ │  (Port 8000)   │ │   (Port 3000)   │
│                 │ │                │ │                  │
│ • REST proxy    │ │ • Auth & RBAC  │ │ • React 18 + TS  │
│ • Webhooks      │ │ • AI Engine    │ │ • Entity Builder  │
│ • Audio WS      │ │ • Billing      │ │ • Voice Campaigns │
│ • Video WebRTC  │ │ • Tenant Mgmt  │ │ • Dashboard       │
│ • Voice routing │ │ • Config       │ │ • 3D Animations   │
└────────┬────────┘ └───────┬────────┘ └──────────────────┘
         │                  │
    ┌────┴──────────────────┴────┐
    │                            │
┌───▼────┐  ┌───────┐  ┌────────▼────────┐
│ Redis  │  │  Arq  │  │  PostgreSQL     │
│ (6379) │  │Worker │  │  + pgvector     │
│ Cache  │  │ (bg)  │  │  (Port 5433)    │
└────────┘  └───────┘  └─────────────────┘
```

### Subdomain Routing

| Subdomain | Target | Purpose |
|-----------|--------|---------|
| `app.hirebuddha.com` | localhost:3000 | Production frontend |
| `dev.hirebuddha.com` | localhost:3000 | Development frontend |
| `api.hirebuddha.com` | localhost:8001 | Unified AI Gateway |
| `gateway.hirebuddha.com` | localhost:8000 | Backend API |
| `streaming.hirebuddha.com` | localhost:8002 | Voice WebSocket streaming |

---

## Key Capabilities

### AI Engine
- **Hierarchical Entities** — Actions → Skills → Agents → Processes with recursive execution
- **20+ Built-in Tools** — Web search, file generation (PDF, PPTX, XLSX), email, calculator, and more
- **Multi-provider LLM** — Google Gemini, Anthropic Claude (via Vertex AI), Azure OpenAI (GPT-4o)
- **CORTEX Memory** — Cognitive tree memory system for persistent agent knowledge
- **RAG** — Document upload with vector search via pgvector + Gemini embeddings
- **HITL Guardrails** — Human-in-the-loop approval checkpoints at any entity level

### Voice & Messaging
- **Real-time voice** — Gemini Live Audio and GPT-4o Realtime for speech-to-speech
- **Telephony** — Twilio (international) and Tata Tele (India) integration
- **Campaign auto-dialer** — Bulk CSV upload, concurrent call throttling, real-time monitoring
- **WhatsApp** — Inbound/outbound messaging via Twilio and Tata Tele

### Platform
- **Multi-tenant RBAC** — App Admin → Partner → Tenant → User hierarchy
- **Billing engine** — SKU-based costing with platform fee, partner fee, discounts
- **Credit wallets** — Daily credits, PAYG top-ups (Razorpay), subscription credits
- **55+ Social integrations** — OAuth connections for social media platforms
- **Real-time observability** — SSE execution traces, cost tracking, token consumption

---

## Tech Stack

### Backend

| Category | Technology |
|----------|-----------|
| Framework | FastAPI (Python 3.11+) |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 15 + pgvector |
| Cache / Queue | Redis 7 + Arq |
| AI Providers | google-genai (Vertex AI), openai (Azure) |
| Auth | JWT (python-jose) + Argon2 hashing |
| Telephony | Twilio SDK, WebSockets |
| Payments | Razorpay |
| Observability | OpenTelemetry, Prometheus |

### Frontend

| Category | Technology |
|----------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite 5 |
| Routing | React Router v6 |
| UI | Liquid Glass design system, Framer Motion |
| Charts | Recharts |
| Entity Builder | ReactFlow |
| 3D Graphics | Three.js + React Three Fiber |
| Forms | React Hook Form + Zod validation |

### Infrastructure

| Component | Image / Version | Port |
|-----------|----------------|------|
| PostgreSQL | pgvector/pgvector:pg15 | 5433 |
| Redis | redis:7-alpine | 6379 |
| Reverse Proxy | Apache 2.4 + mod_ssl | 80/443 |
| SSL | Let's Encrypt (Certbot) | — |

---

## Project Structure

```
hb-proto-3/
├── backend/
│   ├── src/
│   │   ├── ai/            # Hierarchical entities, execution engine, LLM router
│   │   ├── auth/          # Authentication, RBAC, OAuth
│   │   ├── billing/       # Rates, ledger, credits, subscriptions
│   │   ├── common/        # Shared utilities, middleware, security
│   │   ├── config/        # Integration registry, task defaults
│   │   ├── gateway/       # Unified AI Gateway (REST, WebSocket, webhooks)
│   │   ├── voice/         # Voice streaming, campaign executor
│   │   ├── main.py        # Backend FastAPI app
│   │   └── database.py    # DB connection
│   ├── migrations/        # Alembic DB migrations
│   ├── db-scripts/        # seed_admin_user.py, clean_db.sql
│   ├── docker-compose.yml # PostgreSQL + Redis
│   ├── pyproject.toml     # All Python dependencies (Poetry)
│   └── Dockerfile         # Container build
├── frontend/
│   ├── src/
│   │   ├── components/    # Reusable UI components
│   │   ├── pages/         # Page views
│   │   ├── services/      # API client layer
│   │   ├── hooks/         # Custom React hooks
│   │   ├── router/        # Route definitions
│   │   ├── styles/        # CSS design system
│   │   └── types/         # TypeScript type definitions
│   └── package.json       # Node dependencies
├── deploy/
│   └── apache/            # VirtualHost configs, security hardening, setup script
├── docs/                  # Architecture & specification documents
├── setup_production_vm.sh # Full VM setup (Python, Node, Docker, deps)
├── start_services.sh      # Start all services
├── stop_services.sh       # Stop all services
└── AI_MODEL_CREDENTIALS_GUIDE.md  # AI provider setup guide
```

---

## Dependency Management

All Python dependencies are managed by **Poetry** via `backend/pyproject.toml`. There is no separate requirements file.

```bash
cd backend
poetry install          # Install all dependencies
poetry add <package>    # Add a new dependency
poetry update           # Update to latest compatible versions
```

---

## Environment Variables

Only core application settings use environment variables (stored in `backend/.env`). All third-party service credentials (AI providers, Twilio, Razorpay, etc.) are stored encrypted in the database via the **Integration Registry**.

See `backend/.env.example` for the complete list of core settings:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | JWT signing key |
| `CORS_ORIGINS` | Allowed CORS origins |
| `STREAMING_HOST` | Public hostname for WebSocket URLs |
| `INTERNAL_TOKEN` | Microservice auth token |

---

## API Documentation

With the backend running:

- **Swagger UI** — `https://gateway.hirebuddha.com/docs`
- **ReDoc** — `https://gateway.hirebuddha.com/redoc`

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/auth/register` | Register user |
| `POST /api/v1/auth/login` | Login → JWT |
| `GET /api/v1/ai/entities` | List AI entities |
| `POST /api/v1/ai/entities` | Create entity |
| `POST /api/v1/ai/execute` | Trigger execution |
| `GET /api/v1/ai/executions/{id}` | Execution trace |
| `GET /api/v1/ai/approvals/pending` | HITL approvals |
| `POST /api/config/integrations` | Register AI credentials |
| `POST /api/config/task-defaults` | Set model routing |
| `GET /api/v1/billing/usage` | Usage & costs |

---

## Guides

| Document | Description |
|----------|-------------|
| [QUICK_START.md](QUICK_START.md) | Getting started — setup, run, verify |
| [AI_MODEL_CREDENTIALS_GUIDE.md](AI_MODEL_CREDENTIALS_GUIDE.md) | GCP Vertex AI, Azure OpenAI, Integration Registry setup |
| [Product Documentation](HireBuddha-Product-Documentation-2026-03-04.md) | Full product feature documentation |
| [Requirements](Requirements.md) | Functional & business requirements |

---

## License

Proprietary — HireBuddha Platform

**Version:** 2.0.0  
**Last Updated:** March 2026
