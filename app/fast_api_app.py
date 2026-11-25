"""FastAPI entry module: loads .env, re-exports create_app, and builds the served app."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.app_factory import create_app
from app.config import REPO_ROOT

__all__ = ["app", "create_app"]

load_dotenv(REPO_ROOT / ".env")

app: FastAPI = create_app()


if __name__ == "__main__":
    from app.server import main

    main()
