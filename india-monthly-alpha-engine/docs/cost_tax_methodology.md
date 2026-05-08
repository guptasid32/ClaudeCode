# Cost and Tax Methodology

Authoritative spec for transaction costs, slippage, and the date-aware tax regime used by the simulator and the replacement rule. Tickets in this system are small (₹2,500–₹10,000), so cost and tax drag is material relative to expected alpha. This document operationalises every per-rupee friction the system models.

This document is referenced by `scoring_methodology.md` §7 (replacement rule), `backtest_validity_methodology.md` §5 (gross / net reporting), §10.3 (cost-drag test), and §10.7 (tax-lot correctness test).

## 1. Conventions and scope

All costs and taxes apply to long-only delivery-based cash equity transactions. The system does not model intraday, F&O, margin-funded, or short-sell costs. Charges for the index instrument (mutual fund SIP or ETF) are documented separately in §11.

Every cost component is a function of (trade side, trade value, trade date, instrument). The complete cost of a trade is the sum of components. Costs are deducted from cash at trade settlement (T+1 for cash equity); taxes are realised on sells and accumulated in the tax ledger for FY-level computation.

The simulator must report gross, net-of-cost, and net-of-cost-and-tax results separately (per `backtest_validity_methodology.md` §5). Net-of-cost-and-tax is the headline.

## 2. Direct equity transaction-cost components

### 2.1 STT (Securities Transaction Tax)

For delivery-based cash equity (post-2013):
- Buy: 0.10% of trade value.
- Sell: 0.10% of trade value.

Historical regime: pre-1-June-2013, STT on delivery was 0.125% per side. The simulator must apply the historical rate when the trade date falls in that window. Pre-1-October-2004 STT did not exist, but this is irrelevant since the backtest train window starts 2012-01-01.

STT is a transaction tax, not part of brokerage; GST does not apply to STT.

### 2.2 Stamp duty

Post-1-July-2020 (uniform Indian rate): 0.015% on buy side only.

Pre-1-July-2020: stamp duty was state-dependent and varied by exchange and state of investor. The simulator simplifies to a flat 0.01% buy-side rate for trades pre-1-July-2020. This simplification is documented as a known approximation; the magnitude of error is < 0.005% per round trip and well within the cost-drag test tolerance.

Stamp duty does not apply to sells. GST does not apply to stamp duty.

### 2.3 Exchange transaction charges

NSE: 0.00297% per side of trade value.
BSE: 0.00375% per side of trade value.

The simulator uses the NSE rate as the default since most backtest names are NSE-listed. If a security is BSE-only at a given `as_of_date`, the BSE rate applies. Both rates are post-2023 figures; minor historical variations are absorbed within the cost-drag test tolerance.

### 2.4 SEBI charges

₹10 per crore per side, equivalently 0.0001% of trade value. Applies to all trades on NSE and BSE.

### 2.5 GST

18% on (brokerage + exchange transaction charges + SEBI charges). GST does NOT apply to STT or stamp duty.

### 2.6 Brokerage

Configurable. Two switchable models:

- **`zero_delivery`** (default for v1): ₹0 brokerage on delivery trades. This matches Zerodha and several other discount brokers as of 2026.
- **`discount_capped`**: ₹20 or 0.03% of trade value, whichever is lower, per executed order. Matches the prior generation of discount brokers.

The active model is recorded in `cost_model_version` on `strategy_versions`. Two backtests under different models are not directly comparable.

### 2.7 DP charges

CDSL: ₹13.5 per ISIN per day for sells. Applies once per ISIN per day regardless of quantity sold.
NSDL: ₹13.0 per ISIN per day (typical; the exact figure varies marginally by DP).

The simulator uses CDSL ₹13.5 as the default. DP charges apply only on sell-side and are independent of trade value. On a ₹5,000 sell ticket, DP charge alone is 0.27% — material relative to the overall cost stack.

The default DP charge can be replaced by an alternate value via `cost_model_version`. Surcharge and cess on DP charges are intentionally not modelled in v1; the omission is noted as a small approximation.

## 3. Slippage model

Slippage at small ticket sizes (₹2,500–₹10,000) is dominated by half-spread, not market impact. The simulator models half-spread per side, scaled by the candidate's liquidity bucket from `scoring_methodology.md` §3.1.

