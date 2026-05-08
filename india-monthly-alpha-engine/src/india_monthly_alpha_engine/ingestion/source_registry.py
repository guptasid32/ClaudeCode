"""Source registry helpers.

Every ingestion run creates a Source row that records the source URL,
type, parser version, document hash, and counts. Per data_sources.md
section 5 the registry is append-only — re-ingestion of the same logical
document with different bytes yields a new Source row.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.models import Source


def hash_file(path: Path) -> str:
    """SHA-256 of file bytes. Used as document_hash in the source registry."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def register_source(
    session: Session,
    *,
    source_type: str,
    source_url: str | None,
    document_hash: str | None,
    source_tier: int = 1,
    parser_version: str = "v0",
    notes: str | None = None,
) -> Source:
    """Create a Source row and flush it so the id is available."""
    src = Source(
        source_url=source_url,
        source_type=source_type,
        source_tier=source_tier,
        parser_version=parser_version,
        document_hash=document_hash,
        notes=notes,
    )
    session.add(src)
    session.flush()
    return src


def finalize_source(
    session: Session,
    source: Source,
    *,
    files_loaded: int = 1,
    rows_added: int = 0,
    rows_updated: int = 0,
) -> None:
    source.files_loaded = files_loaded
    source.rows_added = rows_added
    source.rows_updated = rows_updated
    session.flush()
