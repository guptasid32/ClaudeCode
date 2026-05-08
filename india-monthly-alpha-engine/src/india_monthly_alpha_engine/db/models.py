"""ORM models for the SQLite OLTP store.

State, audit, and decision tables. Raw history tables (prices, financials,
filings, corporate actions, index constituents) live in models_raw.py and
are visible only to ingestion and to the PIT loader (per the import-linter
contract in pyproject.toml).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
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
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Source(Base):
    """Source registry — every ingested row references a Source row.

    Audit trail for the Evidence Quality rubric (scoring_methodology.md
    section 2.1) and for restated-filings handling (point_in_time_methodology.md
    section 2). One physical source document yields one Source row;
    re-ingestion of the same document with different bytes yields a new
    Source row and increments ingest_version on the run-level metadata.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ingestion_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    ingest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    files_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class SourceConflict(Base):
    """Logged value conflicts between two sources (data_sources.md section 10)."""

    __tablename__ = "source_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    period_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    source_a_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_b_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    source_b_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolution: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class PortfolioHolding(Base):
    """Current portfolio position (one row per active holding)."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    portfolio_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    thesis_status: Mapped[str] = mapped_column(String(16), nullable=False, default="intact")
    last_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PortfolioLot(Base):
    """FIFO tax-lot accounting for STCG/LTCG computation per cost_tax_methodology.md section 6."""

    __tablename__ = "portfolio_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    cost_per_share: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    pre_grandfather_fmv: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_action_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MonthlyDeploymentPlan(Base):
    """One row per monthly rebalance produced by the deployment engine."""

    __tablename__ = "monthly_deployment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rebalance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    monthly_capital: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark: Mapped[str] = mapped_column(String(32), nullable=False, default="NIFTY_500_TRI")
    portfolio_edge_score: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    index_allocation: Mapped[int] = mapped_column(Integer, nullable=False)
    active_allocation: Mapped[int] = mapped_column(Integer, nullable=False)
    cash_allocation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategy_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MonthlyBuyAction(Base):
    """One row per action emitted by the deployment engine for a plan."""

    __tablename__ = "monthly_buy_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    executable_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_trade_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    residual_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    residual_destination: Mapped[str] = mapped_column(String(16), nullable=False, default="index")
    monthly_buy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class HistoricalPrediction(Base):
    """Forward-looking decision log per scoring_methodology.md and v2 plan section 19.

    feature_snapshot_hash anchors replay determinism: a future replay
    with the same inputs must reproduce the same hash
    (point_in_time_methodology.md section 8).
    """

    __tablename__ = "historical_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    replay_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_buy_score: Mapped[int] = mapped_column(Integer, nullable=False)
    portfolio_edge_score: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    benchmark: Mapped[str] = mapped_column(String(32), nullable=False, default="NIFTY_500_TRI")
    feature_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sub_scores_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class HistoricalOutcome(Base):
    """Forward returns evaluated against a stored prediction (v2 plan section 19)."""

    __tablename__ = "historical_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    forward_return_3m: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_return_6m: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_return_12m: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_return_vs_benchmark: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_evaluation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class BenchmarkPrice(Base):
    """Daily index price (close + TRI close where available)."""

    __tablename__ = "benchmark_prices"
    __table_args__ = (
        UniqueConstraint("index_name", "trade_date", name="uq_benchmark_index_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    tri_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
