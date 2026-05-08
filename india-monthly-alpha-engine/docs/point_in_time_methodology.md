# Point-in-Time Methodology

Authoritative spec for what "point-in-time" means in `india-monthly-alpha-engine`, the PIT loader interface, restated-filings handling, and the property tests that protect against future-data leakage. This is the single most important architectural rule in the system. If it is wrong, every backtest result is invalid and every prediction is suspect.

This document depends on `scoring_methodology.md` and `backtest_validity_methodology.md`. It is depended on by every feature engine, every scoring engine, every backtest, and every replay. The PIT layer is the system's truth boundary.

## 1. Conventions and the PIT-availability rule

A field is **PIT-available** at `as_of_date` if its `source_timestamp ≤ as_of_date`. The PIT loader returns only PIT-available rows. Code outside the PIT layer must never query raw history tables directly; doing so circumvents this rule and creates leakage.

`source_timestamp` is the field that marks when a piece of data first became known to the public. It varies by data type and is precisely defined per-table:

- **Prices**: `trade_date` is the source_timestamp. The closing price of trade_date `T` is available from end-of-day `T`. Backtests that use the close of `T` to make a decision *on* `T` must clamp `as_of_date` to `T+1` for that decision (the "D-1 visibility" rule). The deployment engine's monthly rebalance day uses the prior trading day's close.
- **Quarterly financial statements**: `announcement_date` is the source_timestamp, NOT `period_end_date`. A Q4 result with period_end 31-Mar-2018 announced 15-May-2018 is unavailable on 15-Apr-2018. The PIT loader filters by `announcement_date ≤ as_of_date`.
- **Annual reports**: `filing_date` of the annual report PDF with the exchange / company website. Where unclear, use the AGM date as a fallback.
- **Filings (corporate announcements, regulatory disclosures)**: `filing_date`.
- **Shareholding patterns**: `filing_date` with the exchange (typically within 21 days of quarter-end).
- **Governance flags**: `detection_date` if it differs from `filing_date` of the underlying disclosure, otherwise `filing_date`. The detection_date is when the system's structured rule first triggered; for textual NLP-extracted flags, the detection_date is when the extraction was performed, with the underlying filing_date as the lower bound.
- **Index constituents**: `effective_from` is the date the constituent change took effect, NOT the announcement date. NSE typically announces constituent changes ~1 month before they take effect; the system uses the operational change date.
- **Corporate actions**: `ex_date` is the source_timestamp for backward price adjustment. `announcement_date` is the source_timestamp for forward decisions (e.g., knowing a buyback exists before the record date).
- **Credit ratings**: `publication_date` by the rating agency.

Every row in every history table must carry an explicit `source_timestamp` column or a derivable equivalent (announcement_date, filing_date, ex_date, etc.). Rows without a derivable source_timestamp are non-PIT and must not enter scoring.

## 2. The `as_known_at` semantics for restated filings

Companies routinely restate prior periods' results (corrections, audit adjustments, segment reclassifications). A naïve PIT loader that only filters by `announcement_date ≤ as_of_date` will return the *latest* value for a given period as of any future query date, which is itself a leak: at a backtest's `as_of_date`, the restated value was not yet known.

The fix is an `as_known_at` column on every restateable table.

Table schema for restateable rows: `(period_end_date, announcement_date, as_known_at, value, restatement_reason, supersedes_id)`.

- `period_end_date`: the period the value pertains to.
- `announcement_date`: when the value was first published.
- `as_known_at`: the date this *specific row* came into knowledge. For an original announcement, equals `announcement_date`. For a restatement, equals the restatement's announcement date.
- `value`: the actual reported number.
- `restatement_reason`: free text describing why the value was changed; null for original announcements.
- `supersedes_id`: foreign key to the prior row this one supersedes; null for original announcements.

PIT loader rule: for a given `(company_id, period_end_date, as_of_date)`, return the row with the **largest `as_known_at` ≤ `as_of_date`**. Multiple rows with the same `period_end_date` may exist; the loader picks the most recent one knowable at `as_of_date`.

