# Architecture

High-level system architecture spec for `india-monthly-alpha-engine`. This is the document a new engineer reads first to understand what the system is, how its modules connect, and what the architectural rules are. It locks the database engine, the LLM-use policy, the module dependency rules, the determinism rules, the logging and audit conventions, and the error-handling philosophy.

This document depends on `scoring_methodology.md`, `backtest_validity_methodology.md`, `point_in_time_methodology.md`, `benchmark_methodology.md`, `cost_tax_methodology.md`, and `data_sources.md`. It is depended on by every Phase 1 module spec.

## 1. System purpose

`india-monthly-alpha-engine` is a personal-use Indian equity monthly capital deployment engine. It decides where ₹25,000 per month should go: benchmark index, existing holdings, new stocks, replacement buys, or cash. The benchmark index (Nifty 500 TRI) is the default investment. Direct stocks are recommended only when point-in-time, cohort-tested expected alpha is strong enough to justify deviating from the index.

The system is governance-gated, point-in-time validated, locked-holdout tested. It does not auto-execute trades, does not advise third parties, does not publish recommendations, and is not a SEBI-registered service. It is decision support for a single user.

## 2. Subsystem map

The codebase is organised into eleven top-level packages under `src/`, each with a single responsibility.

`ingestion/` runs manual or semi-automated loaders that populate raw history tables with full source metadata (source_id, ingestion_timestamp, parser_version, document_hash). It writes raw data; it never reads PIT views.

`pit/` is the point-in-time loader layer. It is the only module permitted to read raw history tables. Every other module that needs historical data goes through this module's eleven canonical functions (per `point_in_time_methodology.md` §3).

`features/` computes deterministic features (financial ratios, technical indicators, valuation metrics, structured governance signals, evidence quality). All inputs come from `pit/`. The module is stateless and produces feature dicts keyed by `(company_id, as_of_date)`.

`engines/` houses the scoring engines: cohort expected alpha, business quality, earnings acceleration, valuation, governance, technical, sector, monthly buy, portfolio review, portfolio edge, deployment, index fallback. Engines consume features from `features/` and PIT data from `pit/`. They produce numeric scores and structured decisions. They are stateless within a call.

`backtest/` runs the monthly SIP backtester, the cost model, the tax model, the FIFO portfolio-lot accounting, the outcome evaluator, the calibration procedure, the survivorship analysis, and the bootstrap. It is the test harness for the rest of the system.

`historical/` runs the replay engine, the mistake analyzer, and the champion-challenger procedure. It produces `historical_predictions` rows, evaluates them against `historical_outcomes`, and proposes strategy version changes for human approval.

`reports/` generates the monthly deployment report, stock research reports, portfolio review report, replay reports, validity report, and self-improvement report. Reports are read-only over the DB and engines; they generate Markdown / HTML for the user.

`db/` holds SQLAlchemy models, sessions, and repositories. Models split into raw history (only `pit/` reads), portfolio/state (any module reads), and audit (any module writes via the logger).

`schemas/` holds Pydantic schemas for request/response shapes and structured outputs. They define the interface between subsystems and the persistence layer.

`ui/` is a Streamlit read-only dashboard. It reads from the DB and from generated reports; it never directly invokes engines (decisions are computed monthly and persisted, then displayed). The UI is deferred until Phase 18 of the implementation plan.

`utils/` contains date helpers, financial utility functions, validation helpers, and math primitives.

## 3. Database engine

The system uses **SQLite** for OLTP and **DuckDB** for analytics, side by side, with no shared writes.

SQLite holds operational state: `portfolio_holdings`, `portfolio_lots`, `monthly_deployment_plans`, `monthly_buy_actions`, `historical_predictions`, `historical_outcomes`, `strategy_versions`, `governance_flags`, `governance_flag_history`, `source_conflicts`, audit logs.

DuckDB holds analytical data: `prices_daily`, `financial_statements`, `ratios`, `filings`, `corporate_actions`, `index_constituents_history`, `shareholding`, `credit_ratings`, and any wide feature cache. These tables are large (millions of rows for prices alone over a 10-year × 1000-company window) and DuckDB's columnar engine outperforms SQLite by orders of magnitude on the cohort lookups and time-series windows the backtest engine runs.

