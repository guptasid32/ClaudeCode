# Backtest Validity Methodology

Authoritative spec for how `india-monthly-alpha-engine` decides whether a strategy version is good enough to deploy. This document is the gate between "the system produces nice-looking historical returns" and "the system produces returns we should believe." It locks the period split, universe construction, statistical tooling, calibration procedure, champion-challenger promotion gates, multiple-testing correction, style-attribution, and required validity tests.

This document depends on `scoring_methodology.md` (which uses the bucket-calibration procedure defined in §6 below). Subsequent docs (`cost_tax_methodology.md`, `point_in_time_methodology.md`) plug into the cost-drag and PIT-leakage tests defined here.

## 1. Conventions and non-goals

A **strategy version** is a fully-specified configuration of the system: scoring weights, sub-score formulas, cohort matching parameters, allocation buckets, replacement-rule thresholds. Every strategy version is registered in `strategy_versions` with a unique `version` and immutable `weights_json` and `thresholds_json`. Strategy code at runtime reads from this row, not from constants in source.

A **monthly SIP backtest** is a deterministic replay over a period: at each rebalance date the system computes scores from PIT data, produces an allocation, and the simulator executes that allocation against corporate-action-adjusted prices, costs, and taxes.

The **benchmark** for alpha claims is Nifty 500 TRI. Style-adjusted alpha (§9) is the cleaner claim once the active book drifts mid/small-cap-heavy.

This document does not specify how features are computed (that is per-engine spec) or how to ingest data (`data_sources.md`). It specifies how to *test* what the rest of the system produces.

## 2. Period split: train, validation, holdout

The dataset is partitioned exactly once. The partition is committed to source control as fixed dates. It must not be changed except via a deliberate, logged refresh that re-locks the holdout going forward (and explicitly invalidates any strategy versions promoted under the old partition).

For initial v1, with assumed data availability from 2010-01-01:

- **Train**: 2012-01-01 to 2018-12-31. Used for strategy development, cohort engine fitting, sub-score weight exploration.
- **Validation**: 2019-01-01 to 2022-12-31. Used for champion-challenger strategy selection.
- **Holdout**: 2023-01-01 to 2024-12-31. Used **only** for the final single-shot test of the pre-registered strategy from validation. Never used for tuning.

Rationale for the gap before 2012: feature engineering needs at least 12–24 months of history before the first backtest month. Cohort matching (§3 of scoring methodology) uses a 10-year expanding window, which means cohort signal is degraded at the start of the train window — that is acceptable since the train window's role is exploration, not selection.

The first 12 months of any window are warm-up and may be excluded from outcome computation if forward-return needs them.

### 2.1 Walk-forward variant

In addition to fixed-period backtests, every promoted strategy must pass a **walk-forward** test on train + validation: for each rebalance date `t`, score weights and cohort statistics are computed using only data available at `t`, never the full-period parameters. This is more expensive but is the cleanest test of the system's ability to make decisions in real time.

Walk-forward results are reported alongside fixed-period results. Promotion requires both to pass.

## 3. Universe construction (survivorship-correct)

Every backtest at rebalance date `t` must construct its universe from:

```
universe(t) = (
    index_constituents_history.get_companies_in_index_at(index_name='Nifty500', t)
  ∪ delisted_companies_active_at(t)
)
```

`delisted_companies_active_at(t)` returns companies that were trading at `t` but were later delisted, suspended, merged out, or otherwise removed. This is mandatory. A backtest that uses today's index constituents projected backward (the default in many retail tooling stacks) silently overstates returns by the survivorship gap.

### 3.1 Minimum coverage requirement

Before any strategy version can be promoted, the data store must contain at least 50 known-distressed historical Indian equity cases with full price and financial history through their delisting/suspension event. Examples: Yes Bank (recapitalisation event), DHFL (resolution), Cox & Kings, Jet Airways, IL&FS group. The list is curated in `data/raw/delisted_companies/seed_list.md` and is the seed for the survivorship test (§10.2).

If the seed list is incomplete, the system reports `survivorship_universe = INSUFFICIENT` and promotion is blocked.

### 3.2 Index-constituent PIT

Index constituent membership at `t` is determined from `index_constituents_history` rows where `effective_from ≤ t < effective_to`. NSE rebalances Nifty 500 semi-annually; the table must reflect each rebalance event with `effective_from` matching the constituent change date (not the announcement date — the constituent change is the operational event).

## 4. Forward-return computation

A backtest's truth values are forward returns. They must be computed from corporate-action-adjusted prices and must reflect every realisable cash flow, including delisting recoveries and suspension impacts.

