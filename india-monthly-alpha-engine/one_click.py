#!/usr/bin/env python3
"""One-click installer + autonomous loop launcher.

Single file. Stdlib only. Cross-platform (Linux / macOS / Windows).

What it does, in order:
  1. Verify Python 3.11+.
  2. Verify git is installed.
  3. Clone the repo to --target-dir (or pull if already present).
  4. Create a venv inside the project.
  5. Install the package + dev + data extras (yfinance, pandas).
  6. Sanity-check lint and run the fast unit-test suite.
  7. Initialise the SQLite database (alembic upgrade head).
  8. Download real Indian equity historical data via yfinance.
  9. Start the adversarial diversity loop.

You can run this from anywhere. It needs network access for the git
clone and the data fetch.

Usage:

  python3 one_click.py
  python3 one_click.py --repo-url https://github.com/<you>/<fork>.git
  python3 one_click.py --target-dir ~/imae --branch main
  python3 one_click.py --skip-loop   # set everything up but don't start the loop

All env vars supported by bootstrap_local.sh also work here
(MAX_RUNS, CONVERGE_STREAK, REFRESH_EVERY, COHORT_STEP_DAYS,
START_DATE, END_DATE, SEED).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_URL = os.environ.get(
    "IMAE_REPO_URL",
    "https://github.com/guptasid32/ClaudeCode.git",
)
DEFAULT_BRANCH = os.environ.get("IMAE_BRANCH", "claude/analyze-alpha-engine-plan-Vtk8u")
DEFAULT_TARGET = Path.home() / "india-monthly-alpha-engine"


def _print_step(n: int, text: str) -> None:
    print(f"\n>>> {n}. {text}", flush=True)


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, env: dict | None = None) -> int:
    """Run a subprocess and stream its output. Raise on failure when check=True."""
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    rc = subprocess.run(cmd, cwd=cwd, env=env or os.environ.copy()).returncode
    if check and rc != 0:
        sys.exit(f"\nCommand failed (exit {rc}): {' '.join(str(c) for c in cmd)}")
    return rc


def _check_python() -> None:
    # Note: this script targets Python 3.11+; the comparison stays explicit
    # because users may run it under any Python version via `python3 one_click.py`.
    if sys.version_info < (3, 11):  # noqa: UP036
        sys.exit(f"Need Python 3.11+; this is {sys.version.split()[0]}")
    print(f"python {sys.version.split()[0]} OK")


def _check_git() -> None:
    if shutil.which("git") is None:
        sys.exit("git not found in PATH. Install git and re-run.")
    print(f"git OK ({shutil.which('git')})")


def _clone_or_pull(repo_url: str, branch: str, target: Path) -> Path:
    if target.exists() and (target / ".git").is_dir():
        print(f"existing repo at {target}; fetching latest")
        _run(["git", "fetch", "origin"], cwd=target)
        _run(["git", "checkout", branch], cwd=target)
        _run(["git", "pull", "--ff-only", "origin", branch], cwd=target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and any(target.iterdir()):
            sys.exit(f"target {target} exists and is not empty; pick a different --target-dir")
        _run(["git", "clone", "-b", branch, repo_url, str(target)])

    sub = target / "india-monthly-alpha-engine"
    if not sub.exists():
        sys.exit(f"expected sub-project at {sub} not found; wrong repo or branch?")
    return sub


def _venv_python(project_dir: Path) -> Path:
    venv = project_dir / ".venv"
    if not venv.exists():
        _run([sys.executable, "-m", "venv", str(venv)])
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _pip(venv_py: Path, args: list[str]) -> None:
    _run([str(venv_py), "-m", "pip", *args])


def _venv_module(venv_py: Path, mod: str, args: list[str], *, cwd: Path) -> int:
    return _run([str(venv_py), "-m", mod, *args], cwd=cwd, check=False)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    p.add_argument("--branch", default=DEFAULT_BRANCH)
    p.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET)
    p.add_argument("--skip-loop", action="store_true", help="install + data fetch only; don't start the adversarial loop")
    p.add_argument("--skip-data-fetch", action="store_true", help="don't download yfinance data; useful for re-runs")
    args = p.parse_args()

    print("=" * 70)
    print("india-monthly-alpha-engine: one-click installer")
    print("=" * 70)
    print(f"repo:   {args.repo_url}")
    print(f"branch: {args.branch}")
    print(f"target: {args.target_dir}")
    print()

    _print_step(1, "Checking Python...")
    _check_python()

    _print_step(2, "Checking git...")
    _check_git()

    _print_step(3, "Cloning / updating repo...")
    project_dir = _clone_or_pull(args.repo_url, args.branch, args.target_dir)
    print(f"project_dir = {project_dir}")

    _print_step(4, "Creating virtual environment...")
    vpy = _venv_python(project_dir)
    print(f"venv python = {vpy}")
    _pip(vpy, ["install", "--upgrade", "pip"])

    _print_step(5, "Installing package + dev + data extras (this can take a few minutes)...")
    _pip(vpy, ["install", "-e", f"{project_dir}[dev,data]"])

    _print_step(6, "Lint + fast unit tests...")
    _run([str(vpy), "-m", "ruff", "check", "src", "tests"], cwd=project_dir)
    _run(
        [str(vpy.parent / ("lint-imports.exe" if platform.system() == "Windows" else "lint-imports"))],
        cwd=project_dir,
    )
    skip_expr = (
        "not slow and not end_to_end and not replay_determinism and "
        "not pes_lower_when_universe_low_quality and not orchestrator_intersects_universe_with_index"
    )
    _run([str(vpy), "-m", "pytest", "-q", "-k", skip_expr], cwd=project_dir)

    _print_step(7, "Initialising database (alembic upgrade head)...")
    _run([str(vpy), "-m", "alembic", "upgrade", "head"], cwd=project_dir)

    if not args.skip_data_fetch:
        _print_step(8, "Downloading real Indian equity data from yfinance (5-15 minutes)...")
        start = os.environ.get("START_DATE", "2014-01-01")
        end = os.environ.get("END_DATE", "")
        if not end:
            from datetime import date as _d
            end = _d.today().isoformat()
        _venv_module(
            vpy,
            "india_monthly_alpha_engine.tools.data_fetcher",
            ["bulk", "--start", start, "--end", end],
            cwd=project_dir,
        )
    else:
        _print_step(8, "Skipping data fetch (--skip-data-fetch)")

    if args.skip_loop:
        _print_step(9, "Skipping loop (--skip-loop). Setup complete.")
        print()
        print("Activate the venv and run any tool manually:")
        print(f"  source {project_dir / '.venv' / 'bin' / 'activate'}")
        print("  imae monthly --as-of $(date -u +%Y-%m-%d)")
        return 0

    _print_step(9, "Starting the adversarial diversity loop (Ctrl-C to stop)...")
    max_runs = os.environ.get("MAX_RUNS", "300")
    converge_streak = os.environ.get("CONVERGE_STREAK", "30")
    converge_coverage = os.environ.get("CONVERGE_COVERAGE", "0.5")
    refresh_every = os.environ.get("REFRESH_EVERY", "25")
    cohort_step = os.environ.get("COHORT_STEP_DAYS", "365")
    seed = os.environ.get("SEED")
    args_list = [
        "--max-runs", max_runs,
        "--converge-streak", converge_streak,
        "--converge-coverage", converge_coverage,
        "--refresh-every", refresh_every,
        "--cohort-step-days", cohort_step,
    ]
    if seed:
        args_list += ["--seed", seed]
    rc = _venv_module(
        vpy,
        "india_monthly_alpha_engine.tools.adversarial_loop",
        args_list,
        cwd=project_dir,
    )

    print()
    print("=" * 70)
    print("done.")
    print(f"project: {project_dir}")
    print(f"logs:    {project_dir / 'logs'}")
    print(f"db:      {project_dir / 'data' / 'state' / 'imae.sqlite'}")
    print()
    print("Next steps:")
    print(f"  source {project_dir / '.venv' / 'bin' / 'activate'}")
    print("  imae monthly --as-of $(date -u +%Y-%m-%d)")
    print(
        "  python -m india_monthly_alpha_engine.tools.run_backtest "
        "--start 2014-01-01 --end 2018-12-31"
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
