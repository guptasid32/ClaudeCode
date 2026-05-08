from __future__ import annotations

import sys

import click

from .. import __version__
from ..db.session import healthcheck_duckdb, healthcheck_sqlite
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


if __name__ == "__main__":
    cli()
