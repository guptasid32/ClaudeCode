# Benchmark Methodology

Authoritative spec for benchmarks, the index instrument used in real deployment, the construction of style factors used by the backtest validity layer, and the inflation sensitivity report. The system's alpha claims are made against this benchmark; if the benchmark is wrong, the claims are wrong.

This document depends on `scoring_methodology.md` (Edge Score allocation rule references the index allocation) and on `backtest_validity_methodology.md` (style attribution requires the factor construction defined here).

## 1. Conventions

A **benchmark** is the index series against which the system's portfolio returns are compared. The **index instrument** is the actual product the system buys when the deployment engine allocates to "index" — the two are conceptually distinct: the benchmark is a return series for measurement; the instrument is a purchasable product with its own TER and frictions.

All return computations use total-return (TRI) variants of the underlying indices. Price-only (PRI) variants are not used because a direct-stock portfolio reinvests dividends; comparing it to PRI undercounts the benchmark and overstates the system's alpha.

## 2. Primary benchmark: Nifty 500 TRI

The system's primary benchmark is the **NSE Nifty 500 Total Return Index** (TRI). All headline alpha claims, validity tests, and bucket-calibration outcomes use this series.

Rationale: Nifty 500 covers the top 500 NSE-listed companies by free-float market cap, representing roughly 95% of total NSE market cap. It is the broadest Indian-equity benchmark with reliable TRI history and a tradeable index product. Nifty 50 is too narrow (over-indexes to large-cap financials and IT), and BSE Sensex / BSE 500 are less commonly used as performance benchmarks in practice.

The TRI variant must be used; PRI is rejected per §1. Code-level assertion: every comparison function takes a benchmark identifier as input and fails loudly if the identifier is not exactly `"NIFTY_500_TRI"`. Mistyped or substitute benchmarks are bugs, not silent fallbacks.

## 3. Secondary benchmarks for style-drift checks

When the active book deviates materially from Nifty 500 weights, the headline Nifty 500 TRI comparison can over- or under-state alpha through pure style drift. The system reports against the closest secondary benchmark whenever drift exceeds the threshold in §4.

Secondary benchmarks (all TRI):
- **Nifty 50 TRI**: large-cap. Use as the secondary when the active book is ≥ 70% large-cap (companies with market cap ≥ ₹50,000 cr per `scoring_methodology.md` §3.1).
- **Nifty Midcap 150 TRI**: mid-cap. Use when the active book is ≥ 50% mid-cap.
- **Nifty Smallcap 250 TRI**: small-cap. Use when the active book is ≥ 30% small-cap.

These thresholds are conservative (Nifty 500 holds ≈ 12% small-cap by weight; 30% in the active book is meaningful drift). The thresholds are recorded in `strategy_versions.benchmark_methodology_version` and are revised only by a methodology version bump.

## 4. Style-aware blended benchmark

When the active book's market-cap composition diverges from Nifty 500 by more than 10 percentage points in any cap bucket, the system additionally constructs a **blended benchmark**: a portfolio of Nifty 50 TRI, Nifty Midcap 150 TRI, and Nifty Smallcap 250 TRI weighted to match the active book's cap distribution at each rebalance.

The blended benchmark is reported alongside Nifty 500 TRI, not in place of it. The Nifty 500 TRI comparison remains the headline; the blended comparison is a sanity check that the alpha is from selection, not from a passive size tilt.

The 10 percentage-point drift threshold is checked monthly. When triggered, the blended benchmark is reconstructed each month using that month's actual cap composition. The blend weights and the resulting blended return are stored alongside the strategy's monthly return in the backtest report.

## 5. Index instrument cutover (closes scoring §9 item 1)

The instrument the deployment engine actually buys for the index leg of the monthly allocation depends on the rupee amount allocated:

- **Allocations < ₹5,000**: Nifty 500 index fund SIP (direct plan; TER ≈ 0.20% annualised).
- **Allocations ≥ ₹5,000**: Nifty 500 ETF (TER ≈ 0.05% annualised).

Rationale: index funds accept any rupee amount and execute at end-of-day NAV; they are friction-free for small tickets but carry higher TER and a 1-year exit load. ETFs require whole units (typically ₹100–₹500 per unit, so a ₹5,000 ticket buys ~10–50 units), trade intraday with bid-ask, but have lower TER and no exit load. At ₹5,000 the ETF's TER advantage starts to outweigh the bid-ask cost on a ~12-month hold.

