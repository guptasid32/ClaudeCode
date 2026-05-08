# What this project actually does, explained simply

This document is for someone who has never invested in stocks, never heard of an index fund, and is reading the rest of the repository for the first time. No prior knowledge required. Where a term is needed, it is defined the first time it appears, in italics, with the definition that matters for this project.

## 1. The everyday problem

Imagine you have ₹25,000 left over every month and you want to put it somewhere it can grow over many years. You have a few choices:

- Spend it.
- Put it in a fixed deposit at a bank. Safe, but the growth is slow.
- Buy stocks of Indian companies. Riskier, but historically grows faster over long periods.

This project is about that third option, with a specific question:

> Each month, where exactly should ₹25,000 go to grow your wealth?

That sounds simple, but there are thousands of Indian companies. You can't research them all every month. You need a system that tells you, for *this specific month*: how much should go into a basic broad-market option, how much should go into specific stocks, and which stocks.

That's what this codebase is.

## 2. The most important idea: "the index" is the default

A *stock* is a tiny piece of ownership in a single company — say, Tata Consultancy Services (TCS) or Reliance Industries.

A *stock market index* is a recipe for a basket of many stocks. The most important Indian one for our purposes is called *Nifty 500*. It is, roughly, "the biggest and most-traded 500 companies on the National Stock Exchange (NSE), bundled together by their size." If those 500 companies do well on average, the Nifty 500 number goes up. If they do badly on average, it goes down. Over decades, it has gone up by quite a lot.

You can buy the index very easily. You don't have to actually buy 500 stocks. There are products called *index funds* and *ETFs* (Exchange Traded Funds) that do the bundling for you. You give one product ₹5,000 and it automatically owns a tiny piece of all 500 companies, in the right proportions. They are cheap, simple, and very hard to beat.

> **The single most important rule of this project: investing in the index is the *default*. Buying individual stocks is the exception, used only when there is good reason to believe specific stocks will beat the index.**

A lot of investing systems go the other way: they give you a list of "5 stocks to buy this month" no matter what. This project refuses to do that. If no individual stock looks attractive, the right answer is "put all ₹25,000 into the index this month and stop trying to be clever." Most months that is the correct decision.

## 3. When does it make sense to *not* default to the index?

Sometimes a particular company looks especially good. Maybe its earnings are growing fast, or it's selling for less than it's worth, or it has a very strong balance sheet. In those moments, putting some of the ₹25,000 directly into that company *may* beat the index.

The key word is "may." Investing is full of stories where a company looked great and didn't perform. So the system needs a way to tell:

- How attractive is each candidate company right now?
- How sure are we?
- Are the candidates today *as a group* attractive enough to deviate from the safe default?

If the answer to the third question is "yes, very," the system shifts more of the ₹25,000 toward those individual stocks. If the answer is "no, this is a so-so month," the system stays mostly or fully in the index.

## 4. The score ingredients, explained one by one

The system computes a few numbers per company every month. Each is a 0-to-100 score. Higher is better.

### 4.1 Business quality (0–100)

Imagine inspecting a kirana shop you're thinking of buying. You'd want to know:

- Is it making money? (*profit*)
- When customers pay, does the shop actually receive the money quickly, or is there a lot of lending and IOUs? (*cash flow*)
- Has the shop borrowed lots of money from moneylenders to keep running? (*debt*)
- For every ₹100 the owner has put into the shop, how many rupees of profit does it produce per year? (*return on equity*)

A high *business_quality* score means the company is profitable, generates cash, isn't drowning in debt, and earns good returns on the money its owners have put in.

### 4.2 Earnings acceleration (0–100)

This asks: is the business growing *and* is the rate of growth speeding up? A company growing 5% a year for a decade is steady. A company that grew 5% three years ago, 10% last year, and 18% this year is *accelerating*. Acceleration tends to attract more attention from buyers, which tends to push the stock price up.

### 4.3 Valuation sanity (0–100)

This asks: is the stock *cheap relative to its earnings*?

