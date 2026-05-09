# Running on real Indian equity data — local-machine quickstart

This document is for someone moving the project from the sandbox to a real local machine with internet access. Everything you need to run the system on real data lives in the repo. This file walks the entire workflow end to end.

## 0. Prerequisites

- Python 3.11+ (3.11 or 3.12 recommended).
- About 1 GB of disk for several years of price data on Nifty 500 + delisted names.
- A modern machine — anything in the last 5 years is fine. SSD strongly preferred for the SQLite + DuckDB writes.
- Network access to NSE, BSE, and the SEBI / agency sites mentioned in `data_sources.md`.
- `git`, `make`, and a recent `pip`.

## 1. Clone and install

```bash
git clone <your fork URL>
cd <repo>/india-monthly-alpha-engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Sanity checks

```bash
make healthcheck   # confirms SQLite + DuckDB connect, prints OK
make test          # runs the entire test suite; should be all green
make lint          # ruff checks
make import-lint   # architecture rule enforcement
```

If any of those fail, fix them before proceeding. The test suite is the safety net — anything passing it has the engineering invariants we need.

## 3. Initialise the database

```bash
make db-init       # alembic upgrade head; creates SQLite tables
```

The DuckDB analytics database is created lazily on first use; nothing to do explicitly.

## 4. Populate `data/raw/`

The ingestion loaders read CSVs from `data/raw/<type>/`. The expected format for each type is documented as the top docstring of the corresponding loader module under `src/india_monthly_alpha_engine/ingestion/`. Brief recap:

```
data/raw/
  companies/companies.csv
  prices/<any>.csv                  # one or many files
  financials/<any>.csv
  corporate_actions/<any>.csv
  index_constituents/nifty500.csv
  filings/<any>.csv
  delisted_companies/seed_list.csv
  portfolio/holdings.csv            # your current portfolio
  portfolio/lots.csv                # your FIFO tax lots
```

See `data_sources.md` §4 for the canonical primary source for each type. The most useful are:

- **Daily prices**: NSE bhavcopy daily zip (`https://archives.nseindia.com/products/content/sec_bhavdata_full.csv`). One file per trading day; cat them into a single CSV with the columns the loader expects (`symbol, trade_date, open, high, low, close, volume, delivery_volume, delivery_percentage, turnover`).
- **Index constituents**: NSE Indices monthly methodology page; export as CSV with columns `index_name, symbol, effective_from, effective_to, weight`. Effective_to is null for currently-active rows.
- **Quarterly financials**: NSE / BSE corporate filings; the practical shortcut for a v1 run is exporting a Screener (or similar tier-4 source) export and loading it via the financial loader. For audited primary-source loading you'll want an XBRL parser; that is not in v1 scope.
- **Corporate actions**: BSE / NSE corp action announcements; columns `symbol, ex_date, announcement_date, action_type, ratio_numerator, ratio_denominator, cash_amount`. Supported action_types: `split, bonus, rights, dividend, buyback, merger, demerger, delisting`.
- **Delisted seeds**: `data/raw/delisted_companies/seed_list.csv` with `symbol, company_name, isin, exchange, sector, industry, market_cap_category, listing_date, delisting_date, event_type, recovery_rate, source_url, notes`. Names to seed are listed in `data_sources.md` §6.
- **Benchmark prices**: load Nifty 500 TRI daily closes into the `benchmark_prices` table. The simplest path is a small one-off Python script that reads a CSV and inserts rows; the loader for benchmark prices is intentionally not part of the manual ingestion CLI in v1.

You also need a benchmark-prices loader before the orchestrator can compute the market regime. A minimal version:

```python
# tools/load_benchmark.py
from datetime import date
import csv
from pathlib import Path
from sqlalchemy.orm import Session
from india_monthly_alpha_engine.app.config import get_settings
from india_monthly_alpha_engine.db.session import get_session
from india_monthly_alpha_engine.db.models import BenchmarkPrice

CSV = Path("data/raw/benchmarks/nifty500_tri.csv")  # columns: trade_date,close,tri_close

settings = get_settings()
with get_session(settings.sqlite_url) as session:
    for row in csv.DictReader(CSV.open()):
        session.add(BenchmarkPrice(
            index_name="NIFTY_500_TRI",
            trade_date=date.fromisoformat(row["trade_date"]),
            close=float(row["close"]),
            tri_close=float(row.get("tri_close") or row["close"]),
        ))
```

Run it once to seed the benchmark series.

## 5. Run the manual ingestion

```bash
make ingest        # reads data/raw/*.csv and populates SQLite
```

This may take a few minutes the first time. Each ingestion run logs the source registry entries it created. Re-running is safe; idempotency is built in (existing rows are detected and skipped or updated rather than duplicated).

## 6. Run the live monthly cycle

```bash
make monthly                                        # uses today's date
imae monthly --as-of 2024-06-28 --capital 25000    # explicit date
```

