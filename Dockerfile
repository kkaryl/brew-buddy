# syntax=docker/dockerfile:1

# Stage 1: Build the React / Vite / TypeScript frontend
FROM node:22-bookworm-slim AS web-builder
WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# Stage 2: Python 3.12 + FastAPI + Google ADK runtime serving API & static SPA
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

WORKDIR /code

# Install production Python dependencies first for optimal layer caching
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY agents-cli-manifest.yaml ./

RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 brew \
    && chown -R brew:brew /code

COPY --chown=brew:brew --from=web-builder /web/dist ./web/dist

ARG AGENT_VERSION=0.1.0
ENV AGENT_VERSION=${AGENT_VERSION} \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080 \
    WEB_DIST_DIR=/code/web/dist \
    PATH="/code/.venv/bin:${PATH}"

USER brew
EXPOSE 8080

# app.server reads the Cloud Run PORT environment variable directly
CMD ["python", "-m", "app.server"]