If a company earns ₹100 of profit per share per year, and the stock costs ₹1,500, you're paying 15× annual earnings. That's a *price-to-earnings (P/E) ratio* of 15. If the same earnings cost you ₹6,000 per share, the P/E is 60 — much more expensive.

A high valuation_sanity score means the stock isn't priced like a fantasy. Even great companies can be bad investments if you pay too much.

### 4.4 Technical confirmation (0–100)

This is the only score that looks at price action rather than the underlying business. It asks:

- Is the stock currently above its average price over the last 200 trading days? (*200-day moving average*) This is a rough "is it in an uptrend or downtrend" check.
- How far is it from its 52-week high? A stock that's down 50% from its peak is a different beast than one near its peak.

A high technical_confirmation score means the price chart isn't actively saying "this thing is falling apart."

### 4.5 Liquidity (0–100)

How easy is it to buy and sell this stock without moving the price?

If a stock trades hundreds of crores of rupees per day on average, you can buy ₹5,000 worth without anyone noticing. If it trades only ₹10 lakhs per day, your buy order might single-handedly move the price up. We strongly prefer *liquid* (heavily traded) stocks because the friction of buying and selling them is small.

### 4.6 Sector tailwind (0–100)

A *sector* is an industry — IT services, banks, oil and gas, FMCG (everyday consumer goods), pharma, and so on. Some years pharma is hot; other years it's banks; other years it's IT. This score is meant to capture which sectors have a tailwind right now. In v1 of this system the score is a placeholder (always 50, "neutral"). Sector intelligence is something to add later.

### 4.7 Governance safety (0–100)

This is the "are these people honest?" score. Specifically:

- Is the *promoter* (the founding family or controlling group) borrowing against their own shares? When they pledge shares as collateral, banks can seize and sell them, crashing the price.
- Is the company's *auditor* (the outside accountant who checks the books) suddenly resigning?
- Are receivables (money customers owe to the company) growing way faster than sales? That can be a sign the company is "stuffing" customers with goods nobody actually wants.
- Has a credit rating agency just downgraded their bonds?

A high governance_safety score means none of those red flags are flying.

### 4.8 Evidence quality (0–100)

This is meta. It asks: *how confident are we in the data we used to compute the other scores?*

- Is the most recent quarterly result more than 90 days old? Penalty.
- Are some numbers from a third-party data source rather than the official filing? Penalty.
- Is there a conflict between two sources we couldn't resolve? Penalty.
- Is the historical comparison group too small to be statistically meaningful? Penalty.

A high evidence_quality score means the numbers we have are recent, official, and uncontradicted.

## 5. The "expected alpha" score, explained

There's one more score, and it's special. It's called *Cohort Expected Alpha (CEA)*, and it answers a question the others don't:

> Historically, when companies that look like *this candidate* showed up, what did they actually do over the next 12 months, compared to the index?

The trick is what "look like this candidate" means. The system does *not* compare on the score values themselves (that would be circular). It compares on structural buckets:

- Size of the company (large, mid, small, micro).
- Industry sector.
- The general market mood (bull, neutral, bear).
- How heavily traded it is (high, mid, low liquidity).

For a candidate today, the system goes back through 10 years of history and finds every other (company, point-in-time) pair that matched on all four buckets. That's the *cohort*. For each member of the cohort, it computes the actual 12-month forward return that happened, and subtracts the index return over the same 12 months. That difference is the *excess return* — how much the company beat or lost to the index.

The CEA score is based on the *median* (middle value) of those historical excess returns. If, historically, similar setups beat the index by 6%, the score is solidly positive. If they underperformed, the score is low.

Why this matters: this score is the only one that says "based on actual history, here's what we expect." All the others are descriptions of the company's *current* state. CEA is the bridge from "this company is doing well right now" to "this company will plausibly do well over the next year."

If we don't have enough historical look-alikes to be statistically meaningful (cohort size below 10), the CEA score is set to zero and the candidate is downgraded. We'd rather be honest about uncertainty than pretend to know.

## 6. Putting it together: the Monthly Buy Score