### 4.1 Corporate actions

Adjusted prices are computed from `corporate_actions` rows (`scoring_methodology.md` §1 references). Splits, bonuses, and dividends produce continuity-preserving adjustments backward from the ex-date. Rights, buybacks, demergers, and mergers require explicit handling per action type:

- **Split**: backward-multiply pre-ex prices by `ratio_denominator / ratio_numerator`.
- **Bonus**: same as split mathematically (e.g., 1:1 bonus equivalent to 2-for-1 split).
- **Dividend**: backward-subtract `cash_amount`. (The TRI benchmark already reinvests dividends; the active book reinvests at next rebalance.)
- **Rights**: pre-ex price adjusted by theoretical ex-rights price formula; entitlement value tracked separately; if not subscribed, rights lapse and value is lost (modelled as a one-off adjustment).
- **Buyback**: tendered shares treated as a sale at the buyback price on the buyback record date. Acceptance ratio is applied if known; otherwise modelled as 100% acceptance.
- **Demerger / merger**: each event is a tagged corporate action. The backtest must split the original holding into the resulting securities at their first-day prices on the post-event listing.
- **Delisting**: see §4.2.

If a corporate action type is not yet supported (no parser for it), holdings affected by that event are flagged `unsupported_corporate_action` and the backtest fails with a precise list. This is preferable to silently mis-pricing the position.

### 4.2 Delisting and suspension

When a holding's company delists or is permanently suspended:

- If a final settlement / liquidation distribution is known, use it as the realised proceeds on the delisting date.
- If only the last traded price is available, use it — this is the closest proxy and matches what a retail investor would have realised.
- If neither is available (e.g., open-ended suspension followed by exchange removal with no recovery), mark the position at `recovery_rate × cost_basis` where `recovery_rate` is curated per case in `data/raw/delisted_companies/seed_list.md` (default 0%, conservative).

A suspended-not-yet-delisted holding pauses forward-return computation: the position is held at last traded price with zero return contribution until reactivation or delisting. The simulator does not pretend the position is liquid.

### 4.3 Tax-lot accounting in forward-return computation