The output is a `MonthlyDeploymentPlan` row plus per-action rows in `monthly_buy_actions`, plus per-candidate rows in `historical_predictions`. You can read them via SQL or via the (placeholder) Streamlit dashboard.

A monthly cycle on Nifty 500 + 50 delisted names will take a few minutes the first time because the cohort builder walks ten years of history per candidate. After the first run, you can pre-compute and cache cohort statistics if you want to speed up subsequent runs.

## 7. Diverse stress-testing across history

The most useful thing to do once real data is in is to run the orchestrator on many randomly-selected historical (date, subset) pairs to make sure no input combination breaks the system. There's a script for it:

```bash
python -m india_monthly_alpha_engine.tools.stress_test \
    --start 2014-01-01 --end 2022-12-31 \
    --runs 50 --universe-size 30 --seed 42
```

This picks 50 random as-of dates within the train+validation window, samples 30 companies from the universe at each date, and runs the orchestrator on each. It is **not** a strategy backtest; it's a soak test for the engineering. It surfaces:

- Crashes on edge-case dates (e.g., right after a corporate action).
- PIT-availability inconsistencies (a feature engine asking for data that isn't there).
- Unusual values (negative scores, NaN, etc.).
- Performance regressions.

Running it across many random points is the right "diverse loop" — it explores the input space without tuning the strategy. **What this does NOT do, on purpose:**

- It does not promote a strategy variant. Promotion still goes through the train / validation / locked-holdout discipline in `backtest_validity_methodology.md` §7.
- It does not modify weights or thresholds based on results. Those are version-controlled in the strategy_versions table; changing them creates a new strategy version, which then has to face the validation gate.
- It does not run on the locked holdout window (2023-01-01 to 2024-12-31). The stress-test script will refuse to.

## 8. Running a real backtest

Once data is in:

```bash
python -m india_monthly_alpha_engine.tools.run_backtest \
    --strategy hybrid_balanced \
    --start 2012-01-01 --end 2018-12-31     # train window
```

(You'll need to write `tools/run_backtest.py` — it composes the orchestrator with the monthly_sip_backtester. The pieces are all in place; the wiring is one file.)

The backtest reports gross / net-of-cost / net-of-cost-and-tax CAGR, max drawdown, longest underperformance, style-adjusted alpha, and the survivorship gap. It refuses to report alpha if any validity test is failing (PIT property, decile monotonicity, cost-drag tolerance, replay determinism).

## 9. Strategy promotion

Per `backtest_validity_methodology.md` §7:

1. Develop and explore weights / thresholds against the **train** window (2012–2018).
2. Test alternative strategies against the **validation** window (2019–2022).
3. Pre-register the SINGLE best strategy by net CAGR excess.
4. Run it ONCE on the **holdout** window (2023–2024).
5. If it passes all gates (CAGR, bootstrap CI, style alpha, drawdown, underperf duration), promote it.
6. If it fails, the holdout is burned. The current champion stays. Wait for new data before another holdout cycle.

Do not test multiple strategies on the holdout. Do not retry. Do not "tune until it passes." The single-shot rule exists for a reason.

## 10. Running the dashboard

```bash
streamlit run -m india_monthly_alpha_engine.ui.streamlit_app
```

The dashboard is a placeholder in v1. It reads the latest deployment plan and the historical predictions table. Full dashboard pages (deployment plan viewer, portfolio review, backtest summary) are the last Phase 18 task.

## 11. What's still TODO when you move to real data

- A real benchmark-prices loader CLI (currently a one-off script).
- The `tools/run_backtest.py` and `tools/stress_test.py` referenced above.
- Curating the delisted-companies seed list with confirmed dates and last-traded symbols. The names are in `data_sources.md` §6.
- Sector tailwind score (currently a placeholder constant).
- Style-factor returns (SMB, HML, MOM) — defined in `benchmark_methodology.md`, not yet implemented.
- Replacement actions in the deployment engine (the spec is in `scoring_methodology.md` §7; the engine currently only emits `new_buy` / `buy_index` / `hold_cash`).
- Monthly portfolio review report linking holdings to thesis_status from structured signals (per `scoring_methodology.md` §6).
- Streamlit dashboard pages.

Each of those is a clear, scoped piece of work. None of them require any change to the methodology — only implementation against the existing specs.

## 12. The honest expectations

When you run the first real backtest, the most likely outcome is "the strategy modestly beats the index gross, modestly underperforms net of cost and tax." That outcome would be perfectly consistent with the academic literature. The system is designed so that when that happens, the answer is "buy the index" — which the deployment engine already defaults to.

The system's value isn't that it always beats the index. The system's value is that it tells you *honestly* whether and when it can. Most of the value is in the months it correctly says "no" to a tempting active idea and routes the ₹25,000 to the index without remorse.

Good luck on your local box. Pull the branch, populate `data/raw/`, run `make ingest`, run `make monthly`. If anything breaks, the test suite plus the import-linter rules plus the methodology docs together pin down what the right behaviour is.