Restatements are append-only. The system never updates an existing row in place. An ingest that detects a restated value creates a new row, links to its predecessor via `supersedes_id`, populates `restatement_reason`, and sets `as_known_at` to the restatement's announcement date.

This applies to: `financial_statements`, `ratios` (when ratios are stored rather than re-derived), and any computed feature stored in a `features` cache table. It also applies to `governance_flags` when a flag is later retracted (e.g., a textual flag found false on human review): a new row with `is_active = false` is created, the prior row is preserved, and the loader returns the row with the largest `as_known_at ≤ as_of_date`.

Prices and corporate actions are not restateable in this sense (the closing price of a past day does not change), so the standard `source_timestamp ≤ as_of_date` filter suffices for them.

## 3. PIT loader function signatures

The PIT layer exposes a single canonical interface. Every feature engine, scoring engine, and backtest function consumes this interface. Pseudocode signatures:

```
get_prices_until(company_id, as_of_date) -> DataFrame
    Columns: trade_date, open, high, low, close, adjusted_close, volume,
             delivery_volume, delivery_percentage
    Filter: trade_date <= as_of_date
    Sort:   trade_date ascending

get_financials_available_until(company_id, as_of_date) -> DataFrame
    Columns: period_end_date, announcement_date, as_known_at,
             revenue, ebitda, ebit, pat, eps, total_assets, total_debt,
             cash, net_worth, operating_cash_flow, free_cash_flow, capex,
             receivables, inventory, payables, ...
    Filter: as_known_at <= as_of_date
    For each (company_id, period_end_date), return only the row with
    the largest as_known_at within the filter.
    Sort: period_end_date descending.

get_filings_available_until(company_id, as_of_date) -> DataFrame
    Columns: filing_id, filing_type, title, filing_date, source_url,
             local_path, document_hash, parser_version, source_tier
    Filter: filing_date <= as_of_date
    Sort: filing_date descending

get_shareholding_available_until(company_id, as_of_date) -> DataFrame
    Columns: as_on_date (period), filing_date, promoter_holding_pct,
             promoter_pledge_pct, fii_holding_pct, dii_holding_pct, ...
    Filter: filing_date <= as_of_date
    Sort: as_on_date descending

get_governance_flags_until(company_id, as_of_date) -> DataFrame
    Columns: flag_id, flag_date, flag_type, severity, reliability_tier,
             description, evidence_document_id, human_review_required,
             human_review_status, is_active, as_known_at
    Filter: as_known_at <= as_of_date AND latest as_known_at per flag_id
            is the chosen row; return only rows where the chosen row has
            is_active = true.
    Sort: flag_date descending

get_index_constituents_as_of(index_name, as_of_date) -> set[company_id]
    Returns set of company_ids that are constituents of `index_name`
    at as_of_date. Filter: effective_from <= as_of_date < effective_to
    (where effective_to is null for currently-active membership).

get_corporate_actions_until(company_id, as_of_date) -> DataFrame
    Columns: action_id, ex_date, announcement_date, action_type,
             ratio_numerator, ratio_denominator, cash_amount,
             source_document_id
    For backward price adjustment: filter ex_date <= as_of_date.
    For forward decision queries: filter announcement_date <= as_of_date.
    Both filters are exposed; callers specify which they need.

get_features_as_of(company_id, as_of_date) -> dict[str, value]
    Returns a dict of pre-computed features for the company at as_of_date.
    Each feature has its own internal PIT semantics; the loader composes
    the results. Features that cannot be computed return null with a
    sentinel (see §9).

get_companies_active_at(as_of_date) -> set[company_id]
    Set of companies actively trading at as_of_date. A company is
    considered active if it has a price record within 30 trading days
    prior to as_of_date and is not in a delisted/suspended state at
    as_of_date.

get_delisted_companies_active_at(as_of_date) -> set[company_id]
    Set of companies that were trading at as_of_date but have since been
    delisted, suspended permanently, or merged out. The cohort engine
    and the universe-construction in backtest_validity_methodology.md
    §3 use the union of get_companies_active_at and this function.

get_credit_ratings_until(company_id, as_of_date) -> DataFrame
    Columns: rating_id, agency, rating, outlook, publication_date,
             as_known_at, source_url
    Filter: as_known_at <= as_of_date.
    Returns the chronological history of rating changes available at
    as_of_date.
```