The simulator uses `portfolio_lots` (FIFO) for every sell event. Realised STCG / LTCG is computed on the lot-by-lot path, not on a portfolio-average basis. Tax is deducted from cash on the realisation date (next month's available capital).

The `cost_model_version` and `tax_model_version` columns of `strategy_versions` track which models were active during a given backtest. Two backtests of the same strategy under different cost or tax models are different runs and are not directly comparable.

## 5. Cost and tax modelling

Backtests must report gross, net-of-cost, and net-of-cost-and-tax results separately. The exact cost model (transaction charges, STT, stamp duty, exchange fees, SEBI fees, GST, brokerage, slippage) is locked in `cost_tax_methodology.md`. The exact tax model (date-aware STCG/LTCG regimes including the 23-July-2024 transition) is also there.

The backtest reports must include:

- **Gross CAGR**: ignores costs and taxes. Diagnostic only; never the headline number.
- **Net-of-cost CAGR**: applies the cost model.
- **Net-of-cost-and-tax CAGR**: applies the cost model and the date-aware tax regime. **This is the headline number**.
- **Cost drag** (gross − net-of-cost) and **tax drag** (net-of-cost − net-of-cost-and-tax) reported as separate annualised figures for transparency.

Any strategy whose alpha vanishes under the net-of-cost-and-tax computation is not promoted.

## 6. Bucket calibration procedure (Portfolio Edge Score)

Referenced from `scoring_methodology.md` §5.4. Detailed steps:

1. **Restrict to train + validation only**. Holdout is excluded.
2. For each rebalance month `t` in train + validation:
   a. Compute `PES_t` from PIT data at `t`.
   b. Compute the active stock allocation the system would make under the candidate strategy (the strategy version being calibrated).
   c. Hold that allocation for 12 months. Compute realised return contribution from active stocks plus index portion (Nifty 500 TRI for the index allocation).
   d. Compute realised forward excess return: `realised_portfolio_return(t→t+12) − Nifty500TRI(t→t+12)`.
   e. Apply cost and tax model. Use the net-of-cost-and-tax excess return.
3. Group months by PES bucket (boundaries 50, 60, 70, 80, 90 from `scoring_methodology.md` §5.3).
4. For each bucket, compute mean and median forward excess return and 95% block-bootstrap CI on the mean. Block length 12 months (annual seasonality and autocorrelation), 10,000 resamples.
5. **Acceptance**:
   - Mean forward excess return is monotonically non-decreasing across buckets.
   - The bootstrap CI lower bound on (mean of bucket > 90 minus mean of bucket ≤ 50) is ≥ 0.
6. **Failure path**:
   - First, collapse adjacent non-monotonic buckets (e.g., merge 60–70 and 70–80 into a single 60–80 bucket) and re-run the test with 5, then 4, then 3 buckets.
   - If 3-bucket aggregation also fails, calibration fails. The system reverts to the conservative default in `scoring_methodology.md` §5.3 failure clause: PES > 50 → ₹20k index / ₹5k active; PES ≤ 50 → ₹25k index. No further differentiation.
7. **Result is logged** in `strategy_versions` row alongside the bucket-mean table and CI table. A bucket calibration cannot be silently retried — each retry produces a new strategy version.

The 20% index floor described in `scoring_methodology.md` §5.3 stays in effect regardless of calibration outcome until the holdout test (§7) confirms the > 90 bucket has positive mean forward excess return with bootstrap CI lower bound > 0.

## 7. Champion-challenger procedure

The system runs a small, pre-registered set of strategy versions in parallel. The current production strategy is the **champion**. Alternatives are **challengers**. Promotion of a challenger to champion follows a strict procedure:

### 7.1 Initial challenger set (v1)

Six strategies, locked in `strategy_versions` before any validation testing:

1. **conservative_index_heavy**: PES bucket boundaries shifted up by 10 (more index in middle PES values).
2. **equal_weight**: Monthly Buy Score sub-score weights all set to 1/9.
3. **quality_heavy**: business_quality and governance_safety weighted at 0.25 each; valuation reduced to 0.05.
4. **earnings_acceleration_heavy**: earnings_acceleration weight raised to 0.30; CEA reduced to 0.10.
5. **valuation_dislocation_heavy**: valuation_sanity weight raised to 0.25; technical reduced to 0.03.
6. **hybrid_balanced**: master plan v2 weights, the default v1 starting point.

Equal-weight is mandatory per `scoring_methodology.md`; the others come from the v2 plan §17.

### 7.2 Validation gate

For each strategy:

1. Run a fixed-period backtest on validation (2019-01-01 to 2022-12-31).
2. Run a walk-forward backtest on train + validation, evaluated only on validation months.
3. Compute net-of-cost-and-tax CAGR, mean forward excess return per rebalance, max drawdown, underperformance duration, and 95% block-bootstrap CI (block 12, resamples 10,000) on mean monthly excess return.
4. Compute style-adjusted alpha per §9.

A strategy **passes validation** if all of:

- net-of-cost-and-tax CAGR > Nifty 500 TRI net-of-cost CAGR by ≥ 1.5 percentage points annualised.
- Block-bootstrap 95% CI lower bound on mean monthly excess return is > 0.
- Style-adjusted alpha is > 0 with bootstrap CI lower bound > 0.
- Max drawdown is no worse than Nifty 500 TRI's max drawdown plus 5 percentage points absolute.
- Underperformance duration (longest stretch where rolling 12m excess return is negative) ≤ 24 months.

A strategy that fails any of these does not advance.

### 7.3 Pre-registration before holdout

Among strategies that pass validation, the **single best** by net-of-cost-and-tax CAGR is **pre-registered** as the holdout candidate. Pre-registration is logged with a timestamp and the strategy version hash. After pre-registration, no further changes to the strategy or its parameters are permitted before the holdout test. Other strategies that passed validation are recorded but are not retested on holdout.

This is the multiple-testing correction (§8). Pre-registration is preferred to Bonferroni because with a 24-month holdout window and 6 strategies, Bonferroni is too conservative to clear realistic alpha; pre-registering the validation winner concentrates the test on a single hypothesis without the inflation.

### 7.4 Holdout test (single shot)

The pre-registered strategy is run once on the holdout window (2023-01-01 to 2024-12-31). Both fixed-period and walk-forward backtests are required.

The strategy **passes holdout** if all of:

- net-of-cost-and-tax CAGR ≥ Nifty 500 TRI net-of-cost CAGR (any positive margin; the holdout window is short and the bar is whether the system did not destroy value).
- Block-bootstrap 95% CI lower bound on mean monthly excess return ≥ 0 (zero is allowed; the holdout sample is small).
- Style-adjusted alpha ≥ 0.
- Max drawdown is no worse than benchmark + 5 percentage points absolute.
- No PIT-leakage anomalies surfaced (per §10.1).

If the strategy passes holdout, it is promoted to champion. The promotion is logged in `strategy_versions` with `approved = true` and human approver identity.

### 7.5 No second pick

If the pre-registered strategy fails holdout, **no other strategy is tested on this holdout**. The current champion stays in place. The cycle ends. The next cycle requires a fresh holdout window — typically by waiting another 12 months and re-locking the holdout — or by re-partitioning the data with explicit invalidation of the prior holdout.

This is the rule that turns the holdout from a search into a test.

### 7.6 Re-locking the holdout

When the holdout has been used (whether promotion succeeded or failed), it is **burned**. The next promotion cycle requires either:

- 12 more months of post-holdout data, which becomes the new holdout (the prior holdout joins validation).
- An explicit human decision, logged in `strategy_versions`, to redefine the partition. This is a last resort and is a flag for external review.

## 8. Multiple-testing correction

Six challengers tested on the same holdout would inflate the false-positive rate roughly 6×. The pre-registration scheme in §7.3 controls this by reducing the number of holdout tests to one. No Bonferroni adjustment is applied because the post-pre-registration test is a single hypothesis.

If pre-registration is not possible for some reason (e.g., a future cycle needs to test multiple genuinely independent strategies), apply Bonferroni: divide the nominal α (0.05) by the number of strategies tested, and use the adjusted α to construct CIs and significance gates.

## 9. Style-aware benchmark attribution

Outperformance against Nifty 500 TRI can be passive style drift (e.g., tilting mid- or small-cap-heavy in a small-cap rally) rather than stock selection. The headline alpha number must be the residual after style controls.

### 9.1 Style factors

Use a 4-factor model adapted to Indian equities:

- **MKT**: Nifty 500 TRI minus risk-free (overnight T-bill rate).
- **SMB**: Nifty Smallcap 250 TRI − Nifty 100 TRI.
- **HML**: portfolio of high book-to-market minus low book-to-market deciles within Nifty 500. Constructed from `ratios` table at each rebalance.
- **MOM**: 12-1 month price momentum decile spread within Nifty 500.

Factor returns are computed monthly from the same data the system uses. Construction details are deferred to the feature engine spec.

### 9.2 Attribution regression

For each backtest, regress the strategy's monthly net-of-cost-and-tax excess return on the four factors:

```
r_strategy_t − r_f_t = α + β_MKT × MKT_t + β_SMB × SMB_t + β_HML × HML_t + β_MOM × MOM_t + ε_t
```

The intercept `α` (annualised) is the **style-adjusted alpha**. This is the headline alpha claim. CIs on `α` use the Newey-West HAC estimator (lag 12) to handle autocorrelation, plus the block-bootstrap CI as a robustness check.

### 9.3 Reporting requirement

Every backtest report must show:

- Raw mean monthly excess return vs. Nifty 500 TRI.
- Style-adjusted alpha (annualised).
- Factor loadings (β_MKT, β_SMB, β_HML, β_MOM) with CIs.

A strategy with high raw excess return but β_SMB ≈ 0.5 is not delivering selection alpha; it is delivering a small-cap bet. The report must surface this.

## 10. Required validity tests

These are the gating tests for any strategy version. All must pass before promotion. The tests live under `tests/` and are run as part of the backtest pipeline.

### 10.1 PIT property test

Property test: for `K = 1000` random samples of `(company_id, as_of_date)` over the train + validation window, every field returned by every PIT loader function must have `source_timestamp ≤ as_of_date`. Failure of any sample fails the strategy.

### 10.2 Survivorship test

Run the backtest twice on the validation window:

- Survivor-only: universe is today's Nifty 500 constituents projected backward.
- Survivorship-correct: universe is `index_constituents_history(t) ∪ delisted_companies_active_at(t)` per §3.

Survivor-only must produce a meaningfully higher CAGR than survivorship-correct. The gap is reported as `survivorship_bias_estimate`. If the gap is < 1 percentage point annualised, the delisted-company seed list is probably incomplete and promotion is blocked pending more delisted-company history.

### 10.3 Cost-drag test

Run the backtest twice on validation:

- Zero-cost / zero-tax.
- Full cost and tax model.

The drag must match an analytical estimate within ±20% relative tolerance. The analytical estimate is computed from average monthly turnover, average ticket size, and the cost/tax model parameters. A large mismatch indicates either the cost model is misapplied or the tax-lot accounting is broken.

### 10.4 Calibration test (decile monotonicity)

Bucket all historical predictions in `historical_predictions` by `monthly_buy_score` decile (after PIT and survivorship corrections). Compute mean 12-month forward excess return per decile.

The series must be **monotonically non-decreasing** from decile 1 (lowest score) to decile 10 (highest score), or at least show a positive Spearman rank correlation between decile and forward excess return with p < 0.05.

If decile monotonicity fails, the score is not predictive and the strategy cannot be promoted regardless of headline CAGR.

### 10.5 Replay determinism test

Run the same monthly replay twice with the same inputs. Output must be byte-identical. Any stochasticity (random seeds, `datetime.now()`, dictionary iteration order in score breakdowns) is a bug. The test compares the SHA-256 of the deployment plan and `historical_predictions` rows.

### 10.6 Corporate-action continuity test

For a curated set of test cases (at least one of each: split, bonus, rights, buyback, demerger, merger, dividend, delisting), the simulated returns must be continuous across the ex-date. Specifically: a holding's `cost_basis × adjustment_factor` and the next-day's adjusted-price-based market value must produce zero return contribution from the corporate action itself.

### 10.7 Tax-lot correctness test

For a curated set of buy-sell-buy-sell sequences with known FIFO outcomes:
- Realised gain matches hand-computed value.
- STCG/LTCG classification is correct given the holding period at sale date.
- Tax regime applied matches the date (pre/post 23-July-2024 transition).

## 11. Backtest report contents

Every promoted strategy carries a backtest report. The report's mandatory contents:

- Strategy version hash and human-readable description.
- Period: train, validation, holdout dates.
- Universe coverage: number of companies, including count of delisted/suspended.
- Walk-forward and fixed-period results, both reported.
- Gross / net-of-cost / net-of-cost-and-tax CAGR.
- Mean and median monthly excess return vs. Nifty 500 TRI, with block-bootstrap CIs.
- Style-adjusted alpha with HAC and bootstrap CIs.
- Factor loadings.
- Max drawdown.
- Longest underperformance duration (rolling 12m).
- Turnover (annualised).
- Cost drag and tax drag.
- Bucket calibration table (PES bucket → mean forward excess return → CI).
- Decile monotonicity test result.
- Survivorship-bias estimate.
- Validity test pass/fail summary.
- Number of months in each PES bucket (so the report shows where the system actually spent its time).
- Number of fatal-flag rejections, broken down by structured / textual tier.
- Pending-evaluation count (predictions whose 12-month forward window has not yet completed).

A report missing any of these is incomplete. Promotion is blocked.

## 12. Failure modes that invalidate alpha claims

A strategy must be re-tested from scratch (and the prior holdout burned) if any of these are detected post-promotion:

- **PIT leakage**: any code path is found to access non-PIT-constrained data. The audit log on `historical_predictions` must allow reproducing the PIT view used; if reproduction shows future data was accessible, the alpha claim is invalid.
- **Survivorship**: a delisted company that was active during the backtest window is found missing from the universe.
- **Cohort lookahead**: a cohort member's features were computed from data after the cohort observation date.
- **Restated-filings leakage**: a value used was the restated value, not the value as known at `as_of_date`. Mitigated by `as_known_at` semantics in `point_in_time_methodology.md`.
- **Multiple-testing without correction**: more than the pre-registered single strategy was tested on a single holdout.
- **Strategy mutation post-pre-registration**: any change to `weights_json`, `thresholds_json`, `cost_model_version`, or `tax_model_version` between pre-registration and holdout test invalidates the test.

When any of the above is detected, the strategy is reverted, the holdout is burned, and a new partition is locked.

## 13. Open questions deferred to sibling docs

1. Exact cost-model parameters (transaction charges, STT, stamp duty, slippage by liquidity bucket) — `cost_tax_methodology.md`.
2. `as_known_at` semantics and restatement handling — `point_in_time_methodology.md`.
3. Indian small-cap factor universe construction (which exact small-cap index for SMB) — `benchmark_methodology.md`.
4. Risk-free rate proxy for MKT factor (1-month T-bill, MIBOR, repo rate?) — `benchmark_methodology.md`.
5. HML and MOM factor construction details (decile boundaries, rebalance cadence) — feature-engine spec.
6. Treatment of currency or capital-gains tax regime changes outside the documented STCG/LTCG transitions — `cost_tax_methodology.md`.
7. Reference data sources for delisted-company seed list and recovery rates — `data_sources.md`.

## 14. Dependencies

This document depends on, and must be re-validated against:

- `scoring_methodology.md` — for what the scores are.
- `point_in_time_methodology.md` — for what "PIT-constrained" means in §10.1.
- `cost_tax_methodology.md` — for the cost and tax model used in §5 and §10.3.
- `benchmark_methodology.md` — for benchmark and style-factor construction.
- `data_sources.md` — for source-tier ordering and delisted-company seed list.

Changes to any of these may force changes here. Versioned alongside `strategy_versions.backtest_validity_methodology_version`.