Canonical Nifty 500 ETF: **Motilal Oswal Nifty 500 ETF** or **ICICI Prudential Nifty 500 ETF** (both track Nifty 500; the deployment engine picks the one with higher AUM and tighter spread at the time of trade). NIFTYBEES tracks Nifty 50, not Nifty 500, and is not used as the Nifty 500 ETF — this is a common confusion that the code must avoid via explicit instrument identifiers.

Canonical Nifty 500 index fund: a direct-plan Nifty 500 index fund (specific scheme deferred to `data_sources.md` once AUM and tracking-error stats are gathered). Until then the simulator uses a generic 0.20% TER assumption.

Costs for these instruments are documented in `cost_tax_methodology.md` §11.

## 6. Risk-free rate proxy (closes backtest §13 item 4)

The risk-free rate used in the MKT factor (per `backtest_validity_methodology.md` §9.1) and any Sharpe-style metric is the **91-day T-bill auction yield published by RBI**, sampled monthly.

Rationale: the 91-day T-bill is the canonical short-term sovereign rate in India, has consistent auction history, and is short enough to function as a near-risk-free proxy without being noisy. The overnight rate (call money / repo) is too short and reflects intraday liquidity stresses that are not relevant for monthly returns; the 364-day T-bill is too long for the "risk-free" intuition.

Conversion: the auction yield is published as an annualised yield. The simulator converts to a monthly rate as `(1 + annual_yield) ^ (1/12) − 1`.

This locks the open question in `backtest_validity_methodology.md` §13 item 4. The text of `backtest_validity_methodology.md` §9.1 currently says "overnight T-bill rate"; this is corrected to "91-day T-bill" via the patch documented in the consolidated review.

## 7. SMB factor (closes backtest §13 item 3)

**SMB (Small-Minus-Big)** is computed as the monthly difference:

```
SMB_t = NiftySmallcap250_TRI_return_t − Nifty100_TRI_return_t
```

Rationale: this is a replicable, externally-quoted factor using NSE-published indices. A custom decile-spread construction would require maintaining a market-cap sort within Nifty 500 each month, with sector / liquidity filters, and would degrade to ~50 names per decile — statistically thin and operationally fragile. The Nifty Smallcap 250 minus Nifty 100 spread captures the same size effect using indices NSE already maintains and publishes daily.

This locks the open question in `backtest_validity_methodology.md` §13 item 3.

## 8. HML factor

**HML (High-Minus-Low book-to-market)** is computed within the Nifty 500 universe at each annual rebalance:

1. At end of October each year, sort all Nifty 500 constituents by book-to-market ratio. Book value is from the latest available annual report at the rebalance date (must be PIT-available per `point_in_time_methodology.md`); market cap is at the rebalance close.
2. Form **terciles** (top 33%, middle 33%, bottom 33% by B/M).
3. The HML factor return for each subsequent month until the next rebalance is the equal-weighted return of the top tercile minus the equal-weighted return of the bottom tercile.

Rebalance cadence: annual, October. Indian companies report annual results around July–September; an October rebalance ensures the most recent FY data is available.

Tercile (not decile) granularity rationale: deciles within Nifty 500 yield ~50 names per bucket, and after sector / liquidity filters the count drops further; tercile spreads are statistically more stable. This is a deliberate departure from the Fama-French US convention.

The text of `backtest_validity_methodology.md` §9.1 currently says "deciles" for HML; this is corrected to "terciles" via the patch documented in the consolidated review.

## 9. MOM factor

**MOM (Momentum)** is computed within the Nifty 500 universe each month:

1. At each month-end, sort all Nifty 500 constituents by their **12-1 month return**: total return from `t-13 months` to `t-1 month`, skipping the most recent month to avoid short-term reversal.
2. Form terciles.
3. The MOM factor return for the next month is the equal-weighted return of the top tercile minus the bottom tercile.

Rebalance cadence: monthly. The 1-month skip is the standard adjustment and matches the academic convention.

Tercile rationale matches §8.

The text of `backtest_validity_methodology.md` §9.1 currently says "deciles" for MOM; this is corrected to "terciles" via the same patch.

## 10. Benchmark return data sources