- **High liquidity** (30-day ADV ≥ ₹50 cr): half-spread per side = max(₹0.05, 0.05% of trade value).
- **Mid liquidity** (₹5–50 cr ADV): half-spread per side = max(₹0.10, 0.10% of trade value).
- **Low liquidity** (< ₹5 cr ADV): half-spread per side = max(₹0.25, 0.25% of trade value).

Slippage is added to the buy price and subtracted from the sell price. A round-trip slippage cost is therefore 2× the per-side figure.

Low-liquidity names should generally be avoided per `scoring_methodology.md` §11; the simulator includes the slippage rule for completeness, not as an endorsement of trading them.

## 4. Round-trip cost worked examples

These ground the placeholders in `scoring_methodology.md` §7. The placeholders there (0.4% liquid, 0.8% illiquid) are too low for typical ticket sizes once DP charges are included. This document supersedes the §7 placeholders.

### 4.1 Liquid mid/large name, ₹5,000 ticket, NSE, post-2024-07-23

- STT: 0.10% buy + 0.10% sell = 0.20%.
- Stamp duty: 0.015% buy = 0.015%.
- Exchange: 2 × 0.00297% = 0.006%.
- SEBI: 2 × 0.0001% = 0.0002%.
- GST on (brokerage + exchange + SEBI): brokerage 0 (zero_delivery model) → GST on (0 + ₹0.30 + ₹0.01) per side = negligible. ≈ 0.001%.
- Brokerage: 0 (zero_delivery model).
- DP charge (sell): ₹13.5 / ₹5,000 = 0.27%.
- Slippage: 2 × max(₹0.05, 0.05% × ₹5,000) = 2 × ₹2.50 = ₹5.00 = 0.10%.

Round-trip total ≈ 0.59%. With brokerage at the discount_capped model (₹20 + ₹20 = ₹40 round trip = 0.80% on ₹5,000), round-trip total ≈ 1.39%.

### 4.2 Small/illiquid name, ₹3,000 ticket

- STT: 0.20%.
- Stamp duty: 0.015%.
- Exchange: 0.006%.
- SEBI: 0.0002%.
- DP charge (sell): ₹13.5 / ₹3,000 = 0.45%.
- Slippage: 2 × 0.25% = 0.50%.

Round-trip total ≈ 1.17% before brokerage. With discount_capped, add 1.33% → 2.50%. With zero_delivery, stays at ≈ 1.17%.

### 4.3 Resulting placeholder revisions for `scoring_methodology.md` §7

Realistic round-trip costs:
- Liquid mid/large: 0.6% (zero_delivery, ≥ ₹5k ticket) to 1.4% (discount_capped, smaller tickets).
- Small/illiquid: 1.5% (zero_delivery) to 2.5% (discount_capped, smallest tickets).

The §7 placeholders of 0.4% / 0.8% are revised upward. The replacement-rule LTCG threshold of 1.5pp in §7 is also too low: the realistic LTCG-path wedge is roughly 2.9pp (1.0% liquid round-trip cost + 12.5% LTCG on a ~15% notional 12-month gain ≈ 1.9pp tax wedge, total ~2.9pp). The threshold must be raised to 3.0pp. The 4pp STCG threshold barely clears the realistic ~4.4pp wedge (1.0% cost + 20% STCG on 17% gain ≈ 3.4pp tax + 1.0% cost = ~4.4pp); leave 4pp as the gate but treat it as tight.

## 5. Date-aware tax regime

The simulator selects the regime based on the **realisation date** (sell date), not the buy date. Three windows:

### 5.1 Pre-1-April-2018

LTCG on listed equity (holding period ≥ 12 months): 0% (exempt under section 10(38) at the time).
STCG on listed equity (holding period < 12 months): 15%.

### 5.2 1-April-2018 to 23-July-2024

LTCG: 10% on realised gains above ₹1,00,000 per FY (no indexation for listed equity post-2018).
STCG: 15%.

The grandfather rule for pre-31-January-2018 acquisitions is implemented: for shares acquired before 31-Jan-2018 and sold post-1-April-2018, the cost basis is max(actual cost, fair market value as of 31-Jan-2018) for LTCG calculation. The simulator stores `pre_grandfather_fmv` on `portfolio_lots` for any lot acquired before 31-Jan-2018.

### 5.3 Post-23-July-2024 (Finance Act 2024)

LTCG: 12.5% on realised gains above ₹1,25,000 per FY (no indexation).
STCG: 20%.

### 5.4 Holding period

