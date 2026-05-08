# Scoring Methodology

Authoritative spec for every numeric score in `india-monthly-alpha-engine`. All formulas in this document must be deterministic and computable from the point-in-time loader output (see `point_in_time_methodology.md`, forthcoming). No score in this document depends on data that was not available at `as_of_date`. No score uses LLM judgment as an input — LLMs may only populate evidence fields with citations, never produce numbers.

This document locks the six items below. Everything else (PIT loader, feature engines, deployment engine, backtester) is downstream.

1. Evidence Quality Score
2. Cohort Expected Alpha Score
3. Monthly Buy Score
4. Portfolio Edge Score and allocation rule
5. `thesis_status` definition
6. Replacement rule

A worked end-to-end example follows in §8. Items deferred to sibling docs are listed in §9.

## 1. Conventions

All scores are integers in [0, 100] unless stated otherwise.

`as_of_date` is the date at which the system is making a decision (live deployment day, or replay date in backtest).

A field is **PIT-available** at `as_of_date` if its `source_timestamp ≤ as_of_date`. For financial statements this means `announcement_date ≤ as_of_date`, never `period_end_date ≤ as_of_date`. For governance flags it means the structured filing or NLP extraction was published before `as_of_date`. The PIT loader enforces this; scoring code must not query raw history tables directly.

Forward returns referenced in calibration use 12-month forward total return relative to Nifty 500 TRI, computed from corporate-action-adjusted prices. Forward windows that extend past the last available price reduce calibration sample size; they do not invent data.

Benchmark for all excess-return computations: Nifty 500 TRI. (See `benchmark_methodology.md`.)

## 2. Evidence Quality Score (E_Q)

E_Q is a per-company score in [0, 100] that measures how reliable the data behind a candidate is. It enters the Monthly Buy Score (§4) as one sub-score and also as a multiplier on the final score, so weak evidence cannot ride solely on strong-looking factor values.

### 2.1 Formula

Start at 100 and apply the deductions below at `as_of_date`. Floor the result at 0.

- −10 if most-recent quarterly result `announcement_date` is older than 90 days from `as_of_date`.
- −10 if most-recent annual report is older than 270 days from `as_of_date`.
- −10 if any of {revenue, PAT, OCF, total debt, total assets} is missing for any of the last 4 reported quarters.
- −10 if any structured field used in scoring comes from a tier-3+ source (Screener / news / aggregator) rather than NSE / BSE / SEBI / audited annual report. Source tier order is locked in `data_sources.md`; default order: (1) NSE/BSE official filings, (2) SEBI disclosures, (3) audited annual report PDF, (4) structured third-party (Screener), (5) concall transcript, (6) news.
- −10 if conflicting values exist across sources for any structured field in the last 4 quarters and the conflict is not resolved by the source-tier rule.
- −15 if the cohort matched in §3 has 10–29 members (medium confidence).
- −30 if the cohort has fewer than 10 members (null cohort).
- −10 if any textual fact material to the investment case is LLM-extracted and not corroborated by a structured filing field (i.e., unverified).

### 2.2 Short-circuits

These rules override score arithmetic:

- E_Q < 20 → company is excluded from the candidate universe entirely. It cannot enter Monthly Buy Score ranking.
- E_Q < 40 AND any active textual-tier governance flag → flag is **not** treated as fatal automatically; instead the candidate is routed to `human_review_required = true` and held out of allocation pending review.
- E_Q ≥ 40 → all rules apply normally.

The E_Q multiplier on Monthly Buy Score is defined in §4.2.

## 3. Cohort Expected Alpha Score (CEA)

CEA estimates the historical forward-excess-return distribution for setups similar to the candidate. It is the only score that uses cross-sectional historical evidence; everything else in §4 is a present-time factor measurement.

### 3.1 Cohort matching dimensions

To avoid the factor-double-counting failure mode (the same fundamental factor entering once via cohort matching and again as a Monthly Buy Score sub-score, inflating its effective weight), cohort matching uses **only structural buckets**, not fundamental factor scores. Fundamental factors live in §4 sub-scores, not here.

Matching dimensions and bucket boundaries:

- **Market-cap bucket** (in INR crore at `as_of_date`):
  - large: ≥ 50,000
  - mid: 15,000 – 50,000
  - small: 2,000 – 15,000
  - micro: < 2,000
- **Sector bucket**: 11 buckets — financials, materials, energy, industrials, consumer_discretionary, consumer_staples, healthcare, IT, communications, utilities, real_estate. (NIC 1-digit equivalent; see `data_sources.md` for symbol-to-bucket map.)
- **Regime bucket** at `as_of_date` (from market_regime engine; minimal v1 definition):
  - bull: Nifty 500 above 200-DMA AND breadth (% of constituents above 200-DMA) > 60% AND 12-month vol percentile < 70.
  - bear: Nifty 500 below 200-DMA AND breadth < 40%.
  - neutral: otherwise.
- **Liquidity bucket** by 30-day average daily traded value:
  - high: ≥ ₹50 cr
  - mid: ₹5 cr – ₹50 cr
  - low: < ₹5 cr

Exact match required on all four buckets. No nearest-neighbour relaxation in v1.

### 3.2 Cohort universe

For a given `as_of_date`, candidate company `c`, and cohort buckets, the cohort universe is:

```
cohort = {
    (m, t) : m ∈ companies_active_at(t), t ∈ [as_of_date − 10y, as_of_date − 12m],
    bucket(m, t) == bucket(c, as_of_date),
    m != c
}
```

`companies_active_at(t)` must include companies that were later delisted, suspended, or merged out — survivor-only cohorts produce upward-biased forward-return estimates and are not allowed. The PIT loader's `get_companies_active_at(t)` and `delisted_companies_active_at(t)` are the union source.

The window ends at `as_of_date − 12m` because each cohort observation needs a complete 12-month forward return.

### 3.3 Cohort statistics

For each cohort observation `(m, t)`, compute 12-month forward total return for `m` from `t`, and 12-month forward Nifty 500 TRI return from `t`. Forward excess return is the difference.

For delisted cohort members, the forward return uses the realised proceeds (last traded price plus any liquidation distribution; if neither is available, the position is marked `−100%` for the unrecovered portion). This is conservative and necessary; ignoring delisting is the primary source of upward-biased "expected alpha" in retail backtests.

From the cohort excess-return distribution compute:

- median_12m_excess_return
- mean_12m_excess_return
- hit_rate (fraction with positive excess return)
- p25_12m_excess_return (downside)
- worst_decile_median_excess_return (tail)
- cohort_size = |cohort|

### 3.4 CEA score

```
CEA_raw = 50 + 250 × median_12m_excess_return
CEA_clipped = clip(CEA_raw, 0, 100)
```

So a median excess return of 0 → CEA 50, +10% → 75, +20% → 100, −10% → 25, −20% → 0.

Confidence cap by cohort size:

- cohort_size ≥ 30: no cap. Use `CEA_clipped` as-is.
- 10 ≤ cohort_size < 30: cap at 60. (`CEA_score = min(CEA_clipped, 60)`.) E_Q is also penalised −15.
- cohort_size < 10: `CEA_score = 0` and the candidate's E_Q penalty is −30. The candidate may still pass other gates, but its alpha case is not statistically supported.

Median is preferred over mean because forward-return distributions are right-skewed in equities. Mean is reported alongside but not used in the score.

## 4. Monthly Buy Score (MBS)

Monthly Buy Score is the per-candidate composite score that drives ranking. It uses the v2 master-plan weights as the v1 strategy; equal-weight is one of the champion-challenger strategies (see `backtest_validity_methodology.md`).

### 4.1 Sub-scores and weights

```
MBS_raw =
    0.20 × CEA_score
  + 0.15 × earnings_acceleration_score
  + 0.15 × business_quality_score
  + 0.15 × governance_safety_score        (structured tier only)
  + 0.12 × valuation_sanity_score
  + 0.08 × technical_confirmation_score
  + 0.05 × sector_tailwind_score
  + 0.05 × liquidity_score
  + 0.05 × evidence_quality_score
```

Each sub-score is an integer in [0, 100] computed by its named feature engine. Engine specifications are deferred to feature-engine docs but each must consume only PIT loader output and produce a deterministic score.

