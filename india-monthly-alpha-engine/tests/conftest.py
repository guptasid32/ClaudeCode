from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from india_monthly_alpha_engine.db import Base
from india_monthly_alpha_engine.db.session import get_engine, get_session


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.sqlite'}"


@pytest.fixture
def initialized_db(sqlite_url: str) -> str:
    engine = get_engine(sqlite_url)
    Base.metadata.create_all(engine)
    return sqlite_url


@pytest.fixture
def session(initialized_db: str) -> Iterator[Session]:
    with get_session(initialized_db) as s:
        yield s
