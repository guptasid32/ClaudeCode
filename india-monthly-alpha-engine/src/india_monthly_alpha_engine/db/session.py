from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine_cache: dict[str, Engine] = {}
_session_factory_cache: dict[str, sessionmaker[Session]] = {}


def get_engine(sqlite_url: str) -> Engine:
    if sqlite_url not in _engine_cache:
        _engine_cache[sqlite_url] = create_engine(
            sqlite_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return _engine_cache[sqlite_url]


def _get_session_factory(sqlite_url: str) -> sessionmaker[Session]:
    if sqlite_url not in _session_factory_cache:
        _session_factory_cache[sqlite_url] = sessionmaker(
            bind=get_engine(sqlite_url),
            autoflush=True,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory_cache[sqlite_url]


@contextmanager
def get_session(sqlite_url: str) -> Iterator[Session]:
    factory = _get_session_factory(sqlite_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def healthcheck_sqlite(sqlite_url: str) -> bool:
    try:
        with get_session(sqlite_url) as session:
            result = session.execute(text("SELECT 1"))
            return result.scalar_one() == 1
    except Exception:
        return False


def healthcheck_duckdb(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path)) as conn:
            row = conn.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1
    except Exception:
        return False
