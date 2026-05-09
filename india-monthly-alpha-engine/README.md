# india-monthly-alpha-engine

Personal-use capital deployment engine for ₹25,000 / month into Indian equities. Default investment is the benchmark index (Nifty 500 TRI). Direct stocks are recommended only when a point-in-time, cohort-tested, after-cost-after-tax expected-alpha case is strong enough to justify deviating from the index.

## One-click setup

You need Python 3.11+, git, and an internet connection. Then run **either** of these:

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/guptasid32/ClaudeCode/claude/analyze-alpha-engine-plan-Vtk8u/india-monthly-alpha-engine/one_click.py | python3
```

**Windows (PowerShell):**

```powershell
iwr https://raw.githubusercontent.com/guptasid32/ClaudeCode/claude/analyze-alpha-engine-plan-Vtk8u/india-monthly-alpha-engine/one_click.py -UseBasicParsing | python -
```

**Already cloned the repo:**

```bash
python3 one_click.py
```

That single command does everything — clones the repo to `~/india-monthly-alpha-engine`, creates a venv, installs all dependencies, runs lint and unit tests, initialises the database, downloads ~10 years of real Indian equity data via yfinance, and starts the autonomous adversarial diversity loop. Knobs (`MAX_RUNS`, `START_DATE`, `END_DATE`, `SEED`, etc.) are env-var overridable.

If you want setup only without the loop:

```bash
python3 one_click.py --skip-loop
```

After it finishes, activate the venv and use the CLI:

```bash
source ~/india-monthly-alpha-engine/.venv/bin/activate
imae monthly --as-of $(date -u +%Y-%m-%d)
```

## What the system does

Read these in order:

- `docs/HOW_IT_WORKS_PLAIN_LANGUAGE.md` — short on-ramp for a non-trader
- `docs/PROCESS_AND_RATIONALE.md` — deeper "why" walkthrough
- `docs/AUTONOMOUS_LOOP.md` — what the one-click loop is actually doing
- `docs/SOFT_SIGNALS_TAXONOMY.md` — every qualitative input the system can absorb
- `docs/LOCAL_QUICKSTART.md` — manual setup if you don't want the one-click flow

## Phase 0 methodology (locked)

- `docs/scoring_methodology.md`
- `docs/backtest_validity_methodology.md`
- `docs/point_in_time_methodology.md`
- `docs/benchmark_methodology.md`
- `docs/cost_tax_methodology.md`
- `docs/data_sources.md`
- `docs/architecture.md`

Everything else (PIT loader, feature engines, deployment engine, backtester, reports) is downstream of these.

## Important boundaries

- **Personal use only.** Not investment advice. Not a SEBI-registered service. No third-party capital. No auto-execution.
- **The autonomous loop tests engineering robustness, never strategy parameters.** Strategy promotion always goes through the train / validation / single-shot locked-holdout discipline in `backtest_validity_methodology.md` §7. The loop will *not* tune weights until the strategy beats the benchmark — that is the overfitting trap the methodology was built to prevent.
- **The LLM is an extractor, never a judge.** It pulls structured facts from filings with citations. It never produces a numeric score or a buy/sell verdict. All numeric scoring is deterministic.