Rationale: this is a single-user personal system. Postgres is overkill; the operational overhead of running and maintaining a Postgres server for a workstation tool is unjustified. SQLite + DuckDB run as embedded libraries with zero administration, support transactional writes (SQLite) and analytical reads (DuckDB), and have well-maintained Python bindings.

The two databases never share writes. DuckDB views can be materialised against SQLite tables for cross-DB consistency where needed (e.g., joining portfolio state with price history), but writes flow only one direction per table.

DB schema migrations use **Alembic** with named revisions. Rollbacks are tested in CI; a migration that does not have a tested rollback is rejected. Migrations are versioned alongside `strategy_versions.architecture_version`.

## 4. LLM-use policy

LLMs are permitted as evidence extractors with citations. They are **not** permitted to produce numeric scores or to opine on whether a stock is good.

Allowed LLM uses:
- Extract structured facts from filings (e.g., "auditor name", "promoter pledge percentage from a shareholding pattern PDF").
- Summarise filings for the human reviewer with explicit citations to source paragraphs.
- Identify candidate evidence snippets relevant to a scoring sub-component.
- Classify document sections (e.g., "this paragraph is the auditor's report").
- Flag *possible* governance issues for human review (textual-tier governance flags per `scoring_methodology.md` §9.1).

Disallowed LLM uses:
- Producing any numeric score that enters the Monthly Buy Score, Portfolio Edge Score, or any sub-score.
- Overriding deterministic scores or governance gates.
- Generating buy/sell recommendations.
- Producing claims that cannot be cited to a source document_hash.

When an LLM-extracted fact is used in scoring (only allowed for textual-tier governance flag *candidates* pre-human-review), it counts as a **tier-5 source** (concall-transcript level) for Evidence Quality scoring per `data_sources.md` and `scoring_methodology.md` §2.1. LLM extractions never short-circuit to tier-1.

LLMs run in deterministic mode preferred (temperature 0). Non-deterministic outputs are a code smell and are treated as bugs. Every LLM call logs `model`, `prompt_hash`, `prompt_version`, response, latency, and cost. Outputs are stored as evidence rows that can be audited and replayed.

## 5. Module dependency rules

The architectural rules below are enforced via `import-linter` (or an equivalent grep-based pre-commit hook) in CI. A violation fails the build.

- `pit/` is the only module that imports from `db.models` raw history models (`PricesDaily`, `FinancialStatements`, `Filings`, `GovernanceFlags`, `CorporateActions`, `IndexConstituentsHistory`, `Shareholding`, `CreditRatings`, etc.).
- `features/`, `engines/`, `backtest/`, `historical/`, `reports/` import from `pit/` and from `db.models` portfolio/state models only. Direct raw-history imports are blocked.
- `ingestion/` writes to raw history; never reads from `pit/` (would be circular).
- `ui/` reads from `db/` portfolio/state and from generated reports. It does not invoke engines directly. Decisions are computed monthly and persisted; the UI displays the persisted decision.
- Cross-package circular imports are forbidden.

The lint configuration is committed to the repo. Modifications to the rules require a new `architecture_version`.

## 6. Determinism rules

The replay determinism test in `backtest_validity_methodology.md` §10.5 is the gate for all of the rules below.

- No `datetime.now()`, `datetime.today()`, or `time.time()` in any code path under `features/`, `engines/`, `backtest/`, `historical/`, `reports/`. The current date flows in as `as_of_date`. The only sanctioned use of clock time is in `app/`, `ingestion/`, and `db/` for ingestion timestamps.
- No randomness without a fixed seed. Bootstrap, sampling, and any stochastic procedure fix the seed in the `strategy_versions` row.
- No floating-point parallel reductions that change with thread count. The numerical core of the backtester is single-threaded; parallelism is allowed only where the result is provably order-independent.
- No dict-iteration-order dependence in serialised outputs. All dict serialisation uses sorted keys.
- All file IO that affects outputs is deterministic (no temp file names with PIDs in them, no system-locale-dependent string formatting).

