.PHONY: install install-dev lint format typecheck test test-cov healthcheck db-init clean ingest monthly backtest ui import-lint

PY ?= python3

install:
	$(PY) -m pip install -e .

install-dev:
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check src tests

format:
	$(PY) -m ruff format src tests

typecheck:
	$(PY) -m mypy src

import-lint:
	lint-imports

test:
	$(PY) -m pytest

test-cov:
	$(PY) -m pytest --cov=india_monthly_alpha_engine --cov-report=term-missing

healthcheck:
	$(PY) -m india_monthly_alpha_engine.app.main healthcheck

db-init:
	$(PY) -m alembic upgrade head

# Phase-2+ targets — currently stubs that print and exit nonzero
ingest:
	@echo "ingest: not implemented (Phase 2)"; exit 1

monthly:
	@echo "monthly: not implemented (Phase 12)"; exit 1

backtest:
	@echo "backtest: not implemented (Phase 13)"; exit 1

ui:
	@echo "ui: not implemented (Phase 18)"; exit 1

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
