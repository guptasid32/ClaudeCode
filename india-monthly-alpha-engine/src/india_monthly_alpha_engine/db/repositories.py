"""Repository functions over the SQLite OLTP store.

Phase 1 holds only a placeholder. Real repositories arrive alongside the
schemas they query (Phase 2 onwards).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import StrategyVersion


def insert_strategy_version(session: Session, sv: StrategyVersion) -> StrategyVersion:
    session.add(sv)
    session.flush()
    return sv