The `feature_snapshot_hash` on `historical_predictions` (per `point_in_time_methodology.md` §8) is the audit handle: a reproduction must match the stored hash.

## 7. Logging and audit

Every prediction, deployment plan, and strategy promotion is recorded with the full version-stamp tuple:

```
strategy_version
scoring_methodology_version
backtest_validity_methodology_version
benchmark_methodology_version
point_in_time_methodology_version
cost_model_version
tax_model_version
ingest_version
pit_loader_version
architecture_version
```

The tuple goes onto every row in `historical_predictions`, `monthly_deployment_plans`, and `strategy_versions`. A version mismatch on replay surfaces immediately.

Every LLM call logs `model`, `prompt_hash`, `prompt_version`, response, latency, cost, and the document_hash of any cited source. LLM outputs are stored as evidence rows referenced by their hash so any prediction citing the LLM output can be reproduced.

Every ingestion run logs `source_id`, `files_loaded`, `rows_added`, `rows_updated`, `parser_version`, and `document_hash` per file. The `ingest_version` is incremented when a re-ingestion produces different content; this is the cache invalidation key (per `point_in_time_methodology.md` §10).

Logs are written to a `logs/` directory (gitignored) and to structured-log tables in SQLite for queryability. The structured-log library is **structlog** (default; alternative `loguru` documented but not used).

## 8. Error-handling philosophy: fail loudly, never silently substitute

- Missing data is null with a sentinel (per `point_in_time_methodology.md` §9), never zero, never interpolated. The Evidence Quality rubric handles the consequence.
- Unsupported corporate-action types fail the backtest with a precise list of affected positions (per `backtest_validity_methodology.md` §4.1). Silent mis-pricing is forbidden.
- Source conflicts are auto-resolved by tier (higher tier wins per `data_sources.md`) and logged to `source_conflicts` for periodic review. The auto-resolution is not silent — it is logged.
- Validity-test failures (per `backtest_validity_methodology.md` §10) block strategy promotion. There is no override mechanism at runtime; a failed test means a methodology issue that must be fixed via a new strategy version.
- Fatal governance flags block allocation per `scoring_methodology.md` §4.3. They cannot be overridden at runtime; they can only be removed by adjusting the underlying detection rule via a new strategy version (which is itself logged).
- Import-linter violations, lint failures, type errors, and test failures all block CI. There is no merge-on-red.

## 9. Configuration and secrets

Configuration lives in `app/config.py` with environment-variable overrides. A `.env.example` is committed to the repo with the structure but no values; real `.env` files are gitignored.

The system has minimal secret needs because it does not auto-execute trades. API keys for data sources (e.g., a Screener key, a paid news feed) live in `.env`. No real secrets are committed to source.

Configuration changes that affect behaviour (cost-model parameters, tax thresholds, regime cutover dates) are not in `.env` — they live in `strategy_versions` rows or in the methodology docs. `.env` is for environment-specific paths and credentials only.

## 10. Versioning and migrations

Strategy versions are immutable. Any change to `weights_json`, `thresholds_json`, the cost model, the tax model, or any methodology version creates a new row in `strategy_versions`. Previous versions are preserved indefinitely so historical predictions remain reproducible.

Methodology docs themselves are versioned. A change to `scoring_methodology.md` increments `scoring_methodology_version`; the version is recorded on every row of `historical_predictions` made under that doc version. Replay across a methodology change shows up as a version mismatch and triggers a deliberate decision.

DB schema migrations are managed with **Alembic**. Each migration carries a tested down() rollback. CI runs the up→down→up sequence to verify reversibility.

## 11. Architectural test strategy

The system has four layers of tests, each with a specific role:

- **Unit tests** per engine using fixed PIT fixtures. Each engine has a deterministic input → deterministic output test. Run on every commit.
- **Property tests** for the PIT loader (per `point_in_time_methodology.md` §5). Random `(company_id, as_of_date)` samples; no leakage. Run on every commit and as a promotion gate.
- **Validity tests** for the backtester (per `backtest_validity_methodology.md` §10). Survivorship, cost-drag, calibration, replay determinism, corporate-action continuity, tax-lot correctness. Run as a promotion gate.
- **Integration / replay tests**: a fixed historical replay over a 12-month sub-window with a known expected `feature_snapshot_hash` for each prediction. Run weekly and on any change to `pit/`, `features/`, or `engines/`.

CI runs unit + property tests on every commit; validity + integration tests on a nightly schedule and as a promotion gate. No PR merges on red.

## 12. Performance and scale

Universe and data scale assumptions:
- Universe: ≈ Nifty 500 + ~500 distressed/historical names ≈ 1,000 companies.
- Price history: 12 years × 250 trading days × 1,000 companies ≈ 3 million rows. Trivially handled.
- Quarterly financial history: 12 years × 4 quarters × 1,000 companies × ~50 fields = ~2.4 million field-rows. Trivially handled.
- Backtest: 12 years × 12 months = 144 rebalance dates. Cohort lookups per rebalance dominate cost.

DuckDB handles the cohort lookups in seconds per rebalance month on a workstation. The full backtest over 144 months runs in ≤ 15 minutes single-threaded on commodity hardware.

No multiprocessing in v1. A single-threaded backtest is sufficient and avoids the determinism risk of parallel reductions. If walk-forward with more candidates becomes a bottleneck, parallelisation across rebalance months (where the months are independent) can be added later under explicit determinism review.

## 13. Deployment and runtime

The system runs as a single Python process invoked monthly via a `Makefile` target (`make monthly`) or the Streamlit dashboard. There is no daemon, no background worker, no message queue, no API server.

Workflows:
- `make ingest`: run the manual ingestion loaders against the latest available data dumps in `data/raw/`.
- `make features`: refresh the feature cache for the current `as_of_date`.
- `make monthly`: run the deployment engine for the current month, write the deployment plan, generate the monthly report.
- `make backtest`: run the monthly SIP backtester for a specified period and strategy version.
- `make ui`: start the Streamlit read-only dashboard.

Ad-hoc exploration is allowed inside Jupyter notebooks under `notebooks/` (gitignored). Production decisions go through the Makefile target so they are logged with the full version-stamp tuple.

## 14. Phase 0 doc dependency graph

`scoring_methodology.md` is the most-cited document; it defines the scores every other doc references. `backtest_validity_methodology.md` depends on scoring (for the score definitions) and is the gate for promotion. `point_in_time_methodology.md` underlies both — every score and every test depends on PIT semantics. `benchmark_methodology.md` defines what alpha is measured against; it is referenced by the validity doc for the style attribution and by scoring for the index allocation. `cost_tax_methodology.md` defines the friction model used by the validity tests, the simulator, and the replacement rule. `data_sources.md` is the lookup for source-tier ordering used by the Evidence Quality rubric and is the seed for the survivorship-correct universe.

This document (`architecture.md`) sits above all of them: it locks the engineering rules that make the methodology docs operationalisable.

## 15. Open questions

1. **Alembic specific version**: pinned in `pyproject.toml`; not yet selected.
2. **Pydantic v1 vs v2**: defaulting to v2 for v1 of the project unless a specific dependency forces v1.
3. **import-linter specific version pin**: TBD; latest stable at Phase 1 start.
4. **Streamlit phase boundary specifics**: the dashboard is deferred to Phase 18 of the implementation plan; whether a minimal CLI-only reporter is sufficient before that is open.
5. **Notebook environment**: Jupyter Lab vs VS Code notebooks for exploration; not architecturally significant.
6. **CI runner**: GitHub Actions assumed by default; no explicit configuration locked here.

## 16. Dependencies

This document is referenced by every Phase 1 module spec (forthcoming). It depends on all five sibling methodology docs and on the two already-locked docs.

Changes to this document force an `architecture_version` bump on `strategy_versions` and a re-run of the integration / replay tests.