Note that `governance_safety_score` here is the **structured-tier** composite only (pledge %, debt/equity delta, CFO/PAT trend, receivables-vs-revenue delta, credit rating). Textual-tier governance issues are gates (§4.3), not score inputs.

### 4.2 Evidence-quality multiplier

```
E_Q_multiplier = 0.5 + 0.005 × E_Q
MBS_final = round(MBS_raw × E_Q_multiplier)
```

So E_Q = 100 → multiplier 1.0; E_Q = 50 → 0.75; E_Q = 0 → 0.5. This means a candidate with weak evidence cannot reach the top decile on factor values alone — it has at best 50% of its raw factor score.

### 4.3 Fatal governance overrides

If any **structured-tier** fatal flag is active for the candidate at `as_of_date`, then `MBS_final = 0`, the candidate is classified `reject`, and it cannot be allocated to. Structured fatals (deterministic) are listed in `governance_engine` spec and include: promoter pledge increase ≥ 20 percentage points within 6 months, credit rating downgrade ≥ 2 notches into speculative grade within 12 months, debt/equity increase > 1.0 absolute within 12 months coupled with operating cash flow decline, regulatory order in `severe` category from SEBI/RBI/exchange.

If any **textual-tier** fatal flag is active and E_Q ≥ 40, the flag is treated as fatal: `MBS_final = 0`, classification `reject`, human_review_status `confirmed`. If E_Q < 40, the candidate is held out for human review (see §2.2) — neither rejected automatically nor allocated.

This split is intentional. Structured deterministic detection is reliable enough to auto-reject. Textual NLP detection is not, and a single false positive can permanently exclude a good company; the human-review gate is the safety valve.

## 5. Portfolio Edge Score (PES)

PES is the system's allocation-level score: how much of the ₹25,000 monthly capital should go to active stocks vs. the index. It is computed once per month after all candidates' MBS_final values are known.

### 5.1 Formula

```
PES =
    0.30 × Active_Opportunity_Breadth
  + 0.25 × Top_Candidate_Quality
  + 0.15 × Evidence_Quality_TopN
  + 0.10 × Market_Regime_Support
  + 0.10 × Existing_Portfolio_Add_Opportunity
  + 0.10 × Risk_Cost_Penalty
```

All inputs are in [0, 100]. PES is rounded to the nearest integer.

### 5.2 Subcomponent definitions

**Active_Opportunity_Breadth** is a step function of the count of strong candidates, defined as candidates with `MBS_final ≥ 70` AND no fatal governance flag AND E_Q ≥ 40 AND not blocked by portfolio/sector caps.

```
0 strong candidates  → 0
1                    → 40
2 – 3                → 60
4 – 6                → 80
≥ 7                  → 100
```

**Top_Candidate_Quality** is the mean of `MBS_final` across the top 5 strong candidates by `MBS_final`. If fewer than 5 strong candidates, average over what exists; if zero, this subcomponent is 0.

**Evidence_Quality_TopN** is the mean E_Q across the same top 5 strong candidates, or 0 if none.

**Market_Regime_Support**:
- bull regime → 80
- neutral regime → 50
- bear regime → 20

(Bear is not 0 because some active opportunities — beaten-down quality at low valuations — are most attractive in bear regimes. The regime score caps how heavily the system swings into active, not whether it can.)

**Existing_Portfolio_Add_Opportunity** measures whether current holdings are themselves attractive add candidates. For each current holding `h` with `MBS_final(h)` and `position_pct(h)`:

```
add_score(h) =
    MBS_final(h)                           if position_pct(h) < cap_pct (= 10)
    0                                      otherwise
Existing_Portfolio_Add_Opportunity = mean(add_score(h)) over all holdings
```

If the portfolio is empty (cold start), return 50 to avoid biasing the system toward zero existing-add opportunity at cold start.

**Risk_Cost_Penalty** starts at 100 and applies the deductions below; floor at 0.

- −10 per holding above 18 active names (portfolio bloat)
- −10 if max single-stock position > 10% of portfolio
- −10 if max sector concentration > 25%
- −20 if rolling 12-month portfolio turnover > 100%
- −15 if any current holding has `thesis_status = broken` and exit has not been started