For each candidate company in a given month, the system computes a single number called the *Monthly Buy Score (MBS)*, which is a weighted average of the eight ingredient scores plus the CEA score. The weights are documented; CEA gets the heaviest weight. The whole thing is then multiplied by an evidence-quality factor — a candidate with weak evidence can never get a top score even if its ingredients look great.

If a fatal governance problem exists (a sharp rise in promoter pledged shares, a serious credit downgrade, etc.), the MBS is forced to **zero** and the company is rejected outright, regardless of other ingredients. This is intentional. Governance disasters can vaporise capital, so we treat them as a hard gate, not a weighted input.

## 7. The Portfolio Edge Score: should we even *be* picking stocks this month?

Now we have a Monthly Buy Score for every candidate. The question becomes: should we deploy any of the ₹25,000 into individual stocks, or just buy the index?

The system computes a *Portfolio Edge Score (PES)*, which answers exactly that. PES looks at:

- How many strong candidates are there this month? (If only one or two stocks score above 70, that's not enough breadth to be confident.)
- How good are the top 5 candidates? (A breadth of mediocre stocks doesn't help.)
- How confident is our evidence for them?
- Is the overall market mood favourable, neutral, or fearful?
- Are the existing stocks in our portfolio still attractive enough to add more?
- Are we accumulating risks — too many holdings, too much in one sector, too much trading already?

The PES is also 0–100. The system uses it as a dial:

- PES ≤ 50 → all ₹25,000 goes into the index this month. No active stock buying.
- PES 51–60 → ₹20,000 index, ₹5,000 active.
- PES 61–70 → ₹15,000 / ₹10,000.
- PES 71–80 → ₹10,000 / ₹15,000.
- PES 81–100 → ₹5,000 / ₹20,000. (Note: even here we keep at least ₹5,000 in the index. That floor is a safety brake until we have proven the system on locked-out test data.)

So the PES is the answer to "be more or less aggressive this month."

## 8. The deployment engine: actually allocating the rupees

Once the system knows the active-vs-index split, it has to decide *which* stocks get the active rupees. The best candidates by Monthly Buy Score get tickets of ₹2,500–₹5,000 each. There's a wrinkle specific to India: you can't buy fractional shares of a stock. If the stock costs ₹3,200 and your ticket is ₹4,000, you can buy exactly 1 share for ₹3,200 and your remaining ₹800 spills over to the index. The system handles this whole-share rounding automatically.

If the portfolio is already full (more than 25 stocks), the system either rejects new candidates or proposes a *replacement*: sell the weakest existing holding and buy a much stronger new one. Replacement is gated by a cost-and-tax-aware threshold: the new candidate must beat the existing one by enough to clear realistic round-trip costs and the tax on the realised gain. Otherwise the swap destroys value.

## 9. Why "point-in-time" matters so much

The most subtle and most important rule in the entire codebase is: **never use information that wasn't actually available on the decision date.**

Imagine you're trying to test what your strategy would have done starting in January 2018. You're sitting today (May 2026) with full hindsight. Your databases now show, for example, a financial result for "March 2018 quarter." But that result wasn't published until *May 15, 2018*. If your test pretends you knew the result on March 31 — when in real life you wouldn't have — you've cheated. Your test will look better than reality.

The codebase has a layer called the *PIT loader* (point-in-time loader) whose only job is to enforce this rule. Every time a feature engine asks for "the latest financial result for company X as of April 15, 2018," the loader returns only data that was *known* on that date. Results announced after that date are invisible.

This sounds obvious. It is the most-violated rule in retail backtesting. We treat it as the system's truth boundary and have automated tests (1,000 random samples per run) that hunt for any leak.

The same idea applies to *restatements*. A company can announce a Q4 result, then 3 months later announce a corrected version. The PIT loader stores both rows and returns the one that was knowable on a given date — not the latest restated value. It's an extra layer of paranoia, and it matters.

## 10. Why "survivorship" matters so much

If you ask "how did the stocks of Indian banks do over the last 20 years?", the obvious answer is to take the banks that exist today and walk their prices backwards. That answer is *wrong*. It excludes the banks that went bankrupt, the ones that got merged out of existence, the ones that were taken over for pennies on the rupee. Those bad outcomes happened to real shareholders. They have to be in the test or you're only counting the winners.

The codebase has a `delisting_events` table for exactly this reason. The seed list includes about 50 well-known Indian distress / delisting cases (Yes Bank, DHFL, IL&FS, Jet Airways, Cox & Kings, IBC resolutions, etc.). Every backtest universe is the union of "currently active companies" and "companies that were active back then but later disappeared." If we don't have at least 50 confirmed cases, the system refuses to certify a strategy.

## 11. Costs and taxes — the silent edge eaters

Indian equity has many small frictions:

- *STT (Securities Transaction Tax)* — a small percentage on every buy and every sell.
- *Stamp duty* — small charge on every buy.
- *Exchange and SEBI charges* — fractions of a percent.
- *GST* — 18% on the brokerage and exchange charges.
- *Brokerage* — varies; some discount brokers charge zero on delivery trades.
- *DP (Demat) charge* — a flat ~₹13.5 every time you sell, regardless of trade size.
- *Slippage* — the bid-ask gap; you buy at slightly above the "true" price and sell at slightly below.

For ₹2,500–₹5,000 tickets, these total something like 0.6–1.5% per round trip. That's a real drag. Worse, when you sell a stock for a profit, the government takes a *capital gains tax*: 20% if you held it less than a year (Short-Term Capital Gains, STCG), or 12.5% above a small annual exemption if you held it longer (Long-Term Capital Gains, LTCG). Those rates changed on July 23, 2024 — the system models the old and new regimes correctly based on when the sell happens.

The backtester reports three numbers: "gross" (ignoring all this), "net of cost" (transaction costs subtracted), and "net of cost and tax" (including tax). The headline is always the third one. A strategy that looks brilliant gross but breaks even after costs and taxes is not actually a good strategy.

## 12. How we know if the system actually works (the backtest)

A *backtest* is a simulation: pretend it's January 2012, walk forward month by month, let the system make its monthly decision using only the data that was available at each point, accumulate the portfolio, and at the end compare:

- The system's portfolio CAGR (the average yearly growth rate) net of cost and tax, vs. the index's CAGR.
- The deepest drawdown (worst peak-to-trough loss).
- How long the system underperformed the index continuously.

Three rules keep this honest:

- **Train / validation / holdout split.** We use 2012–2018 to develop the strategy, 2019–2022 to choose between strategy variants, and **2023–2024 is locked**. The holdout is touched once — only to verify a single pre-registered strategy. You can't tweak a strategy until it works on holdout, because that's just slow overfitting.
- **Block bootstrap confidence intervals.** Monthly returns are autocorrelated. Naive statistics overstate confidence. Block bootstrap (resample 12-month chunks) is the honest way to put error bars on the result.
- **Style-adjusted alpha.** If the system happened to drift toward small-cap stocks during a small-cap rally, that's not skill — that's a passive style bet. We decompose the portfolio's return into "market exposure," "size tilt," "value tilt," "momentum tilt," and a residual. The residual is the actual selection skill we're measuring.

If a strategy variant cannot beat the benchmark net of cost and tax, with bootstrap-positive lower confidence, on a locked holdout, **it does not get promoted**. The current default stays in place.

## 13. The safety brakes

Several brakes prevent the system from doing anything dramatic:

- The 20% index floor. Until the holdout test confirms it, we never put less than ₹5,000 into the index, no matter what. Single overconfident months can't blow up the strategy.
- The single-shot holdout rule. We test the *single* pre-registered strategy on holdout. If it fails, the holdout is "burned" — we can't try a second strategy on it. A new holdout requires waiting for new data.
- The fail-loud rule. Missing data is null, never zero. Unsupported corporate actions (rare events like complex mergers) make the backtest stop, not silently mis-price. Source conflicts are logged. Validity test failures block promotion. There is no override.
- The LLM rule. Large language models can extract evidence with citations. They cannot produce numeric scores or judge whether a stock is a good buy. All the numeric machinery is deterministic.

## 14. The day-to-day workflow (once everything is wired up)

Once the system is fully running on real data, the monthly cycle looks like this:

1. **Data refresh.** The latest prices, the most recent quarterly results, any new corporate actions, any new filings — all loaded into the database. Each row carries source metadata (where it came from, when it was ingested, what it hashes to).
2. **Compute features.** For every company in the universe at today's date, the PIT loader produces all the relevant inputs and the feature engines compute the eight sub-scores plus the cohort expected alpha.
3. **Score candidates.** Each candidate gets a Monthly Buy Score. Candidates with fatal governance flags are rejected.
4. **Compute the Portfolio Edge Score.** The PES summarises whether this month is a "go aggressive" or "stay defensive" month.
5. **Build the deployment plan.** Index/active split, candidate ranking, ticket sizes, whole-share rounding, residuals.
6. **Persist.** The plan is saved to the database. Each individual decision is also saved to `historical_predictions` with a *feature snapshot hash* — a fingerprint of the inputs used to make the decision, so a future replay can verify reproducibility.
7. **Generate the report.** A Markdown file is produced explaining the month: PES breakdown, every action, every rejected candidate, why active vs. why index, and a watchlist for next month.
8. **Human reviews and decides.** The human reads the report and chooses to act on it (or not). The system **does not** auto-execute trades. It is decision support, not an autopilot.

12 months later, when the forward returns of those decisions are known, the *historical outcomes* table is populated, and the *mistake analyzer* surfaces patterns: "the system tends to overestimate small-cap names in bear markets," that sort of thing. Those insights feed the next round of strategy variants in the *champion-challenger* framework.

## 15. What's been built so far in this repo

In approximate order:

- The seven methodology documents under `docs/`. They lock the formulas and rules so future work doesn't drift.
- The repository skeleton: package layout, dependencies, build, lint, test, type-check, import-rule enforcement, database setup, migrations.
- Manual ingestion of the data types listed above (companies, prices, quarterly financials with restatement support, corporate actions, index constituents, filings metadata, portfolio holdings and tax lots, plus the delisted-companies seed list).
- The PIT loader: the eleven canonical functions that everyone consumes.
- Adjusted prices (handling splits, bonuses, dividends; refusing to silently mis-price the rare events).
- Feature engines: business quality, earnings acceleration, valuation sanity, technical, liquidity, sector tailwind, governance safety, evidence quality.
- Cohort expected alpha (the formula and statistics; the cohort *builder* that walks PIT data is the next piece to wire up).
- Monthly Buy Score and Portfolio Edge Score.
- Deployment engine with whole-share rounding and PES-based split.
- Cost model, tax model, FIFO tax-lot accounting, and the monthly-SIP backtester.
- Bootstrap confidence intervals, bucket calibration, decile monotonicity, survivorship gap analysis.
- Markdown monthly report generator.
- Mistake analyzer and champion-challenger gating logic.
- A Streamlit UI placeholder (read-only dashboard skeleton).
- 123 automated tests, all green; lint checks all green; module-dependency rules enforced.

## 16. What's still ahead

- Wiring the cohort *builder* to produce CohortObservations from real PIT data. Today the formula exists; the data feed into it is the next step.
- Wiring the live `monthly` command to the real PIT layer so the engines compose end-to-end on actual data, not just synthetic test fixtures.
- Building out the Streamlit dashboard pages (deployment plan viewer, portfolio review, backtest summary).
- Automated daily / weekly data refresh (today's loaders are run by hand; production needs a scheduled refresh).
- Curating the delisted-companies seed list with confirmed dates and last-traded symbols. The names are listed; the verified metadata still has to be filled in from primary sources.
- A small evidence retriever (linking each prediction to source PDFs / filings; full RAG/LLM extraction is the very last phase, intentionally deferred).

## 17. The one-sentence summary

This system tells you, every month, where to put ₹25,000 of your own money — and the most important thing it can tell you is "just buy the index this month." When it tells you anything else, it is required to explain why, in numbers and in evidence, and to be testable against history with no peeking at the future.

That's the whole project.