- **Nifty 500 TRI, Nifty 50 TRI, Nifty Midcap 150 TRI, Nifty Smallcap 250 TRI, Nifty 100 TRI**: NSE Indices daily close files (TRI series) published at niftyindices.com. Loaded into the database with daily granularity; the monthly return series is derived.
- **91-day T-bill yield**: RBI's weekly auction results, sampled to monthly.
- **CPI Combined - All India**: Ministry of Statistics and Programme Implementation (MoSPI), monthly publication.

Backup sources are deferred to `data_sources.md` for full discussion. The PIT loader treats these reference series like any other PIT-available data: prices and yields are filtered by trade_date / publication_date ≤ as_of_date.

## 11. Index reconstitution treatment

NSE rebalances Nifty 500 semi-annually (March and September). When constituents change:

- The TRI series produced by NSE is continuous through the change; no adjustment on the benchmark side.
- The active book's universe at each rebalance date uses the constituents *as of that date*, retrieved via `get_index_constituents_as_of(index_name='NIFTY_500', as_of_date=t)` from the PIT loader. Projecting today's constituents backward is forbidden (per `backtest_validity_methodology.md` §3).

The same rule applies to Nifty 50, Nifty Midcap 150, Nifty Smallcap 250, and Nifty 100 when used as comparison benchmarks: their TRI series are continuous; their constituent membership at any date is PIT-resolved.

## 12. Code-level assertions

- The benchmark identifier in any comparison function must equal `"NIFTY_500_TRI"` exactly. Mismatched identifiers must fail loudly with a `BenchmarkMismatchError`.
- The cost model applied to the benchmark side of a comparison must match the **instrument** chosen by the cutover rule (§5): TER ≈ 0.20% for the index fund, TER ≈ 0.05% for the ETF, plus per-tranche cost as specified in `cost_tax_methodology.md` §11. Setting TER to zero on the benchmark side is forbidden.
- The blended benchmark (§4) is computed at each rebalance from actual cap weights; the simulator must not cache it across rebalances when cap composition changes.

## 13. Inflation-adjustment sensitivity

The headline numbers in every backtest report are **nominal**. CPI-deflated ("real") returns are reported as a sensitivity analysis. Both nominal and real are deflated identically on the benchmark and the active sides; the active-vs-benchmark gap is invariant to the deflator, but the absolute return levels are not.

The deflator is **CPI Combined - All India** (MoSPI monthly series). Real returns are computed as:

```
real_monthly_return = (1 + nominal_monthly_return) / (1 + cpi_monthly_inflation) − 1
```

Real CAGR, real max drawdown, and real Sharpe are reported alongside the nominal versions in the backtest report (per `backtest_validity_methodology.md` §11).

The inflation-adjusted variant of the SIP itself (₹25,000 nominal per month vs. CPI-scaled ₹25,000) is also reported as a sensitivity, since over a 10-year window the real value of a fixed-rupee SIP halves.

## 14. Open questions deferred to sibling docs

1. **Specific Nifty 500 index fund scheme to use** (UTI, Motilal Oswal, ICICI Prudential, etc.) including AUM and tracking error — `data_sources.md`.
2. **Specific Nifty 500 ETF instrument and ISIN** including historical AUM and bid-ask — `data_sources.md`.
3. **Exit-load schedule for the chosen index fund** — `cost_tax_methodology.md`.
4. **NSE TRI file ingestion paths** (URL patterns, file format, refresh cadence) — `data_sources.md`.
5. **Possible future migration to Nifty Total Market Index** (broader than Nifty 500) once liquidity and product availability mature — open methodology question.
6. **Risk-free rate alternative for periods predating reliable RBI 91-day T-bill series** — defer; the train window starts 2012 and RBI auction data is reliable through this period.

## 15. Dependencies

This document is referenced by:

- `scoring_methodology.md` (Portfolio Edge Score allocation buckets reference the index allocation; the instrument used at execution is determined here).
- `backtest_validity_methodology.md` (the 4-factor style attribution depends on the SMB / HML / MOM construction defined here; the headline alpha claim is against the benchmark defined here).
- `cost_tax_methodology.md` (instrument-side TER and STT differ between fund and ETF).
- `data_sources.md` (NSE TRI file paths, RBI T-bill source, MoSPI CPI source).

Changes to this document force a `benchmark_methodology_version` bump on `strategy_versions` and re-run of all backtests because the benchmark series changes the alpha computation.
