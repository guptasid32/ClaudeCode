"""Phase 1 smoke tests.

Acceptance gates from v2 plan section 21 Phase 1:
- project installs (covered by `pip install -e .` succeeding)
- tests run (this file)
- DB connects (test_sqlite_connects, test_duckdb_connects)
- healthcheck passes (test_healthcheck_command)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.orm import Session

import india_monthly_alpha_engine
from india_monthly_alpha_engine.app.config import Settings, get_settings
from india_monthly_alpha_engine.app.main import cli
from india_monthly_alpha_engine.db.models import StrategyVersion
from india_monthly_alpha_engine.db.repositories import insert_strategy_version
from india_monthly_alpha_engine.db.session import healthcheck_duckdb, healthcheck_sqlite


def test_package_imports() -> None:
    assert india_monthly_alpha_engine.__version__ == "0.1.0"


@pytest.mark.parametrize(
    "module_name",
    [
        "india_monthly_alpha_engine.app",
        "india_monthly_alpha_engine.db",
        "india_monthly_alpha_engine.schemas",
        "india_monthly_alpha_engine.pit",
        "india_monthly_alpha_engine.features",
        "india_monthly_alpha_engine.engines",
        "india_monthly_alpha_engine.backtest",
        "india_monthly_alpha_engine.historical",
        "india_monthly_alpha_engine.reports",
        "india_monthly_alpha_engine.ingestion",
        "india_monthly_alpha_engine.ui",
        "india_monthly_alpha_engine.utils",
    ],
)
def test_subsystem_packages_import(module_name: str) -> None:
    __import__(module_name)


def test_settings_load_with_defaults() -> None:
    settings = Settings()
    assert settings.log_level == "INFO"
    assert settings.app_timezone == "Asia/Kolkata"


def test_get_settings_returns_settings() -> None:
    s = get_settings()
    assert isinstance(s, Settings)


def test_sqlite_connects(sqlite_url: str) -> None:
    assert healthcheck_sqlite(sqlite_url) is True


def test_duckdb_connects(tmp_path: Path) -> None:
    db_path = tmp_path / "x.duckdb"
    assert healthcheck_duckdb(db_path) is True


def test_session_executes_select_one(session: Session) -> None:
    assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_strategy_version_insert_and_read(session: Session) -> None:
    sv = StrategyVersion(
        strategy_name="hybrid_balanced",
        version="v0.1.0",
        weights_json={"cea": 0.20},
        thresholds_json={"replacement_stcg_pp": 4.0},
        scoring_methodology_version="v1",
        notes="phase 1 smoke",
    )
    insert_strategy_version(session, sv)
    fetched = session.query(StrategyVersion).filter_by(strategy_name="hybrid_balanced").one()
    assert fetched.version == "v0.1.0"
    assert fetched.weights_json == {"cea": 0.20}
    assert fetched.approved is False


def test_healthcheck_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "imae.sqlite"))
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "imae.duckdb"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    runner = CliRunner()
    result = runner.invoke(cli, ["healthcheck"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "OK" in result.output