### 5.3 Allocation rule with safety floor

PES maps to allocation buckets per v2 §6, with one critical change: until holdout-validated calibration confirms the > 90 bucket is reliable, the index allocation is floored at 20% of monthly capital regardless of PES. ₹25,000 × 20% = ₹5,000.

| PES range | Index allocation | Active allocation |
|-----------|------------------|-------------------|
| ≤ 50      | ₹25,000          | ₹0                |
| 51 – 60   | ₹20,000          | ₹5,000            |
| 61 – 70   | ₹15,000          | ₹10,000           |
| 71 – 80   | ₹10,000          | ₹15,000           |
| 81 – 90   | ₹5,000           | ₹20,000           |
| > 90      | ₹5,000 (floor)   | ₹20,000           |

After holdout calibration shows the > 90 bucket has historically delivered positive forward excess return in at least N months with bootstrap CI lower bound > 0 (parameters locked in `backtest_validity_methodology.md`), the floor on the > 90 bucket can be lowered to 0. Until then, the floor stands.

### 5.4 Bucket calibration procedure

The bucket boundaries (50, 60, 70, 80, 90) are the v2 plan's asserted thresholds. They become **data-derived** through the procedure below, run on train + validation data only (not holdout).

For each month `t` in train + validation:

1. Compute `PES_t` and the active stock allocation that the system would have made.
2. Compute the realised 12-month forward portfolio return that resulted from that allocation (active stocks held, weighted by their target allocation; index portion gets Nifty 500 TRI).
3. Compute forward excess return vs. all-index allocation: `realised_portfolio_return − Nifty500TRI_return`.

Group months by PES bucket. For each bucket compute:
- mean forward excess return
- median forward excess return
- hit rate (fraction with positive excess return)
- 95% block-bootstrap CI on mean (block length 12, 10,000 resamples)

**Acceptance criterion**: mean forward excess return must be monotonically non-decreasing across buckets, AND the difference between the lowest bucket (≤ 50) and highest bucket (> 90) must have a bootstrap CI lower bound ≥ 0 on the validation set.

**If acceptance fails**:
- First, collapse adjacent non-monotonic buckets and re-test with the reduced bucketing.
- If 3-bucket aggregation also fails monotonicity, calibration fails. The system reverts to the conservative default: `PES > 50` → ₹20,000 index / ₹5,000 active; `PES ≤ 50` → ₹25,000 index. No further differentiation. Champion-challenger continues to search for a passing strategy.

The holdout window is **never** used for bucket selection or re-bucketing. Holdout is the final gate (see `backtest_validity_methodology.md`).

## 6. `thesis_status`

Defines when the system is permitted to exit, hold, or add to a current position. Computed per-holding at `as_of_date` from structured signals only.

### 6.1 broken (triggers exit)

A holding is `broken` if any of:

- Any active **structured-tier** fatal governance flag (per §4.3).
- Revenue YoY < −20% for 2 consecutive reported quarters.
- CFO / PAT < 0.3 for 4 consecutive reported quarters (rolling).
- Credit rating downgrade ≥ 2 notches into speculative grade (BB+ or below on CRISIL / ICRA / CARE / Fitch India scale) within last 12 months.
- Promoter pledge increase ≥ 20 percentage points within last 6 months.

Action: exit the position. Default exit cadence is 50% within 30 days, remainder within 60 days, to limit market impact and tax-cost concentration. The deployment engine treats a `broken` holding's exit proceeds as cash available for next month's allocation (subject to T+1 settlement; see deployment-engine spec).

### 6.2 weakening (triggers human review, no auto-action)

A holding is `weakening` if not `broken` AND any of:

- Revenue YoY < −10% for 2 consecutive reported quarters.
- CFO / PAT < 0.5 for 4 consecutive reported quarters.
- Credit rating downgrade of 1 notch into speculative grade, or 1 notch within speculative grade, within last 12 months.
- Promoter pledge increase 10 – 20 percentage points within last 6 months.
- Debt/equity increase > 0.5 absolute within last 12 months coupled with operating cash flow decline.
- Any active **textual-tier** governance flag pending human review (§4.3).

