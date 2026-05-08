# How the system works, step by step, and why each step is right

This is a longer walkthrough than the earlier `HOW_IT_WORKS_PLAIN_LANGUAGE.md`. Read that file first if you have zero context. This one assumes you know:

- A *stock* is a piece of one company.
- A *stock index* like *Nifty 500* is a basket of many companies.
- An *index fund* or *ETF* is a product that lets you buy the basket in one go.
- We have ₹25,000 every month and want to grow it over many years.

This document walks through one full monthly cycle, explains what the system actually does, and pauses at every design choice to say *why* that choice is the right one. The "why" is more important than the "how." A system you can't justify is a system you can't trust.

A small note on language. We say "stock" and "share" interchangeably. We say "the market" to mean the universe of buyable Indian companies. We say "the benchmark" or "the index" to mean Nifty 500 (with dividends reinvested — the *Total Return Index* or TRI variant). We say "deploying" or "allocating" capital to mean buying something with it. We never say a stock is "going to" do anything; we only say what it has done and what we expect from history.

## 1. The 10-minute version (so you have a frame for everything else)

Once a month — say the last business day of June — the system does this:

1. Refreshes the data: latest prices, any new quarterly results, any new corporate actions, any new filings.
2. For every Indian company in the universe (roughly the Nifty 500 plus historical names that no longer exist), figures out *as of today* what its eight quality, growth, valuation, technical, liquidity, sector, governance, and evidence scores are.
3. For each company, looks back through 10 years of history and finds other companies that, at some past moment, matched today's company on size, sector, market mood, and trading volume. It computes how those historical look-alikes actually performed over the next 12 months versus the index. That's the *Cohort Expected Alpha* score.
4. Combines all those scores into a single *Monthly Buy Score* for each company. If a company has a serious governance red flag (auditor resigned, promoter pledged shares, credit rating cut, etc.), its score is forced to zero — no exceptions.
5. Looks at the whole list of candidates *together* and computes a *Portfolio Edge Score*: a single number that says how confidently we should deviate from the index this month.
6. Translates that confidence into a rupee split. Low confidence → all ₹25,000 to the index. High confidence → ₹5,000 to the index, ₹20,000 to active stock picks.
7. Picks the actual stocks, sized so each one gets between ₹2,500 and ₹5,000, with whole-share rounding (you can't buy half a share in India).
8. Writes a Markdown report explaining every decision and saves the entire thing — input snapshot, scores, plan — to a database. The human reads the report and decides whether to act on it.

Nothing here is exotic. The exotic part is the discipline applied at every step. The rest of this document is about that discipline.

## 2. Why we need a system at all

Three plausible alternatives to a system:

- **Gut feel.** "I read about this company in the newspaper, I'll buy some." This is how most retail investors invest. Hundreds of psychology and finance studies show it underperforms. Humans buy after big run-ups, sell after big drops, and cluster on names they hear about. The names you hear about are not a random sample of the market.
- **Broker tips.** "My broker says XYZ is hot." Brokers make money on transactions. Their incentive is to make you trade more, not better.
- **Mutual funds.** "I'll let a professional handle it." Most active mutual funds, after their fees, don't beat the index over long periods. The few that do, you can't reliably identify in advance.

The honest baseline is buying the index and holding for decades. It is cheap, easy, and historically delivers most of the equity return you'd ever realistically capture. Any system that proposes anything else has the burden of proof that it can do better, *after costs and taxes*, *after surviving bad markets*, *after honest backtest checks*.

The whole project is built around that burden of proof. We start from the index as the default. We deviate only when the *evidence* — not the optimism — supports it.

## 3. Why the index gets to be the default

There is a simple mathematical reason that beating the index is hard for everyone collectively. The market is the average of all participants weighted by their capital. If everyone could trade actively and beat the average, the average would itself rise — but the average is the market itself. So as a group, active investors *cannot* beat the market: they *are* the market, before fees. After fees, they collectively underperform. Over long enough horizons, the math is unforgiving.

That doesn't mean nobody can ever beat the index. A few investors do. But the *average* of the people trying to beat the index loses money to the people just buying the index, after costs and taxes. So your prior — your default before considering any evidence — should be: "I am probably one of the average tryers. I should buy the index."

When you propose to deviate from this default, you are claiming you have a structural reason to be above-average. The system makes you state that reason in numbers, with evidence, every single month. If you can't, you don't deviate that month.

This is why the *Portfolio Edge Score* exists. It is the system's way of asking, every month, "do I actually have a reason to be above-average right now? Or am I just optimistic?"

## 4. What data the system needs and why

The system collects six categories of data. Each one is required because removing it would corrupt a specific decision.

**Daily prices.** For every company, every trading day's open, high, low, close, and trading volume. We need this to compute trend signals (is the stock above its 200-day average?), to measure volatility, to rank candidates by liquidity, and most importantly to compute the *forward returns* used in the cohort engine. Without honest prices, no part of the system has a foundation.

**Quarterly financial statements.** Revenue, profit, operating cash flow, debt, equity, etc. for each company every three months. Two key dates per row: when the *period* ended, and when the *announcement* was made (the announcement is typically 4–8 weeks after the period ends). The system uses the announcement date as the truth-of-availability date. We also store *restatements* — when a company corrects a past report — as new rows linked to the original, so the system can return the value as it was *known* at any past date, not the latest restated value.

**Corporate actions.** Splits, bonuses, dividends, rights, buybacks, mergers, demergers, delistings. These adjust historical prices so a 10-year price chart doesn't show a fake 50% drop on a 1-for-2 split. Without proper handling, every backtest is wrong.

**Index constituents over time.** Nifty 500 reconstitutes every six months — companies enter and exit. To reconstruct what the universe looked like at, say, March 2018, we need to know which 500 companies were in the index *then*, not which 500 are in it today.

**Filings.** Corporate announcements (results, board meetings, auditor changes, regulatory orders, etc.). The system stores their metadata — date, type, hash, source link — so any decision can cite primary sources.

**Portfolio state.** Your current holdings and the *tax lots* underneath them — when you bought, at what price, in what quantity. India taxes capital gains based on the holding period, so we have to remember each lot, not just the average price across all lots of a stock.

For every single piece of data, the system records who said it, when we ingested it, what the source document hashes to, and which parser version produced the structured row. That metadata trail lets us audit any decision after the fact and recover the world as we knew it on any past date. This sounds bureaucratic. It is the price of being able to honestly say later: "yes, this is how we made that decision, and yes, you can verify it."

## 5. Why "point-in-time" matters (the most subtle rule, the most important rule)

Imagine running a test: "I want to know what my strategy would have done starting in January 2018, walking forward month by month." It's now May 2026. Your databases contain the full history. Every March 2018 quarterly result is sitting in there.

Naively, you'd write a backtest that, on March 31, 2018, lets the strategy use the March 31, 2018 quarterly results. **This is wrong.** Those results weren't published until mid-May 2018. On March 31, your strategy could not have known them. Your test pretended otherwise. Your backtest is not a real backtest — it's a fantasy that uses information from the future.

This kind of cheating is called *look-ahead bias*. It's the most-violated rule in retail backtesting. It systematically makes strategies look better than they are.

The system has a layer called the *PIT loader* (point-in-time loader) whose only job is to enforce honesty. Every time the engines ask "what's the latest financial result for company X as of April 15, 2018?", the loader returns rows whose announcement date is on or before April 15, 2018. The May 15 result is invisible until the calling code passes a date of May 15 or later. There is no way to bypass this — every query through the codebase goes through this layer.

A subtle case: a company can announce Q4 results, then four months later restate them. If your backtest is sitting on May 16, 2018, the restatement (announced September 2018) is invisible. The loader returns the original numbers as they were originally reported. This is deeper than most backtests bother with, and it matters: many real-world surprises (and many real-world failures) involve restatements that change the picture.

To prove the system actually maintains the rule, the test suite includes a *property test* that picks 1,000 random `(company, date)` pairs and asserts that no piece of data returned by any loader function has a timestamp after the requested date. The test runs in CI on every commit. If any developer accidentally introduces a leak, the property test catches it before the change merges.

This is the bedrock. Without it, every other number the system reports is suspect.

## 6. Why we include companies that no longer exist (survivorship)

If you ask "how did Indian banks do over the last 20 years?" and you only look at banks that exist today, you exclude:

- Banks that went bankrupt and got merged out at zero or near-zero value to shareholders.
- Banks that were taken over for pennies on the rupee.
- Banks the regulator forced to recapitalise, wiping out existing shareholders.

Those bad outcomes happened to real shareholders. Excluding them is not "looking at the data" — it's looking only at the winners. It's like asking "how do startups do?" and only surveying ones still in business.

This bias has a name: *survivorship bias*. Every backtest that looks at "today's index, walked backward" suffers from it. The historical numbers will look better than what investors actually got.

The system maintains a *delisted-companies seed list*. About 50 well-known Indian distress / delisting cases are listed (Yes Bank's 2020 reconstruction, DHFL's bankruptcy, IL&FS, Jet Airways, Cox & Kings, the various Reliance ADAG entities, Bhushan Steel and Essar Steel via the IBC, and so on). Each one carries an event date, an event type, and a *recovery rate* — the fraction of cost basis that shareholders actually got back. The default recovery rate is 0% (conservative). Where there's a known recap or partial proceeds, the actual figure goes in.

Every backtest universe is the *union* of:

- Companies that are currently in the relevant index.
- Companies that *were* trading at any past date and have since been delisted or distressed.

This is a small data tax — about 50 extra companies and a few dozen events — but it removes a systematic upward bias from every result. The system's promotion criteria explicitly require this: a backtest run on a survivor-only universe must look better than the survivorship-corrected version, and the gap must be large enough (>1pp annualised) to indicate the seed list has real coverage. If the gap is too small, that's a sign the seed list isn't comprehensive enough yet, and promotion is blocked until it is.

## 7. The eight company-level scores

Each one is a number from 0 to 100 (higher = more attractive). Each measures something specific. Together they describe the company from multiple independent angles, so a candidate can't fake its way to the top of the list by being strong on one dimension only.

**Business Quality.** Made of three things: return on equity (how much profit per rupee of owners' capital), cash conversion (does reported profit show up as cash, or as IOUs?), and debt-to-equity (how much leverage is the company carrying?). A high business-quality score means the company is a profitable, cash-generating, conservatively financed enterprise. *Why these three?* Because each maps to a thing a thoughtful business owner would check before buying a kirana shop. Profitability, cash, leverage. Companies that fail one of these and pass the others have a known failure mode the system wants to flag.

**Earnings Acceleration.** Year-over-year revenue growth, plus whether that growth rate is itself increasing. A company growing 10% in 2024 was growing 5% in 2023 is *accelerating*. A company growing 10% in 2024 was growing 18% in 2023 is *decelerating*. *Why pay attention to acceleration?* Because the price impact of growth is non-linear: when growth surprises positively, the stock tends to re-rate sharply; when growth disappoints, the stock tends to re-rate sharply down. The signal is in the change of pace, not the level.

**Valuation Sanity.** A simple price-to-earnings (P/E) check. The score is high when the P/E is low (around or below 15), and falls to zero as the P/E gets very high (above 60). Loss-makers (negative earnings) are penalised but not zeroed automatically — there are legitimate cases where a company is investing through a loss period. *Why this approach?* Because even great companies are bad investments at the wrong price. The P/E check is crude but in practice it filters out the most obviously stretched names without being sophisticated enough to pretend to know what's "fair."

**Technical Confirmation.** Is the price above its 200-day moving average? How far below the 52-week high is it? *Why look at the chart at all?* Because price contains information from market participants we can't otherwise see. A stock plunging on rising volume is the market telling us something we don't know yet. The system uses technical signals only to *confirm or deny* what the fundamentals already suggested — never as a primary buy signal.

**Liquidity.** How heavily traded is this stock? We bucket every company as high (≥₹50 cr daily traded value), mid (₹5–50 cr), or low (<₹5 cr). *Why this matters:* if a stock trades only ₹50 lakh per day on average, your ₹5,000 ticket is fine, but the *bid-ask spread* (the gap between the price you can buy at and the price you can sell at) is much wider than for a heavily traded stock. We strongly prefer liquid names because the friction of getting in and out is small.

**Sector Tailwind.** A placeholder in v1 — set to a neutral 50 for everyone. The full implementation would consume sector-index data and macro signals to identify which industries have a tailwind right now. Adding it later is a champion-challenger experiment, not a v1 requirement.

**Governance Safety (structured tier).** Penalises receivables growing much faster than revenue (often a sign the company is "stuffing" customers with inventory it can't really sell), CFO-to-PAT collapse (profit on paper that isn't showing up as cash), and other deterministic structured signals. *Why structured-only?* Because the textual signals (auditor resigned, regulatory action, related-party-transaction concerns) require NLP on filings, which has a higher false-positive rate. Those textual signals are detected separately and routed to *human review* — they don't auto-disqualify a company until a human confirms.

**Evidence Quality.** Meta-score about the data itself. Is the most recent quarterly result more than 90 days old? Penalty. Are some numbers from a third-party data source rather than the original filing? Penalty. Is there a conflict between two sources we couldn't resolve? Penalty. Did the cohort matching find too few historical look-alikes to be statistically meaningful? Penalty.

The Evidence Quality score does double duty: it's one of the eight inputs to the Monthly Buy Score, *and* it's used as a multiplier on the final score. A candidate with weak evidence — even if its underlying ingredients look great — can never reach the top tier. The multiplier formula: at evidence_quality = 100 the multiplier is 1.0; at evidence_quality = 50 the multiplier is 0.75; at evidence_quality = 0 the multiplier is 0.5. So a candidate with no evidence floor cannot exceed half its raw score. This is exactly the right shape: don't trust scores you can't audit.

## 8. The cohort idea: why we look at history and how

The eight scores describe a company *as it is today*. None of them tell us how the company is likely to perform *going forward*. That gap is filled by the *Cohort Expected Alpha* score, which alone is special.

Here's the idea. For a candidate today — say, a mid-cap consumer-discretionary company with high liquidity, in a neutral market regime — the system goes back through the last 10 years and finds every (company, observation date) pair where the company *at that time* was also mid-cap consumer-discretionary high-liquidity in a neutral regime. That's the *cohort*. We look at how each cohort member actually performed over the 12 months following its observation date, *minus the index return over the same 12 months*. The resulting list of excess returns describes "what historical look-alikes actually did."

The CEA score is computed from the median (middle value) of those excess returns. Median in years where the cohort hit it big: positive score. Median in years where the cohort lost to the index: low score.

There are two crucial design choices here.

First, the cohort matching uses *only structural buckets* — size, sector, regime, liquidity. It does *not* match on fundamental factor scores like business quality or valuation. *Why?* Because if we matched on the same factors that go into the Monthly Buy Score, we'd be using each factor twice: once to find the cohort, once to weight the score. That double-counting inflates the system's effective sensitivity to those factors and creates a very subtle form of overfitting that breaks calibration. Keeping cohort matching on structural buckets only, and putting fundamental factors into the Monthly Buy Score only, gives clean separation.

Second, cohort confidence depends on cohort size:

- 30 or more historical look-alikes → full confidence, use the score as-is.
- 10 to 29 look-alikes → cap the score at 60 (medium confidence) and apply an evidence-quality penalty.
- Fewer than 10 → set the CEA score to zero. We *do not* invent confidence we don't have.

This is honest. A cohort of three companies tells you almost nothing.

The cohort's universe must include companies that have since been delisted (back to the survivorship rule). Otherwise the cohort hit-rate and median return are biased upward.

## 9. The Monthly Buy Score: combining the eight scores

Each candidate's eight ingredients plus the CEA score combine into a single Monthly Buy Score. The weights are documented; CEA gets the heaviest weight (20%), followed by earnings acceleration / business quality / governance safety / valuation (15%, 15%, 15%, 12% respectively), with technical (8%), sector / liquidity / evidence (5% each).

After the weighted sum, the score is multiplied by the evidence-quality multiplier (0.5 to 1.0). Then if a fatal structured-tier governance flag is active, the score is forced to zero and the candidate is rejected.

Why this shape?

- *Why CEA highest?* It's the only ingredient that incorporates historical evidence. The others describe the present; CEA bridges to the future.
- *Why governance as a hard gate, not a weighted input?* Because governance failures kill capital. A company can be cheap, growing, and well-managed, but if the auditor just resigned, you don't want to be a shareholder. Treating it as a weighted input would let other strengths "outvote" the warning. Treating it as a gate prevents that.
- *Why evidence quality both as a sub-score and as a multiplier?* Because weak evidence should hurt twice. A candidate with weak evidence still has a low evidence_quality score *and* gets its raw composite multiplied down. Without the multiplier, a candidate could compensate for weak evidence with strength elsewhere. With the multiplier, weak evidence puts a hard ceiling on the final score.
- *Why these specific weights?* They're a starting point, derived from the methodology document. The weights are themselves a hypothesis, and the system explicitly tests alternative weight sets in the *champion-challenger* framework. Equal-weight is one of the alternative strategies. The weights aren't sacred — they're version-controlled.

## 10. The Portfolio Edge Score: should we deviate from the default *this month*?

Now we have a Monthly Buy Score for every candidate company. The next question: *should we put any of the ₹25,000 into individual stocks at all this month, or just buy the index?*

The Portfolio Edge Score (PES) answers exactly that. It's also 0 to 100 and combines six things:

1. **Active Opportunity Breadth (30% weight).** How many candidates are actually strong this month? A "strong" candidate has Monthly Buy Score ≥ 70, evidence quality ≥ 40, no fatal flag, not blocked by portfolio caps. Zero strong → 0 score. One strong → 40. Two or three → 60. Four to six → 80. Seven or more → 100. *Why a step function?* Because conviction comes from breadth. A single hot pick can be a fluke. Multiple independent signals at the same time is harder to dismiss.

2. **Top Candidate Quality (25% weight).** Mean Monthly Buy Score of the top 5 strong candidates. *Why this matters separately from breadth?* Because seven mediocre picks beats two excellent ones in breadth but not in quality. We want both.

3. **Evidence Quality of the top N (15% weight).** Mean evidence quality of the same top 5. *Why include this in PES?* Because if our top picks rest on shaky data, our confidence shouldn't be high regardless of how good the headline scores look.

4. **Market Regime Support (10% weight).** Bull market → 80. Neutral → 50. Bear → 20. *Why include the regime?* Because the same candidate strength behaves differently in different markets. In a roaring bull market, even mediocre picks tend to drift up; in a falling market, even strong picks tend to drift down. We're cautious about being aggressive in environments that historically punished aggressiveness.

5. **Existing Portfolio Add Opportunity (10% weight).** Mean Monthly Buy Score of current holdings that are still under their position cap and still classified as "intact." *Why this matters?* If we already own great stocks, we should consider adding to them rather than always seeking new ones. This subcomponent rewards already-owned strength.

6. **Risk/Cost Penalty (10% weight).** Starts at 100, deducts for portfolio bloat (more than 18 holdings), single-position cap breaches (any one stock >10%), sector concentration (any one sector >25%), high turnover (more than 100% of portfolio churned in the last 12 months), and unstarted broken-thesis exits. *Why this exists?* To prevent the system from reaching for active picks while ignoring the costs we're already paying. If we're already over-traded and concentrated, we shouldn't add more.

The PES then maps to a rupee split via a fixed table:

- PES ≤ 50: ₹25,000 to the index, ₹0 to active stocks.
- PES 51–60: ₹20,000 / ₹5,000.
- PES 61–70: ₹15,000 / ₹10,000.
- PES 71–80: ₹10,000 / ₹15,000.
- PES 81–100: ₹5,000 / ₹20,000.

Why these particular boundaries? They're a starting hypothesis, the same way the weights are. They get *calibrated* against historical data: the system replays each historical month, computes what PES would have been, computes what the active-vs-index split would have looked like, and computes what the realised forward 12-month return was. The boundaries are accepted as valid only if average forward returns *monotonically increase* across PES buckets — i.e., higher-PES months actually delivered better forward returns. If they don't, the boundaries get collapsed (fewer, wider buckets) and re-tested. If even three buckets fail monotonicity, the calibration fails and the system reverts to a conservative default (₹20k index / ₹5k active for any PES > 50).

There's also a critical *safety floor*: until the calibration is independently confirmed on a locked-out test window, the index allocation is never less than ₹5,000 (20% of monthly capital). In other words, even if the PES is 99 and the system is screaming "all in on active stocks," at least ₹5,000 still goes to the index. This floor exists because over-confidence is the most common failure mode of quantitative systems. Until we have proof that the highest PES bucket actually delivers, we cap the maximum aggressiveness.

## 11. The deployment engine: from numbers to actual rupees

The PES gave us a split — say, ₹10,000 active, ₹15,000 index. Now we have to decide which active stocks get the ₹10,000.

The deployment engine does this:

1. Sort the strong candidates by Monthly Buy Score (highest first).
2. For each candidate in order, allocate a *ticket* between ₹2,500 (floor) and ₹5,000 (cap). The cap is to keep no single position too large for a small monthly slice.
3. Apply *whole-share rounding*. Indian cash equity doesn't allow fractional shares. If the candidate's price is ₹2,800 and the ticket is ₹4,000, we can buy exactly 1 share for ₹2,800. The remaining ₹1,200 is the *residual*. The residual spills back into the index allocation.
4. If a candidate's price exceeds the ticket size entirely (e.g., a ₹10,000 stock when the ticket is ₹2,500), the whole ticket spills to the index for that candidate (0 shares bought).
5. After the active candidates are processed, the index allocation gets the original index amount plus all residuals.

The output is a list of *actions*: each action is `(action_type, symbol, target_amount, executable_quantity, estimated_trade_value, residual_amount, residual_destination, reason)`. Action types are `new_buy`, `add_existing`, `replace`, `buy_index`, or `hold_cash`. Each action is logged to the database alongside the deployment plan; each carries enough metadata that the report generator can explain it in human language.

If the portfolio is already at its cap (more than ~25 holdings), new candidates can only enter via *replacement*: sell the weakest current holding and buy the new candidate. Replacement is gated by a real, post-tax, post-cost wedge:

```
expected_after_tax_after_cost_excess_return(new) >
expected_after_tax_after_cost_excess_return(hold weakest) + threshold
```

Where the threshold is 4 percentage points if the existing holding is held under 12 months (because the sell triggers Short-Term Capital Gains tax at 20%, and we need to clear that cost) or 3 percentage points if held over 12 months (Long-Term Capital Gains at 12.5%, plus round-trip cost ~1%, gives roughly a 2.9pp wedge to clear). Without this gate, the system would happily replace holdings on small score gaps that get destroyed by tax and cost — a common mistake of naive ranking systems.

## 12. The monthly report: every action must justify itself

The system writes a Markdown report each month with the following sections:

- **Header** — month, capital available, benchmark, PES, the active/index split.
- **Final Deployment** — the full action list with target amount, executable quantity, residual, and reason.
- **Why Not Just Buy Index?** — for each active stock, the system has to be able to point at the cohort backing, the evidence, the score components. If the active allocation was ₹0, the section explicitly says so and explains why.
- **Portfolio Edge Score Breakdown** — each of the six PES subcomponents with its score, so the human can see *why* the overall PES landed where it did.
- **Current Portfolio Review** — for each existing holding: status (intact / weakening / broken), recommendation (add / hold / reduce / exit), reason.
- **Rejected Candidates** — companies considered but not bought, with rejection reasons (weak evidence, valuation excess, governance flag, low cohort, sector cap reached, position cap reached, etc.).
- **Index/Cash Fallback Explanation** — when active ideas were weak, an explicit statement that money went to the index by design.
- **Next Month Watchlist** — companies that *almost* made the cut, and what specifically would need to change before they're bought (e.g., "P/E falls below 25" or "next quarter shows revenue acceleration continuing").

The report is the system's accountability mechanism. Every active buy must be explainable. If the system can't tell you why it bought something, *you should not act on the recommendation*.

## 13. Costs and taxes: the silent edge eaters

Indian equity transactions have many small frictions. Each is a few basis points; in aggregate they're a real drag on small tickets:

- *Securities Transaction Tax (STT)*: 0.10% on every buy and every sell.
- *Stamp duty*: 0.015% on every buy.
- *Exchange transaction charges*: about 0.003% per side.
- *SEBI charges*: about 0.0001% per side.
- *GST*: 18% on (brokerage + exchange + SEBI charges).
- *Brokerage*: zero on delivery trades at most discount brokers today; ₹20 per order at older discount brokers. Configurable in the cost model.
- *DP charge*: a flat ~₹13.5 every time you sell, regardless of trade size. On a ₹5,000 sale, that alone is 0.27%.
- *Slippage / bid-ask spread*: about 0.05% per side on a liquid name; up to 0.25% per side on a thinly traded one.

For a ₹5,000 round trip on a liquid name with zero brokerage, the total round-trip cost is roughly 0.6%. On smaller or less liquid tickets it can be 1.5% or more.

Then there's the tax on profits. India's regime as of mid-2024:

- Short-Term Capital Gains (held under 12 months): 20% on the realised gain (was 15% before July 23, 2024).
- Long-Term Capital Gains (held 12 months or more): 12.5% on the gain above ₹1,25,000 per financial year (was 10% above ₹1,00,000 before July 23, 2024).

The system models all of this, picks the right regime based on the sale date, and tracks the per-financial-year LTCG exemption usage. The backtester reports three numbers: *gross* (no costs or taxes), *net of cost* (costs subtracted), and *net of cost and tax* (taxes also subtracted). The headline is always the third one. A strategy that looks great gross but breaks even after the friction stack is not actually a good strategy.

This is also why the replacement rule has the wedge gate. Selling a winner triggers tax that destroys edge. The system has to know, in rupees, whether the swap is worth the friction.

## 14. The backtest: how we know the system actually works

We can't just trust that the system is right because the formulas look reasonable. We have to *test* it.

A *backtest* is a simulation. We pretend it's January 2012, walk forward month by month, let the system make its monthly decision *using only the data that was available at each month*, accumulate the simulated portfolio, and compare against an index SIP.

Three rules keep the backtest honest:

**Train / validation / holdout split.** The historical window is divided in three. Older data (2012–2018) is *training* — we use it to develop the strategy. Middle data (2019–2022) is *validation* — we use it to choose between strategy variants. Recent data (2023–2024) is *holdout*, and it is **locked**. We never look at it during development. Once a strategy variant has been chosen on validation, we test it once on holdout. If it passes, it gets promoted. If it fails, the holdout is *burned* — we don't get to try a second strategy on it. Why? Because if you keep retrying on the same holdout, you're just slowly memorising it. The single-shot rule is the antidote.

**Block bootstrap confidence intervals.** Monthly returns are autocorrelated — if last month was bad, this month is more likely to be bad too. Standard statistical tests assume independence and overstate confidence. *Block bootstrap* is the honest version: resample 12-month chunks of returns (with replacement) thousands of times to build an empirical distribution of "what could the average have been by chance." We require that the lower 95% confidence bound, not just the point estimate, be above zero before we promote a strategy.

**Style-adjusted alpha.** Suppose the system's portfolio drifted toward small-cap stocks during a small-cap rally. The strategy's gross return looks great, but most of it is just a passive size tilt. To untangle skill from style, we regress the strategy's monthly returns on four factors: market, size, value, momentum. The intercept of that regression — the part that *isn't* explained by passive style exposure — is the *style-adjusted alpha*. That's the actual stock-selection skill we're paying for. We require it to be positive with positive lower-CI bound.

The full validity test suite includes:

- The PIT property test (no future leakage in any random sample).
- The survivorship test (gap > 1pp between survivor-only and survivorship-corrected universes).
- The cost-drag test (the cost stack reduces backtested CAGR by an amount close to an analytical estimate; if not, costs are misapplied or lots are broken).
- The calibration test (Monthly Buy Score deciles are monotonic vs forward returns; if not, the score isn't predictive).
- The replay determinism test (running the same backtest twice produces byte-identical output; if not, there's a hidden non-determinism we have to find).
- The corporate-action continuity test (split / bonus / dividend pre-ex and post-ex prices should produce continuous returns; if not, our corporate-action handling has a bug).
- The tax-lot correctness test (FIFO consumption with regime-correct rates and per-FY exemption tracking).

If any of these fail, no strategy variant is promoted, regardless of how attractive its CAGR looks.

## 15. The safety brakes

Several mechanisms prevent the system from doing anything dramatic:

- **20% index floor.** Until the holdout calibration confirms the highest PES bucket reliably delivers, the index allocation never goes below ₹5,000. Single overconfident months can't blow up the strategy.

- **Single-shot holdout.** As above — one strategy gets one shot at the holdout. If it fails, the holdout is burned. This is the discipline that makes the backtest honest in the long run.

- **Fail-loud on missing data.** Missing fields are explicit nulls (with a sentinel), never zeros, never interpolated. Unsupported corporate actions stop the backtest with a precise list, never silently mis-price. Source conflicts are logged. There is no override flag.

- **LLM-as-extractor rule.** Large language models can pull structured facts from filings *with citations* and can flag candidate textual governance issues for human review. They cannot produce numeric scores, override deterministic gates, or recommend buy/sell. All numerics are deterministic.

- **No auto-execution.** The system writes a plan and a report. The human reads the report and decides whether to act. The system never sends an order to a broker. It is decision support, not autopilot.

- **Personal use only.** The repository is for one user's own decisions. No third-party capital. No advisory service. No published recommendations.

## 16. What can still go wrong

A complete and honest list:

- **Cohort engine quality.** The cohort is only as good as the underlying historical data and the bucket boundaries. If we mis-classify a company's sector or market-cap bucket, its cohort is wrong.

- **Regime classification.** Calling 2018 "neutral" vs "bear" is a judgment call. The current implementation uses simple rules (Nifty 500 vs 200-day moving average, breadth, vol percentile); fancier classifications would change every score that depends on the regime bucket.

- **Sector tailwind is a placeholder.** A full sector signal would change the answers. Adding it later is a champion-challenger experiment.

- **Tax model omissions.** Surcharge and cess on capital gains aren't modelled. For a high-income user, the true tax wedge is somewhat larger than what the simulator shows.

- **Corporate-action edge cases.** Rights issues, buybacks, mergers, demergers, delistings — all of these have per-event handling needs. The system raises an error for any unsupported action so the backtest can't silently mis-price; but the error means the affected month/stock has to be excluded until the per-event treatment is implemented.

- **Restated filings beyond financials.** We model restatements for financial statements; not yet for governance flags, ratings, etc. Adding the same `as_known_at` pattern to those tables is a small extension.

- **Real-time data latency.** Our model assumes the latest data is available within minutes of the source publishing it. In production the scraper may lag; that's an operational risk.

- **The seed list isn't 50.** Until the curated delisted-companies file has at least 50 confirmed cases (with verified dates and last-traded symbols), the survivorship test fails the coverage threshold and no strategy can be promoted. The list of names is in `data_sources.md` section 6; the work to go from named list to confirmed metadata is real.

The whole system is designed so that when something is wrong, the test suite tells us before the strategy gets promoted. The remaining unknown unknowns are the things we haven't thought of. Those will surface, and when they do, the discipline — version every change, log every decision, test before promoting — is what limits the damage.

## 17. The shape of the right answer

If you read everything above, you should have the following picture:

The system spends most of its effort on *not making bad decisions*. Defaulting to the index. Capping aggressive allocations. Requiring evidence with each pick. Refusing to buy on weak data. Failing loudly on missing or contradictory inputs. Logging every decision with a reproducible snapshot. Locking holdout data away from development. Rejecting strategies that don't beat the index *after* costs and taxes.

The ambitious goal — beat the benchmark over many years — is a side effect of doing all of those negative things well. Most of the value of a system like this isn't in the moments it correctly picks a winner. It's in the moments it correctly says "no" to a bad idea, and in the months it stays patient with the boring index allocation when nothing better is on offer.

That patience is hard to maintain by gut. A system can do it for you. That's the actual job this codebase exists to perform.
