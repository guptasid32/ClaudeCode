# The autonomous adversarial loop, explained

This document is the spec for `bootstrap_local.sh` plus
`tools/adversarial_loop.py`. Read it once before running the loop on
your local machine. It is short by design.

## What the loop does

It picks **diverse historical scenarios** — different time periods,
different market regimes, different sector concentrations, different
liquidity profiles, different universe sizes, with and without
delisted-company stress — and runs the orchestrator on each. For each
run it checks engineering invariants (no crashes, scores in valid
ranges, deterministic feature-snapshot hashes, capital split sums to
the correct total, etc.). Failures are logged as bugs to fix in code.
Successful runs increment coverage of that scenario cell. Cells that
have caused failures get a probability boost so the loop keeps probing
near known-fragile inputs — that is the "GAN-like" hardness signal,
but for finding bugs, not for tuning strategy parameters.

Every N runs (default 25), the data fetcher is invoked to pull
additional real data from yfinance: extends history of existing
symbols by a year, or adds a few new symbols. So the testbed evolves;
no two iterations see the same data twice.

The loop exits cleanly when the engine handles **30 consecutive
scenarios without invariant failures**, with at least **60% scenario
cell coverage** (configurable). At that point you have engineering
confidence that the orchestrator is robust across the input space.

## What the loop does NOT do

It does not change strategy weights or thresholds. It does not search
for parameter combinations that beat the benchmark. It does not run on
the locked holdout window (2023-01-01 to 2024-12-31). Strategy
promotion remains a single-shot decision per
`backtest_validity_methodology.md` section 7. This separation is the
discipline that prevents overfitting on real money.

## Why "GAN-like" works for engineering, not for strategy

A real GAN updates weights from a differentiable loss. We don't have
that. What we have are *engineering invariants* — things that must be
true for any input to the system, like "the index amount and active
amount sum to the monthly capital." Diverse adversarial inputs find
the cases where invariants break; the developer fixes the bug; the
loop re-runs and either passes (no more bugs) or finds a new one.

If you instead used the loop to search for weights that maximise
backtest CAGR on whatever historical window you pulled, you'd be
overfitting. The system would look great in tests and fail in the
real world. Reading `PROCESS_AND_RATIONALE.md` section 14 once will
give you the full intuition for why.

## What's running on your machine

Three things, in order:

1. **`bootstrap_local.sh`**: one-time setup. Creates a venv, installs
   the package and its data extras (yfinance, pandas, requests),
   verifies lint and the unit-test suite pass, runs alembic to
   initialise SQLite, calls the bulk data fetcher to pull ~10 years
   of daily prices, dividends, splits, quarterly financials, and the
   Nifty 500 proxy benchmark for ~30 starter symbols, and seeds the
   curated delisted list.

2. **`tools/data_fetcher.py`**: the network layer. Two modes —
   `bulk` (initial download) and `refresh` (evolve the testbed by
   adding new symbols or extending history of existing ones).
   Everything goes through the source registry so the audit trail
   is preserved.

3. **`tools/adversarial_loop.py`**: the loop. Scenario diversity
   is managed by `tools/diversity.py` which maintains an in-memory
   coverage grid keyed on (period, regime_proxy, sector_concentration,
   liquidity_profile, universe_size, survivorship_stress). Cell
   selection is inverse-frequency-weighted with a failure-bonus
   intensification term. Each cell pick produces one (as_of_date,
   stock_subset) sample; the orchestrator runs against it; invariants
   are checked; coverage and failure counters update.

## Configuration knobs (defaults are sensible; only change if you
have a reason)

- `MAX_RUNS=300` — how many scenarios to try before giving up.
- `CONVERGE_STREAK=30` — consecutive failure-free runs to declare
  the engine robust.
- `CONVERGE_COVERAGE=0.5` — minimum fraction of scenario cells that
  must be exercised before convergence is allowed.