Action: hold. Do not add. Surface in monthly review report under "review required". No automatic exit.

### 6.3 intact

Otherwise. Eligible for adds per the deployment engine's allocation rules and position cap.

## 7. Replacement rule

The v2 master plan's `new_score > weakest_score` gate is replaced by an after-tax, after-cost expected-excess-return gate. Score-comparison alone ignores the tax wedge that destroys the edge on small portfolios.

A new candidate `n` may replace the weakest current holding `w` only if:

```
E[after_tax_after_cost_excess_return_12m(n)]
  > E[after_tax_after_cost_excess_return_12m(hold w)] + replacement_threshold(w)
```

Where:

```
E[after_tax_after_cost_excess_return_12m(X)] =
    CEA_median_excess_return_12m(X) × (1 − tax_rate(X))
  − round_trip_cost_pct(X)
```

`tax_rate(X)`:
- 20% if X is a new buy (replacement triggers exit of `w` whose holding period determines the tax on the existing leg). For the new leg, model 20% prospectively (most conservative; assumes ≤12m hold).
- For the **existing leg** of the swap (selling `w`): 20% if `w` has been held < 12 months; 12.5% (above the ₹1.25L per-FY threshold; assume met for replacement decisions, conservative) if ≥ 12 months.

`round_trip_cost_pct(X)` from `cost_tax_methodology.md` (forthcoming). Placeholder: 0.4% on liquid mid/large names; 0.8% on small/micro/illiquid.

`replacement_threshold(w)`:
- 4.0 percentage points if `w` is held < 12 months (STCG path; high tax wedge).
- 1.5 percentage points if `w` is held ≥ 12 months (LTCG path).

Rationale: STCG at 20% on a typical 12-month gain of ~15% costs ~3 percentage points of the active edge. The replacement candidate must clear that wedge plus a buffer for cost and uncertainty before the swap is justified.

If `n` does not clear the threshold, the deployment engine prefers (in order): adding to existing `intact` holdings under cap, allocating to index, holding cash.

## 8. Worked example

Hypothetical company **X Ltd** at `as_of_date = 2024-06-30`.

Inputs from PIT loader and feature engines:

- Market cap: ₹35,000 cr → bucket `mid`.
- Sector: consumer_discretionary.
- Regime at 2024-06-30: Nifty 500 above 200-DMA, breadth 55%, vol percentile 50 → `neutral`.
- Liquidity: 30-day ADV ₹40 cr → `mid` (below the ₹50 cr cutoff for `high`).
- Cohort match: mid + consumer_discretionary + neutral + mid liquidity, lookback 2014-06-30 to 2023-06-30 (window ends 12m before as_of_date).
- Cohort size: 47 (≥ 30, no confidence cap, no E_Q penalty).
- Cohort median 12m excess return vs Nifty 500 TRI: +6.2%.

CEA: `50 + 250 × 0.062 = 65.5` → 65.

Sub-scores (from feature engines):

- earnings_acceleration_score: 75
- business_quality_score: 70
- governance_safety_score (structured): 85
- valuation_sanity_score: 55
- technical_confirmation_score: 70
- sector_tailwind_score: 60
- liquidity_score: 75 (mid liquidity → 75)
- evidence_quality_score: 100 (computed below)

E_Q computation:
- Latest quarterly: Q4FY24 announced 2024-05-22, 39 days before as_of_date — no penalty.
- Latest annual report: FY23 audit, ~10 months old — no penalty.
- All five core fields present last 4 quarters — no penalty.
- All structured fields from BSE filings (tier 1) — no penalty.
- No conflicts — no penalty.
- Cohort size 47 ≥ 30 — no penalty.
- No unverified textual facts — no penalty.
- E_Q = 100. (`evidence_quality_score` in §4.1 is the same value.)

Recompute MBS:

```
MBS_raw =
    0.20 × 65   = 13.0
  + 0.15 × 75   = 11.25
  + 0.15 × 70   = 10.5
  + 0.15 × 85   = 12.75
  + 0.12 × 55   =  6.6
  + 0.08 × 70   =  5.6
  + 0.05 × 60   =  3.0
  + 0.05 × 75   =  3.75
  + 0.05 × 100  =  5.0
  =                71.45
```

