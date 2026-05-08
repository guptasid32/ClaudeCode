"""ORM models for the SQLite OLTP store.

Phase 1 contains only StrategyVersion as a smoke-test model. Schema for
portfolio state, predictions, lots, deployment plans, etc. arrives in
Phase 2 onwards. Raw history models (prices, financials, filings) live
in models_raw.py and are imported only by the pit/ package.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_name", "version", name="uq_strategy_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    weights_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    thresholds_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cost_model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scoring_methodology_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backtest_validity_methodology_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    point_in_time_methodology_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    benchmark_methodology_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    architecture_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
