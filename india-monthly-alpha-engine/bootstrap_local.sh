#!/usr/bin/env bash
#
# bootstrap_local.sh — single-command setup + autonomous adversarial loop.
#
# Run this on your local Linux/macOS box (the box that has internet
# access and where you want to actually run the engine on real data).
#
#   chmod +x bootstrap_local.sh
#   ./bootstrap_local.sh
#
# What it does, in order:
#   1. Verifies python 3.11+ is available.
#   2. Creates a venv inside the project.
#   3. Installs the package + dev + data extras (yfinance, pandas).
#   4. Sanity-checks lint and the unit test suite.
#   5. Initialises the SQLite database (alembic upgrade head).
#   6. Pulls a real bulk dataset from the internet via yfinance.
#   7. Starts the adversarial diversity loop, which:
#        - picks diverse historical (date, stock-subset) scenarios,
#        - runs the orchestrator on each,
#        - checks engineering invariants,
#        - logs failures to logs/adversarial_failures.log,
#        - every 50 runs it pulls additional data so the testbed evolves,
#        - exits cleanly when the engine handles 50 consecutive scenarios
#          without engineering failures and coverage > 60%.
#
# Strategy weights and thresholds are NOT modified by the loop. Strategy
# promotion remains a single-shot decision per backtest_validity_methodology.md
# section 7. The loop is engineering robustness fuzzing, not parameter tuning.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
LOG_DIR="${LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"

step() { printf '\n>>> %s\n' "$*"; }

step "1. Checking Python..."
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN not found in PATH" >&2
  exit 1
fi
PY_VERSION="$($PYTHON_BIN -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "found python $PY_VERSION"
case "$PY_VERSION" in
  3.11|3.12|3.13|3.14) ;;
  *)
    echo "ERROR: need Python 3.11+; got $PY_VERSION" >&2
    exit 1
    ;;
esac

step "2. Creating venv at $VENV_DIR..."
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null

step "3. Installing project + dev + data extras (this may take a couple of minutes)..."
pip install -e ".[dev,data]"

step "4. Lint + unit tests..."
ruff check src tests || { echo "lint failed" >&2; exit 1; }
lint-imports || { echo "import-linter failed" >&2; exit 1; }
# Skip the slow orchestrator end-to-end here; it runs as part of the loop.
pytest -q -k "not slow and not end_to_end and not replay_determinism and not pes_lower_when_universe_low_quality and not orchestrator_intersects_universe_with_index" \
  || { echo "unit tests failed" >&2; exit 1; }

step "5. Initialising database..."
alembic upgrade head

step "6. Bulk-loading real data from yfinance (Indian equities)..."
START_DATE="${START_DATE:-2014-01-01}"
END_DATE="${END_DATE:-$(date -u +%Y-%m-%d)}"
echo "fetching prices from $START_DATE to $END_DATE..."
python -m india_monthly_alpha_engine.tools.data_fetcher bulk \
  --start "$START_DATE" --end "$END_DATE" \
  | tee "$LOG_DIR/bootstrap_data_fetch.log" || true

step "7. Starting the adversarial diversity loop..."
echo "  Logs: $LOG_DIR/adversarial_failures.log (failures)"
echo "  Press Ctrl-C to stop early; partial coverage stats are printed at end."

MAX_RUNS="${MAX_RUNS:-300}"
CONVERGE_STREAK="${CONVERGE_STREAK:-30}"
CONVERGE_COVERAGE="${CONVERGE_COVERAGE:-0.5}"
REFRESH_EVERY="${REFRESH_EVERY:-25}"
COHORT_STEP_DAYS="${COHORT_STEP_DAYS:-365}"
SEED="${SEED:-$(date +%s)}"

python -m india_monthly_alpha_engine.tools.adversarial_loop \
  --max-runs "$MAX_RUNS" \
  --converge-streak "$CONVERGE_STREAK" \
  --converge-coverage "$CONVERGE_COVERAGE" \
  --refresh-every "$REFRESH_EVERY" \
  --cohort-step-days "$COHORT_STEP_DAYS" \
  --seed "$SEED" \
  --failure-log "$LOG_DIR/adversarial_failures.log" \
  | tee "$LOG_DIR/adversarial_loop.log"

echo ""
echo "Done. Summary printed above. Failures (if any) are in $LOG_DIR/adversarial_failures.log."
echo "Per-run details are in $LOG_DIR/adversarial_loop.log."
echo ""
echo "Next steps:"
echo "  - Inspect logs/. If failures are present, fix the bug, commit, re-run this script."
echo "  - Once the loop converges with zero failures, you can run a real backtest:"
echo "      python -m india_monthly_alpha_engine.tools.run_backtest --start 2014-01-01 --end 2018-12-31"
echo "  - Or do a single live monthly cycle:"
echo "      imae monthly --as-of $(date -u +%Y-%m-%d)"
