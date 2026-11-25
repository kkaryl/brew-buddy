# Brew — AI-Powered Coffee Chat Buddy

Brew helps professionals prepare for coffee chats, networking meetings, mentorship conversations, and customer discovery meetings while compounding relationship context across sessions through user-approved memory.

## Prerequisites

- **Python 3.12+** & **[uv](https://docs.astral.sh/uv/)**
- **Node.js 22 LTS** & **npm**
- **Google Cloud SDK (`gcloud`)** & **`google-agents-cli` (`agents-cli`)**

## Quickstart (Local Setup)

1. **Configure local environment variables** (safe defaults work out of the box for local health & tests):
   ```bash
   cp .env.example .env
   ```

2. **Install backend and frontend dependencies**:
   ```bash
   uv sync
   npm --prefix web install
   ```

3. **Start backend (FastAPI + ADK) and frontend (Vite + React) with a single command**:
   ```bash
   uv run brew-dev
   # or: make dev
   ```
   - Frontend dev server: `http://127.0.0.1:5173` (proxies `/api/*` to FastAPI)
   - Backend API & health check: `http://127.0.0.1:8000/api/health`
   - A2A agent card: `http://127.0.0.1:8000/a2a/app/.well-known/agent-card.json`

## Quality Gates

```bash
# Lint & format check (Backend + Frontend)
uv run ruff check .
uv run ruff format --check .
npm --prefix web run lint

# Static type checking (Strict mypy + Strict TypeScript)
uv run mypy app tests/unit tests/integration
npm --prefix web run typecheck

# Automated unit & integration tests (pytest + Vitest)
uv run pytest
npm --prefix web test

# Production frontend build
npm --prefix web run build
```

## Google Agents CLI Commands

```bash
# Inspect ADK project configuration
agents-cli info

# Interactive ADK web playground (requires GCP ADC or GEMINI_API_KEY)
agents-cli playground

# Offline behavioral evaluation suite (requires GCP ADC or GEMINI_API_KEY)
agents-cli eval run
```

## Container Build & Google Cloud Deployment

The multistage `Dockerfile` compiles `web/dist` and serves both the static SPA and FastAPI/ADK routes on `$PORT` (default `8080`):

```bash
docker build -t brew:local .
docker run --rm -p 8080:8080 -e PORT=8080 brew:local
```

For full minimal-footprint Cloud Run provisioning, custom IAP dual-account setup ([`iap_setup.sh`](iap_setup.sh)), Workload Identity Federation CI/CD, health/readiness probes, rollback, and cleanup instructions, see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and [`gcloud_setup.sh`](gcloud_setup.sh):

```bash
PROJECT_ID="your-gcp-project-id" GITHUB_REPO="your-org/brew" ENABLE_IAP="true" ./gcloud_setup.sh --dry-run
```
