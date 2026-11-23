.PHONY: install dev lint typecheck test build check eval-deterministic eval-smoke eval

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

eval-deterministic:
	uv run python -m tests.eval.run_eval_suite --mode deterministic-adk --subset comprehensive --grade-via-cli

eval-smoke:
	uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset smoke

eval:
	uv run python -m tests.eval.run_eval_suite --mode live-agents-cli --subset comprehensive

check: lint typecheck test build
