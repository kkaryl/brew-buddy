# Stage 1: Build the React / Vite / TypeScript frontend
FROM node:22-bookworm-slim AS web-builder
WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# Stage 2: Python 3.12 + FastAPI + Google ADK runtime serving API & static SPA
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

WORKDIR /code

# Install exact locked production versions from uv.lock via public PyPI so builds succeed
# identically in Cloud Build and GitHub Actions without corporate proxy URLs.
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY agents-cli-manifest.yaml ./

RUN uv venv /code/.venv \
    && uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.prod.txt \
    && uv pip install --python /code/.venv/bin/python --index-url https://pypi.org/simple --no-cache -r /tmp/requirements.prod.txt \
    && uv pip install --python /code/.venv/bin/python --index-url https://pypi.org/simple --no-deps --no-cache . \
    && rm -f /tmp/requirements.prod.txt \
    && useradd --create-home --uid 10001 brew \
    && chown -R brew:brew /code

COPY --chown=brew:brew --from=web-builder /web/dist ./web/dist

ARG AGENT_VERSION=0.1.0
ENV AGENT_VERSION=${AGENT_VERSION} \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080 \
    WEB_DIST_DIR=/code/web/dist \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT \
    ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false \
    BREW_TELEMETRY_CAPTURE_CONTENT=false \
    BREW_TELEMETRY_UPLOAD_COMPLETIONS=false \
    PATH="/code/.venv/bin:${PATH}"

USER brew
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.environ.get('PORT', '8080'); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=4).read()"]

# app.server reads the Cloud Run PORT environment variable directly
CMD ["python", "-m", "app.server"]
