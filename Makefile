.PHONY: install dev lint typecheck test build check

install:
	uv sync
	npm --prefix web install

dev:
	uv run brew-dev

lint:
	uv run ruff check .
	uv run ruff format --check .
	npm --prefix web run lint

typecheck:
	uv run mypy app tests/unit tests/integration
	npm --prefix web run typecheck

test:
	uv run pytest
	npm --prefix web test

build:
	npm --prefix web run build

check: lint typecheck test build