E_Q_multiplier = `0.5 + 0.005 × 100 = 1.0`.

`MBS_final = round(71.45 × 1.0) = 71`.

Now assume the system has 12 candidates this month with `MBS_final` values [78, 74, 71 (X Ltd), 68, 65, 62, 58, 55, 52, 48, 42, 38] after fatal-flag filtering.

Strong candidates (`MBS_final ≥ 70`): {78, 74, 71} → count = 3 → Active_Opportunity_Breadth = 60.

Top 5 by MBS_final: [78, 74, 71, 68, 65]. Top_Candidate_Quality = mean = 71.2 → 71.

Top 5 mean E_Q (assume similar): 92.

Market_Regime_Support: neutral → 50.

Existing portfolio: 14 holdings, all intact, mean MBS_final 60, all positions < 10%. Existing_Portfolio_Add_Opportunity = mean(MBS_final(h)) over addable = 60.

Risk_Cost_Penalty: 14 holdings (≤ 18, no penalty), max position 8% (no penalty), max sector 22% (no penalty), turnover 35% (no penalty), no broken thesis. = 100.

```
PES =
    0.30 × 60   = 18.0
  + 0.25 × 71   = 17.75
  + 0.15 × 92   = 13.8
  + 0.10 × 50   =  5.0
  + 0.10 × 60   =  6.0
  + 0.10 × 100  = 10.0
  =                70.55 → 71
```

PES = 71 → bucket 71–80 → ₹10,000 index, ₹15,000 active.

The ₹15,000 active gets allocated across the top strong candidates. X Ltd at MBS_final = 71 ranks third; allocation engine assigns roughly proportional weights with a position cap (₹2,500–₹5,000 initial). X Ltd target = ₹4,000 at price ₹2,800 = 1 share = ₹2,800 actual. Residual ₹1,200 spills to next-best candidate or to the index per deployment-engine residual rule.

End-to-end consistent. Every number is a function of PIT loader output and the formulas above.

## 9. Open questions deferred to sibling docs

These items are referenced by the methodology but not locked in this document. Each must be locked before the corresponding feature engine is built.

1. **Index instrument cutover rule** (Nifty 500 index fund SIP vs. NIFTYBEES ETF, threshold typically ₹5,000) — `benchmark_methodology.md`.
2. **Slippage and bid-ask cost model parameters** — `cost_tax_methodology.md`. Placeholder: half-spread max(₹0.05, 0.05% of trade value) for liquid; 2–5× for illiquid.
3. **T+1 settlement modelling** for replacement buys (fill price assumption, cash gap handling) — deployment-engine spec.
4. **Restated filings / `as_known_at` semantics** for the PIT loader — `point_in_time_methodology.md`.
5. **Automated data refresh sources** (NSE bhavcopy, BSE corp-actions feed) and update cadence — `data_sources.md`.
6. **Multiple-testing correction** for champion-challenger holdout (Bonferroni vs. pre-registered single strategy) — `backtest_validity_methodology.md`.
7. **Style-aware benchmark attribution** (decompose portfolio return into Nifty 500 TRI + style tilt + selection alpha) — `backtest_validity_methodology.md`.
8. **DB engine choice** (recommended: SQLite for OLTP + DuckDB for analytics) — `architecture.md`.

## 10. Dependencies

This document depends on, and must be re-validated against, the following sibling docs as they are written:

- `point_in_time_methodology.md`: defines what "PIT-available" means and how `as_known_at` handles restatements.
- `benchmark_methodology.md`: locks Nifty 500 TRI, secondary benchmarks, and the index instrument used in real deployment.
- `cost_tax_methodology.md`: locks the cost/tax model that feeds §7's replacement rule.
- `backtest_validity_methodology.md`: locks the calibration / promotion / holdout procedure that turns the §5.4 acceptance criterion into a runnable test.
- `data_sources.md`: locks source-tier ordering used in §2.1 deductions.

Changes to any of these may force changes here. This document is versioned alongside `strategy_versions.scoring_methodology_version`.