These eleven functions are the canonical interface. Additions require a new methodology version. Renames are forbidden (callers depend on the names).

## 4. Architectural isolation

`pit/` is the **only** module that imports from `db/` raw history models. All other modules — `features/`, `engines/`, `backtest/`, `historical/`, `reports/` — import from `pit/` and from `db/` portfolio/state models only.

`ingestion/` is the only module that writes to raw history; it never reads from `pit/` (would be circular).

Enforcement is mandatory. The system uses an import-linter rule (or equivalent grep-based pre-commit hook) that blocks imports of `db.models.PricesDaily`, `db.models.FinancialStatements`, etc., from any module outside `pit/`. A violation fails CI; merging is blocked.

Direct DB access via raw SQL strings from outside `pit/` is also blocked. Code review and a regex check (`SELECT.*FROM (prices_daily|financial_statements|filings|governance_flags)`) catch SQL leaks; SQLAlchemy ORM is the only sanctioned access path and the import-linter rule covers it.

## 5. PIT property test (formalising backtest_validity_methodology.md §10.1)

The property test runs in CI on every commit and as a gate on every strategy version promotion.

Procedure:

Sample `K = 1000` random `(company_id, as_of_date)` pairs uniformly from the train + validation window (2012-01-01 to 2022-12-31). For each sample, call every PIT loader function from §3 and verify, for every returned row across every function, that the row's `source_timestamp` (or relevant timestamp field per §1) is `≤ as_of_date`. If any row violates, the test fails.

Synthetic restatement sub-test: for at least 10 of the K samples, the test temporarily injects a synthetic restatement row with `as_known_at` set to a date *after* `as_of_date`, calls the loader, and verifies the loader returns the prior (pre-restatement) row, not the synthetic one. After the assertion, the synthetic row is rolled back. This protects against the most subtle leak — restatements that look correct under naive `announcement_date ≤ as_of_date` filtering.

Sentinel sub-test: for samples where data legitimately does not exist at `as_of_date` (e.g., a company that did not yet have a Q4 result), the loader must return an empty result or a null with the correct sentinel (§9), never zero or interpolated values.

Failure of any sub-test blocks the strategy version from promotion. The test is deterministic via a fixed sampling seed stored alongside the strategy_version row.

## 6. Forbidden patterns

These patterns are anti-patterns; they are caught by lint or code review. Any occurrence is treated as a leakage bug and blocks merge.

- `datetime.now()`, `datetime.today()`, `time.time()` inside `features/`, `engines/`, `backtest/`, `historical/`, `reports/`. The current date is always passed as `as_of_date`. The only sanctioned use of clock time is in `app/`, `ingestion/`, and `db/` for ingestion timestamps.
- Direct ORM access (e.g., `session.query(PricesDaily).filter(...)`) to raw history tables from outside `pit/`.
- Cohort-engine code that uses cohort-member features without going through the PIT loader at the *cohort observation date*. The cohort engine must call `get_features_as_of(member_id, cohort_date_t)`, never `get_features_as_of(member_id, today)` or `get_features_as_of(member_id, as_of_date_of_outer_query)`.
- Test fixtures that assume "today" rather than passing `as_of_date` explicitly.
- Cache keys that omit `as_of_date` (a cache shared across `as_of_date` values is a leak).
- Hard-coded date strings inside engine code; all dates flow through the function signatures.

## 7. Determinism guarantees

The PIT loader's output for a fixed `(function, args, as_of_date)` must be byte-identical across runs. The replay determinism test in `backtest_validity_methodology.md` §10.5 depends on this.

Specific guarantees:

- DataFrame rows sorted deterministically (by primary key, then by `as_known_at` descending, then by `announcement_date` descending). No reliance on insertion order.
- Float values serialised to a fixed precision (6 decimal places) when the output is hashed for `feature_snapshot_hash`. The in-memory float values may have higher precision; the hash uses the canonical 6-decimal serialisation.
- No dict-iteration-order dependence in any serialised output; dicts are serialised with sorted keys.
- No parallel reductions inside the PIT layer that change with thread count. The PIT loader is single-threaded; callers may parallelise outside it.

## 8. Audit trail: `feature_snapshot_hash`

Every prediction stored in `historical_predictions` carries a `feature_snapshot_hash` column: a SHA-256 hash of the canonical serialisation of all PIT loader outputs used to produce that prediction.

Reproduction rule: a future replay run with the same `(strategy_version, as_of_date, company_id)` must produce the same `feature_snapshot_hash`. If it does not, either (a) the underlying data was re-ingested with different content (`ingest_version` changed), (b) the PIT loader has a non-deterministic bug, or (c) the strategy code consumed something outside the loader. Each case is debuggable from the hash mismatch.

The serialisation rules: rows ordered as in §7; floats at 6-decimal precision; null sentinels as their string names (`"value_null"`, `"not_yet_available"`, `"not_applicable"`); the function name and arguments included as a header; a trailing record of the `ingest_version` and `pit_loader_version` active during the call.

## 9. Missing data: three null sentinels

The Evidence Quality rubric (`scoring_methodology.md` §2) treats the three cases below differently. The PIT loader must distinguish them.

- `value_null`: the field exists in the DB and the underlying source explicitly reports null. Example: a company filing a result with no R&D spend reported. The Evidence Quality rubric does not penalise this case (the source is authoritative; the field is genuinely null).
- `not_yet_available`: the field has not been ingested at `as_of_date`. The latest source-side data is older than expected. Example: a Q4 result that should have been announced two months ago is missing. The Evidence Quality rubric penalises this (`-10` for a missing recent quarterly per scoring §2.1).
- `not_applicable`: the field genuinely does not apply to this company type. Example: a non-bank does not have a CASA ratio. The Evidence Quality rubric does not penalise this and does not include the field in any score that uses it.

The PIT loader returns nulls with these three sentinels, distinguishable in the returned data. The Evidence Quality engine and any feature engine that consumes nulls must dispatch on the sentinel.

## 10. Caching rules

The PIT loader is called many times per backtest month. Caching is allowed and recommended; the cache must respect PIT semantics.

- Cache key always includes `as_of_date`. A cache hit on a different `as_of_date` is a bug.
- Cache key also includes `ingest_version`. Re-ingestion of any underlying data invalidates the cache.
- The cache is per-process; no shared / cross-process cache that could pollute reproducibility.
- The cache is cleared at the start of each backtest run for safety; warm-cache replays are allowed only when explicitly opted into for performance, with the determinism test verifying byte-identical output.

## 11. Open questions deferred to sibling docs

1. **Ingestion-side schema for `as_known_at`**: how the ingestion pipeline populates this field on first ingest vs. on detected restatement — `data_sources.md`.
2. **Ingest_version semantics**: how it is incremented and when — `architecture.md`.
3. **Pre-2012 data availability**: the train window starts 2012, but cohort lookback uses 10y. Coverage of 2002–2012 is sparse; document policy in `data_sources.md`.
4. **NCLT / IBC resolution date treatment**: when a delisted company's resolution outcome is finalised years after the suspension, how does the cohort engine treat the forward-return tail — `data_sources.md` and `cost_tax_methodology.md`.
5. **Symbol changes / merger renames**: a company that becomes a different `company_id` after a merger should be tracked across the rename for cohort continuity; mechanism — `architecture.md`.

## 12. Dependencies

This document is referenced by:

- `scoring_methodology.md` (every score consumes PIT-available inputs).
- `backtest_validity_methodology.md` (validity tests assume the PIT loader's interface).
- `architecture.md` (module dependency rules build on §4).
- `cost_tax_methodology.md` (date-aware tax regime requires correct PIT timing of realisation events).
- All feature engine specs (forthcoming).

Changes to this document force a strategy version bump (`pit_loader_version`) and re-run of all validity tests.