Holding period is computed per lot (`portfolio_lots`) at sale date as `(sale_date − acquisition_date).days`. Threshold for LTCG/STCG classification is 365 days.

### 5.5 Surcharge and cess

Surcharge (10% / 15% / 25% / 37% based on income slab) and cess (4% on tax + surcharge) are intentionally not modelled in v1. The simulator's tax computation is the base rate only. This is a known approximation; for users in the 30% slab with high-income surcharge, the actual after-tax wedge is somewhat larger. Document this as a limitation; users in those brackets should mentally inflate the tax drag by ~15–25% relative.

## 6. FIFO tax-lot accounting

`portfolio_lots` is the source of truth for cost basis. Each buy creates a lot with `(symbol, company_id, quantity, acquisition_date, cost_per_share, total_cost, source_action_id)`.

Sells consume lots in FIFO order: oldest `acquisition_date` first. FIFO is the default deemed assumption under Indian tax law when specific identification is not declared in the ITR; the system sticks to it for reproducibility and audit simplicity.

For each lot consumed by a sell:
1. Compute realised gain: `(sale_price_per_share − cost_per_share) × quantity_consumed`.
2. Determine holding period from `acquisition_date` to `sale_date`.
3. Classify as STCG (< 365 days) or LTCG (≥ 365 days).
4. Apply the regime active on the sale date (§5).

LTCG exemption tracking: the simulator maintains a per-FY (April 1 – March 31) running total of cumulative LTCG. Tax is applied only to the excess over the exemption (₹1,00,000 pre-23-Jul-2024, ₹1,25,000 post-). Exemption resets at FY boundary.

The cost-basis adjustment for splits, bonuses, rights, and demergers (per `backtest_validity_methodology.md` §4.1) updates `cost_per_share` and `quantity` on the affected lots without changing `acquisition_date` (per Indian tax convention).

## 7. Replacement-rule cost calculation

Operationalises `scoring_methodology.md` §7. The "after_tax_after_cost_excess_return" calculation:

```
E[after_tax_after_cost_excess_return_12m(X)] =
    CEA_median_excess_return_12m(X) × (1 − tax_rate(X))
  − round_trip_cost_pct(X)
```

where:

- `CEA_median_excess_return_12m(X)` is from the cohort engine.
- `tax_rate(X)`: 20% if X is a hypothetical new buy (assume ≤12m hold prospectively, conservative); for the existing leg of the swap (selling weakest holding `w`), 20% if `w` was held < 12m at the swap date, 12.5% above the FY exemption otherwise (assume exemption met for replacement decisions, conservative).
- `round_trip_cost_pct(X)` from §4: 0.6% liquid / 1.5% small-illiquid as the working defaults under zero_delivery; the simulator uses the actual figures per the cost model.

The replacement gate is:

```
E[after_tax_after_cost_excess_return_12m(new)]
  > E[after_tax_after_cost_excess_return_12m(hold w)] + replacement_threshold(w)
```

Thresholds (revised from `scoring_methodology.md` §7):
- 4.0pp if `w` is held < 12 months (STCG path, high tax wedge).
- 3.0pp if `w` is held ≥ 12 months (LTCG path; revised from 1.5pp).

## 8. Cost-drag analytical estimate

Operationalises `backtest_validity_methodology.md` §10.3.

Analytical formula:

```
cost_drag_annual ≈ annual_turnover × average_round_trip_cost
tax_drag_annual ≈ realised_gain_fraction × effective_tax_rate
total_drag ≈ cost_drag_annual + tax_drag_annual
```

Where:
- `annual_turnover` = (sum of trade values over year) / average portfolio NAV over year.
- `average_round_trip_cost` = weighted by liquidity bucket of trades; expect 0.7–1.0% under zero_delivery.
- `realised_gain_fraction` = (sum of realised gains over year, gross of tax) / average portfolio NAV.
- `effective_tax_rate` = weighted blend of STCG 20% and LTCG 12.5% based on lot holding periods at realisation.

The cost-drag test runs the backtest twice (zero-cost / full-cost) and compares the drag to this analytical estimate. Tolerance: ±20% relative on the total drag figure. Larger mismatch indicates either the cost model is misapplied or the tax-lot accounting is broken; promotion is blocked until reconciled.

## 9. `cost_model_version`