- `REFRESH_EVERY=25` — pull fresh data every N runs.
- `COHORT_STEP_DAYS=365` — observation cadence inside the cohort
  builder. Lower is more thorough but much slower; 365 means one
  observation per year.
- `START_DATE=2014-01-01`, `END_DATE=today` — bulk download window.
- `SEED` — by default random per run (uses `date +%s`); set to a
  fixed integer for reproducibility.

All are overridable via environment variables before invoking the
script:

```bash
SEED=42 MAX_RUNS=1000 CONVERGE_STREAK=100 ./bootstrap_local.sh
```

## What you do with failures

When the loop reports invariant failures (you'll see them on stderr
and they'll be saved to `logs/adversarial_failures.log` with the
full traceback plus the scenario cell that triggered them):

1. Read the traceback. It tells you which check failed and where.
2. Look at the scenario cell. The cell tells you what made the
   input adversarial (e.g., "concentrated sector + with_illiquid +
   2018_2020 + survivorship_stress" probably means an illiquid
   delisted name during the IL&FS crisis).
3. Fix the engine bug. Add a regression test under `tests/` so the
   bug never recurs.
4. Re-run the loop. The intensification weighting will keep probing
   the same kind of cell until it stops failing.
5. Repeat until the loop converges.

This is the same discipline as test-driven development: failures are
the input, fixes are the output, the test suite grows monotonically.

## When to stop the loop

When it converges (`loop.converged` log line). Or after a sensible
soak — if 1,000 runs and 80% coverage produce zero failures, you're
in good shape. Or never — you can leave it running as a monitor and
have it log to a file you check daily.

## After the loop converges

Run a real backtest on the train window:

```bash
python -m india_monthly_alpha_engine.tools.run_backtest \
    --start 2014-01-01 --end 2018-12-31
```

If the strategy beats Nifty 500 TRI net of cost and tax, with a
positive bootstrap lower CI on monthly excess return, repeat on
validation:

```bash
python -m india_monthly_alpha_engine.tools.run_backtest \
    --start 2019-01-01 --end 2022-12-31
```

If validation passes the gates in `backtest_validity_methodology.md`
section 7.2, **pre-register the single best strategy** (record it in
`strategy_versions` with its weights and thresholds frozen) and then
test it ONCE on the holdout:

```bash
python -m india_monthly_alpha_engine.tools.run_backtest \
    --start 2023-01-01 --end 2024-12-31 \
    --allow-holdout \
    --pre-registered-strategy hybrid_balanced@v1
```

If it passes, the strategy is promoted and you have a system worth
acting on. If it fails, the holdout is **burned**. The current
champion stays. You wait for new data before another holdout cycle.

That single-shot rule is the reason you're allowed to trust the
result if it passes. Don't break it.

## Honest limits

- yfinance coverage of Indian quarterly financials is partial. Many
  fields will be null. The Evidence Quality rubric handles this
  correctly (penalises low evidence rather than crashing), but real
  alpha measurement benefits from richer data than yfinance provides.
- The Nifty 500 series fetched as `^CRSLDX` is PRI, not TRI. For an
  honest alpha number, replace it with a real TRI series via
  `tools/load_benchmark.py`.
- The default delisted seed list is six names. Per
  `data_sources.md` section 6, real strategy promotion needs ≥ 50.
  The engine and loop are happy to run with six; the survivorship
  test will not certify a strategy until the list is expanded.
- The starter symbol list is 30 large-cap names. Expand to a fuller
  Nifty 500 list with `--symbols-file path/to/your/list.txt`.

These are real-world data acquisition tasks, not engineering
problems. The system is engineered to consume better data when you
get it.

## One-line summary

`./bootstrap_local.sh` sets up the environment, pulls real data, runs
the diverse adversarial loop, evolves the testbed, fixes-or-flags the
hard cases, and converges when the engine is robust — without ever
touching strategy parameters or the locked holdout.
