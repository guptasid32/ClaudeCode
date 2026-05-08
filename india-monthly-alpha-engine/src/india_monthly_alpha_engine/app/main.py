from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import __version__
from ..db.session import get_session, healthcheck_duckdb, healthcheck_sqlite
from ..ingestion.manual_upload import ingest_all
from .config import get_settings
from .logging_config import configure_logging, get_logger


@click.group()
@click.version_option(__version__, prog_name="imae")
def cli() -> None:
    """india-monthly-alpha-engine command-line interface."""


@cli.command()
def healthcheck() -> None:
    """Verify config loads and both databases connect.

    Phase 1 acceptance gate: prints OK and exits 0 on success.
    """
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("healthcheck")

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    sqlite_ok = healthcheck_sqlite(settings.sqlite_url)
    duckdb_ok = healthcheck_duckdb(settings.duckdb_path)

    log.info(
        "healthcheck.result",
        sqlite=sqlite_ok,
        duckdb=duckdb_ok,
        sqlite_path=str(settings.sqlite_path),
        duckdb_path=str(settings.duckdb_path),
        version=__version__,
    )

    if sqlite_ok and duckdb_ok:
        click.echo("OK")
        sys.exit(0)
    click.echo("FAIL", err=True)
    sys.exit(1)


@cli.command()
@click.option(
    "--raw-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override data/raw root. Defaults to <DATA_DIR>/raw.",
)
def ingest(raw_dir: Path | None) -> None:
    """Phase 2 manual ingestion. Walks data/raw/ and loads every CSV."""
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("ingest")

    target = raw_dir if raw_dir is not None else settings.data_dir / "raw"
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        click.echo(f"raw dir not found: {target}", err=True)
        sys.exit(2)

    with get_session(settings.sqlite_url) as session:
        results = ingest_all(session, target)

    for kind, stats in results.items():
        log.info(
            "ingest.result",
            kind=kind,
            rows_added=stats.rows_added,
            rows_updated=stats.rows_updated,
            rows_skipped=stats.rows_skipped,
        )
    click.echo("OK")


if __name__ == "__main__":
    cli()