Recorded on `strategy_versions`. Increments on any change to:
- Brokerage assumption (zero_delivery vs discount_capped vs other).
- Slippage model (half-spread coefficients per liquidity bucket).
- DP charge values.
- STT / stamp duty / exchange / SEBI / GST rate corrections.
- The historical regime cutover dates (e.g., a discovered correction to the pre-2013 STT rate).

Two backtests under different cost_model_version are reported separately.

## 10. `tax_model_version`

Recorded on `strategy_versions`. Increments on any change to:
- Regime cutover dates (e.g., post-2024-07-23).
- Tax rates (STCG 15→20%, LTCG 10→12.5%).
- Exemption thresholds (₹1,00,000 → ₹1,25,000).
- Grandfather rule implementation.
- FIFO vs alternative lot consumption rule.

## 11. Index-instrument costs

The buy side of the index allocation is either a Nifty 500 index fund SIP or a Nifty 500 ETF, per `benchmark_methodology.md` cutover rule. Costs differ.

### 11.1 Index fund SIP (default for allocations < ₹5,000)

- TER (expense ratio): ~0.20% annualised, deducted from NAV daily. Modelled as a continuous drag on the index leg.
- STT: not applicable to mutual fund unit purchases.
- Exit load: typically 1.0% if redeemed within 1 year of allocation, 0% after. Per-tranche tracked.
- DP charge: not applicable (units held in folio, not demat).
- Stamp duty: 0.005% on units allotted (regulatory minimum).
- Brokerage: 0 (direct mutual fund route).

Tax treatment on redemption follows the same equity-MF regime as listed equity (STCG 20% < 12m post-2024-07-23, LTCG 12.5% above ₹1.25L per FY).

### 11.2 Index ETF (default for allocations ≥ ₹5,000)

- Expense ratio: ~0.05% annualised (lower than the index fund).
- STT: 0.001% on buy and 0.025% on sell (different from cash equity rates; ETFs are taxed at the lower regime).
- Stamp duty: 0.015% on buy (same as cash equity).
- Exchange / SEBI / GST: same as cash equity.
- Brokerage: per the active brokerage model.
- DP charge: applicable (₹13.5 per ISIN per day on sell).
- No exit load.

Tax treatment on sell follows the listed-equity regime.

The cost differential matters at the cutover threshold: at ₹5,000 ticket, the ETF route saves ~0.15% annualised on TER but pays the DP charge on sell. The fund route avoids DP and brokerage but pays a higher TER and a 1-year exit load.

## 12. T+1 settlement

Cash equity in India settles T+1. A sell on day T frees cash for trading on T+1. Replacement-rule trades that fund a buy from a sell cannot execute the buy on the same day at the same price; the simulator must enforce the gap.

Rule:
- Sell `w` on day T at the day-T close.
- Cash from the sell is available on T+1.
- Buy `n` on T+1 at the T+1 open or VWAP (specified in deployment-engine spec; default T+1 open).

The simulator records both legs as separate trades with different settlement dates. The cost stack applies to each leg independently. The price gap between T close and T+1 open is realised as part of the natural execution cost; it is not modelled as additional slippage (it is what happens, not a model parameter).

## 13. Open questions deferred to sibling docs

1. **Exact ETF instrument for Nifty 500 ETF route**: Motilal Oswal Nifty 500 ETF vs ICICI Prudential Nifty 500 ETF, including their actual TER and historical AUM/liquidity — `benchmark_methodology.md`.
2. **Pre-2013 STT precision**: 0.125% used here; verify against historical Finance Act notifications — `data_sources.md`.
3. **State-by-state pre-July-2020 stamp duty**: simplified to flat 0.01% buy-side; users in specific states may want a more precise model — `data_sources.md`.
4. **Surcharge/cess incorporation**: deferred to v2 once user's income slab is configurable; current model omits.
5. **DP charge variations**: NSDL vs CDSL, and DP-specific surcharge — `data_sources.md`.

## 14. Dependencies

This document is referenced by:

- `scoring_methodology.md` §7 (replacement rule cost wedge) — patches needed: round-trip placeholder revision and 1.5pp → 3.0pp LTCG threshold.
- `backtest_validity_methodology.md` §5, §10.3, §10.7.
- `benchmark_methodology.md` (instrument-side TER and STT).
- `point_in_time_methodology.md` (date-aware tax regime requires correct sell-date semantics).

Changes to this document force a `cost_model_version` or `tax_model_version` bump and re-run of the cost-drag and tax-lot validity tests.
