# Soft signals: an exhaustive taxonomy and how each one enters the system

This document catalogues every qualitative / "soft" factor that can
move Indian equity prices, organised by category, with the specific
integration point in the existing engine for each. The discipline is
that no soft signal becomes a numeric score on its own — it always
flows through one of five deterministic rails:

1. **Sector tailwind score** (per scoring_methodology.md section 4.1):
   currently a placeholder of 50. This is where macro-sector signals
   land (e.g., a PLI scheme bumps the affected sector).
2. **Market regime classifier** (engines/market_regime.py): currently
   uses index price + breadth + vol. This is where macro / geopolitical
   inputs land.
3. **Evidence Quality score** (scoring_methodology.md section 2):
   conflicting news, unverified text, missing or stale data lower it.
4. **Governance Safety - textual tier** (scoring_methodology.md
   section 9.1): auditor news, regulatory orders, ED / SEBI notices
   etc. flag for human review (never auto-reject).
5. **Earnings acceleration** (existing): post-earnings revisions /
   guidance changes already affect this via the structured numbers.

The LLM extracts facts from filings and news. The deterministic
scoring engines consume those extracted facts. **The LLM never
produces a buy/sell recommendation or a numeric score.** That
separation is the architectural rule from `architecture.md` section 4.

What follows is the full taxonomy. For each item: a one-line
description, a typical example, and the rail it plugs into.

## 1. Global macro and central bank policy

These move FII flows, INR, valuations, and risk appetite. They
primarily feed the **market regime classifier** because they shift
the whole market, not specific names.

- **US Federal Reserve policy** — FOMC decisions, dot-plot moves,
  Powell speeches. Hawkish surprises tighten EM liquidity and pull
  FII money out; dovish pivots reverse that. Rail: market regime.
- **ECB / BOJ / PBOC policy** — global liquidity tide. Rail: market
  regime.
- **US 10-year Treasury yield** — single most important global asset
  signal for EM equity multiples. Rising yields compress P/Es. Rail:
  market regime.
- **Dollar index (DXY)** — strong dollar = EM outflow, weak rupee.
  Rail: market regime.
- **Crude oil spot price (Brent / WTI)** — India imports ~85% of its
  crude; oil shock = current account deficit pressure, INR weakness,
  inflation, RBI hawkishness. Rail: market regime + sector tailwind
  (energy up, downstream-consumer down).
- **OPEC+ production decisions** — same channel as crude.
- **Global PMI (manufacturing, services)** — leading indicator of
  global growth. Rail: market regime.
- **Yield curve inversion** (US 2Y vs 10Y) — recession proxy. Rail:
  market regime.

## 2. Geopolitical conflict and tensions

Discrete events that re-price risk in days, not quarters.

- **War / military conflict (Russia-Ukraine, Middle East,
  India-China LAC)** — moves crude, fertilisers, defence, shipping,
  semiconductors. Rail: market regime (broad risk-off) + sector
  tailwind (defence, energy up; aviation, FMCG down).
- **US-China trade and tech tensions** — affects Indian IT services
  (H1B), pharma exports to US, electronics supply chains. Rail:
  sector tailwind.
- **Sanctions regimes** — Russia oil discount, Iran oil access. Rail:
  sector tailwind (refiners directly affected).
- **Border tensions / border infrastructure announcements** — defence
  procurement orders, road and bridge contractors. Rail: sector
  tailwind.
- **Terrorism and major attacks** — short-term risk-off; airlines,
  hospitality dip. Rail: market regime + sector tailwind.
- **Energy security events** — Strait of Hormuz disruption, LNG
  shortages. Rail: sector tailwind.
- **Strategic minerals / rare earth restrictions** — affects EV
  battery supply. Rail: sector tailwind.

## 3. Indian government policy and announcements

The single richest source of sector-level tailwinds in India.

- **Union Budget (1 February each year)** — tax rate changes
  (corporate, personal, capital gains), capex announcements,
  sectoral schemes, customs duty changes, divestment targets,
  fiscal-deficit number. Rail: sector tailwind (multiple), market
  regime (fiscal stance), Evidence Quality if fields change post-
  Budget.
- **PLI (Production-Linked Incentive) schemes** — semiconductors,
  electronics, pharma, autos, textiles, drones, white goods. Sector
  beneficiaries are explicit. Rail: sector tailwind.
- **PMs' major announcements** — infrastructure pipelines (NIP),
  housing schemes, manufacturing missions, green hydrogen mission.
  Rail: sector tailwind (cement, capital goods, EPC, renewables).
- **GST council decisions** — rate changes by category move
  sector-level revenue economics. Rail: sector tailwind.
- **Disinvestment / strategic sale events** — BPCL, Air India (closed),
  IDBI, Container Corp, public sector banks. Rail: company-specific
  via filings layer; market regime if large.
- **Public sector bank recapitalisation** — affects PSU bank
  earnings power. Rail: sector tailwind.
- **Spectrum auctions (telecom)** — Reliance Jio, Bharti, Vi auction
  outcomes. Rail: sector tailwind.
- **Coal block / mining auctions** — cement, steel, power inputs.
  Rail: sector tailwind.
- **Petroleum product price decontrol or controls** — refining
  margins. Rail: sector tailwind.
- **Renewable energy policy (NIP, RPO, solar bidding)** — solar
  manufacturers, EPC, IPPs. Rail: sector tailwind.
- **Real-estate regulation (RERA, REIT rules, stamp duty changes)**
  — developers, financiers. Rail: sector tailwind.
- **Foreign Direct Investment (FDI) policy** — sector caps changing.
  Rail: sector tailwind (insurance, defence, retail).
- **Trade policy / tariffs** — anti-dumping duties, FTA changes,
  customs duty hikes / cuts. Rail: sector tailwind.
- **PM-Kisan, MGNREGA, rural welfare schemes** — rural FMCG, two-
  wheeler, tractor demand. Rail: sector tailwind.
- **Digital public infrastructure announcements (UPI, ONDC,
  AccountAggregator, DEPA)** — fintech, payments, cloud. Rail: sector
  tailwind.
- **Defence indigenisation lists, large defence orders** — HAL, BEL,
  BDL, Mazagon, Cochin Shipyard. Rail: sector tailwind, plus
  per-company filings layer for order wins.
- **Railways and metro capex** — capital goods, cement, steel,
  signalling, RVNL, IRCON. Rail: sector tailwind.
- **CGD city gas auctions** — IGL, MGL, Adani Total. Rail: sector
  tailwind.

## 4. RBI / regulatory monetary policy

- **Repo rate decisions** — bank net interest margin, real-estate,
  consumer durables. Rail: market regime (financial conditions) +
  sector tailwind (rate-sensitive sectors).
- **CRR / SLR changes** — bank liquidity. Rail: sector tailwind
  (banks).
- **Open market operations** — bond yields and INR. Rail: market
  regime.
- **Forex reserves changes / RBI INR intervention** — INR stability.
  Rail: market regime.
- **Macroprudential measures (priority sector lending, risk weights,
  unsecured-loan rules)** — bank earnings power, NBFC cost of
  funds. Rail: sector tailwind.
- **Asset Quality Review** (rare but huge) — bank NPL recognition.
  Rail: sector tailwind.

## 5. SEBI / market structure / regulation

- **F&O contract redesign** (lot sizes, expiry days, weekly index
  moves) — affects volatility regime. Rail: market regime.
- **Margin requirements / peak margin rules** — short-term liquidity.
  Rail: market regime.
- **Insider trading rule changes** — Evidence Quality input.
- **Material event disclosure thresholds** — Evidence Quality input.
- **T+1 / T+0 settlement** — operational, doesn't directly move
  prices but affects costs. Rail: cost model.
- **STT / stamp duty changes** — directly hits round-trip cost. Rail:
  cost model (`cost_tax_methodology.md`).
- **AIF / mutual fund regulations** — affects DII flows. Rail: market
  regime.
- **Short selling rules** — affects price discovery. Rail: market
  regime.
- **Index reconstitution rules / methodology changes** — directly
  affects what's in the universe. Rail: index_constituents_history.

## 6. Indian macroeconomic indicators

- **GDP and quarterly GVA prints** — growth narrative. Rail: market
  regime.
- **IIP (Index of Industrial Production)** — leading manufacturing
  indicator. Rail: sector tailwind (industrials, capital goods).
- **CPI inflation** — RBI's main mandate input. Rail: market regime.
- **WPI inflation** — input cost proxy for manufacturers. Rail:
  sector tailwind (raw-material-heavy sectors).
- **Manufacturing & Services PMI** — Rail: sector tailwind.
- **Trade deficit, current account deficit** — INR pressure. Rail:
  market regime.
- **Forex reserves** — INR support. Rail: market regime.
- **Tax collections** — fiscal stance, government spending capacity.
  Rail: market regime + sector tailwind (capex sectors).
- **Bond auction yields, G-Sec 10Y** — discount rate proxy. Rail:
  market regime.
- **Consumer sentiment surveys** — discretionary spend forecaster.
  Rail: sector tailwind.
- **Real estate price indices** — wealth-effect proxy. Rail: sector
  tailwind.
- **IPO market activity** — sentiment / risk-appetite proxy. Rail:
  market regime.
- **Mutual fund flows (equity, hybrid, debt)** — DII demand. Rail:
  market regime.
- **FII / DII flow data** — direct demand signal. Rail: market regime.
- **Festival / wedding season demand** — discretionary spend
  seasonality. Rail: sector tailwind.

## 7. Climate, weather, and natural events

- **Monsoon (IMD forecasts and outturn)** — agri output, rural FMCG,
  fertilisers, two-wheelers, tractors. Rail: sector tailwind.
- **Cyclones / floods / heatwaves** — affected supply chains,
  insurers, power demand. Rail: sector tailwind.
- **Earthquakes / industrial accidents** — plant-specific damage.
  Rail: per-company filings layer.
- **Climate transition policy** — carbon pricing, emission caps.
  Rail: sector tailwind.
- **Water stress / drought** — agri, beverages, paper. Rail: sector
  tailwind.

## 8. Pandemics and public health

- **COVID-style outbreaks** — directly affect consumer behaviour.
  Rail: market regime + sector tailwind (healthcare up; airlines,
  hotels, malls down).
- **Vaccine / drug approvals** — pharma company filings layer.
- **Antibiotic / antimicrobial regulations** — pharma. Rail: sector
  tailwind.

## 9. Election cycles

- **General elections** — big policy continuity / discontinuity
  signal. Rail: market regime + sector tailwind (depending on
  manifesto promises).
- **State elections** — affect state-specific spending, bank credit
  growth, infra projects. Rail: sector tailwind for state-exposed
  names.
- **Exit polls** — short-term volatility spike. Rail: market regime.
- **Coalition formation / government stability** — policy
  predictability. Rail: market regime.

## 10. Corporate governance — textual tier

These ALL flow through the textual-tier governance flag mechanism
(scoring_methodology.md section 9.1), which routes to **human
review**, never to auto-reject. The LLM extracts the candidate flag;
the human confirms or rejects.

- **Auditor resignation** — particularly with adverse remarks.
- **Auditor qualification of accounts** — flagged caveats.
- **CFO departure (especially abrupt or repeated)** — finance team
  instability.
- **Whistleblower complaints** — disclosed via exchanges.
- **Forensic audit announcements** — board-initiated investigations.
- **Tax raids / search and seizure** — IT / GST / ED.
- **SEBI / CCI / RBI / DGCA / DGFT / NCLT notices**.
- **ED enforcement actions** — money laundering / FEMA.
- **Class action / shareholder suits**.
- **Insider trading SEBI investigations**.
- **Related-party transaction concerns** — large RPTs without
  arms-length evidence.
- **Promoter pledge spike via news** (independent of structured
  shareholding pattern, in case timing differs).
- **Material misstatement allegations**.
- **Corporate governance ratings downgrade** (ISS, ICRA Governance,
  CRISIL Governance).
- **Independent director resignation citing governance reasons**.
- **Annual report delays or non-filing**.
- **Buyback failures, postponements, withdrawals**.
- **AGM postponements / contentious AGMs**.
- **NCLT proceedings unrelated to the company itself but affecting
  group entities**.

## 11. Sector-specific events (a partial list per sector)

### IT services
- US tech recession leading indicators (large client layoffs,
  Q-on-Q deal momentum).
- US H1B / immigration policy.
- Currency translation impact (INR depreciation = revenue tailwind).
- Large multi-year deal wins (TCV).
- Acquisitions and integrations.

### Banking and NBFCs
- NPA cycle indicators (sectoral exposure to stressed sectors).
- Asset quality reviews / RBI inspections.
- Loan growth runway (credit-to-GDP gap).
- CASA ratio movement.
- Provisioning policy changes.
- ECL transition.
- NBFC funding access (commercial paper market state).
- Small finance bank licence developments.

### Pharma
- USFDA inspections — Form 483, warning letters, import alerts,
  consent decrees. Rail: per-company filings layer (huge sub-signal
  in itself; many pharma companies' valuations hinge on plant
  status).
- Patent expiries (cliff effect).
- Generic price erosion in US.
- DPCO (Drug Price Control Order) inclusions in India.
- Biosimilar approvals.
- API import dependence (China supply risk).

### Auto and EV
- BS-VI emission norms (transition events).
- EV transition pace, FAME subsidy changes, GST cuts on EVs.
- Raw material costs (steel, lithium, semiconductors).
- Two-wheeler vs four-wheeler demand divergence.
- Tractor sales (rural proxy).
- Electric three-wheeler regulatory support.

### Energy and oil & gas
- Refining margins (Singapore GRM proxy).
- Domestic gas price formula changes.
- LNG spot prices.
- Crude oil price volatility.
- Renewables transition CapEx commitments.

### Cement
- Pricing discipline (regional cartels' fragility).
- Coal / pet coke costs.
- Construction season seasonality.
- Infrastructure CapEx pipeline.

### Telecom
- Spectrum auction outcomes (Jio / Airtel / Vi).
- AGR dues, court cases.
- Tariff hikes / floors.
- 5G rollout pace.

### FMCG
- Rural demand (monsoon-linked).
- Raw material inflation (palm oil, milk powder).
- Premiumisation trend.
- D2C / e-commerce share.

### Metals
- China demand / steel inventory cycle.
- Iron ore and coking coal prices.
- US tariffs on steel and aluminium.
- Power cost linkages.

### Realty
- Mortgage rates.
- Inventory clearance pace.
- RERA filings completion.
- Premium vs affordable housing mix.

### Infrastructure / EPC
- Government order book wins.
- Working capital cycles.
- Receivable days.
- Book-to-bill ratio.

### Insurance
- IRDAI rule changes.
- Mortality experience updates (post-COVID).
- Channel mix (bancassurance vs agency vs digital).
- New business margins (VNB margins).

### Renewable Energy
- Tariff awards in solar / wind auctions.
- Module costs (Chinese supply pricing).
- ALMM (approved list) changes.

### Defence
- Indigenisation orders.
- Order book wins (multi-year contracts).
- Export approvals.
- Capital budget allocations.

### Hotels / aviation
- Average room rates / RevPAR.
- ATF (aviation turbine fuel) prices.
- Airport passenger traffic.

### Retail
- Same-store sales growth.
- Online vs offline mix.
- Wedding / festival season.

### Logistics
- Diesel prices.
- E-way bill volumes.
- Container freight rates.

## 12. Idiosyncratic per-company events

These are the ones an attentive analyst would scan filings and news
for daily. The system already exposes a `filings` table; the LLM-
extractor populates structured fields off the raw filing text and the
extracted facts feed Evidence Quality / textual governance flag /
sector tailwind as appropriate.

- Earnings beats / misses vs consensus.
- Guidance upgrades / downgrades on concalls.
- Capacity additions / capex announcements.
- Order wins (defence, EPC, capital goods).
- Major contract terminations.
- Plant fires / accidents.
- Cyber incidents and data breaches.
- M&A announcements (acquirer and target).
- Tender offer results.
- Bonus / split / dividend announcements (already in
  corporate_actions).
- Buyback launches / closures.
- Promoter buying / selling beyond regulatory thresholds.
- Insider trading transactions disclosed under PIT regs.
- Stake sales by major institutional holders.
- Credit rating changes (CRISIL, ICRA, CARE, Fitch).
- Bond issuances and downgrades.
- Foreign currency convertible bond developments.
- Foreign listings / GDR / ADR developments.
- Annual report quality (length, audit qualification, related-party
  detail).
- Concall absentees of CEO / CFO from earnings calls.
- Concall language sentiment shift (year-on-year).
- ESG controversies (environment, labour, supply chain).
- Boycott / consumer activism episodes.
- Litigation outcomes (significant ones).
- Court rulings affecting the company sector.

## 13. Information sources, with tier per data_sources.md section 3

For each soft signal there's a matching ladder of sources. Tier order
controls what wins on conflict.

- Tier 1: NSE / BSE official announcements, RBI press releases, SEBI
  orders, Government of India press releases, IRDAI / TRAI / DGCA /
  CCI / NCLT orders.
- Tier 2: SEBI insider trading / takeover filings.
- Tier 3: Audited annual reports, AGM voting outcomes, company press
  releases on company websites.
- Tier 4: Bloomberg / Reuters / Mint / BS / ET / Moneycontrol /
  Capitaline / Screener / Trendlyne / Tijori / Smallcase research.
- Tier 5: Concall transcripts (Researchbytes, AlphaStreet), broker
  reports — per `architecture.md` section 4, LLM-extracted facts
  also count as tier 5 unless corroborated by tier 1–3.
- Tier 6: News tickers, Twitter / X, Telegram channels.

## 14. How the engine consumes these signals (the integration map)

| Signal category | Rail | Sub-rail mechanism |
|---|---|---|
| Global macro / Fed / oil | Market regime | Augment `engines/market_regime.py` to ingest macro snapshot |
| Indian govt schemes / Budget / PLI | Sector tailwind | Replace `sector_tailwind_score = 50` placeholder with a real engine that consumes a curated `sector_events` table |
| RBI policy | Market regime + sector tailwind | Same as macro for regime; `sector_tailwind` for rate-sensitives |
| SEBI rule changes | Cost model + market regime | Cost model parameters change; some flow to regime |
| GDP / IIP / PMI / inflation | Market regime | Macro snapshot |
| Monsoon, weather | Sector tailwind | Curated `weather_events` table |
| Elections | Market regime | Calendar-aware regime adjustment |
| Auditor resignation, regulatory orders | Governance textual tier | LLM-extracted, human-reviewed flag |
| Promoter / insider trading | Governance structured (existing) + textual | Already wired |
| Earnings beats / misses, guidance | Earnings acceleration (existing) | Use post-earnings revisions |
| USFDA inspections (pharma) | Sector tailwind + per-company filings | Plant-status table |
| Order wins / capex | Per-company filings | Already wired |
| News conflicts / unverified facts | Evidence Quality | Already wired |

## 15. What I am proposing to build (concrete next-phase plan)

For each rail, here's the minimal concrete implementation that lets
the soft signals flow through without violating the LLM-as-judge rule:

### 15.1 Sector tailwind engine (replaces the `50` placeholder)

A new table `sector_events` holds curated rows:

```
(id, sector, event_date, event_type, intensity, decay_days,
 source_url, parser_version, source_id, created_at)
```

`event_type` is enumerated: `pli_announcement`, `budget_allocation`,
`gst_rate_cut`, `regulatory_order`, `monsoon_outlook`, `commodity_shock`,
etc. `intensity` is a small integer in [-3, +3]. `decay_days`
controls how the event fades over time.

`sector_tailwind_score(sector, as_of_date)` then becomes:

```
score = 50 + sum_over_active_events(intensity * decay(today, event_date, decay_days))
clip(score, 0, 100)
```

The LLM populates new event rows by extracting from filings / news;
each row carries source metadata. Humans review tier-5 / tier-6
sources before they enter production.

### 15.2 Macro regime classifier expansion

Augment `engines/market_regime.py` with a `MacroSnapshot` dataclass:

```
@dataclass(frozen=True)
class MacroSnapshot:
    nifty500_above_200dma: bool
    breadth_pct: float
    vol_percentile_12m: float
    repo_rate: float
    cpi_yoy: float
    inr_usd: float
    brent_usd: float
    us10y_yield: float
    fii_net_30d: float  # Rs cr
    india_vix: float
```

The classifier rules become a documented decision tree on these
inputs. Each input has a curated source_id. Rules live in
`benchmark_methodology.md` and are version-controlled like every
other parameter set.

### 15.3 Textual governance flag pipeline

Already exists conceptually in `scoring_methodology.md` section 9.1
and `architecture.md` section 4. Concretely, build:

- `engines/textual_governance.py`: a function that consumes filings
  + news for a company and returns a list of `CandidateFlag`
  objects (LLM-extracted, with citations).
- `governance_flags` table: `is_active`, `human_review_required`,
  `human_review_status`, `description`, `evidence_document_id`
  (already in `db/models.py`).
- A reviewer CLI: `imae review-pending-flags` shows pending flags
  with citations; user accepts / rejects; accepted ones become
  fatal-tier (block allocation) or warning-tier (lower
  governance_safety_score).

### 15.4 Earnings revision and concall sentiment

Augment `earnings_acceleration_score` with a *post-earnings*
component: change in 12-month forward consensus revenue / EPS in the
30 days following an announcement. Concall transcripts feed an
LLM-extracted sentiment label (`improving / stable / deteriorating`)
with citations; the structured engine combines that with the
deterministic numbers, never alone.

### 15.5 News conflict logging

Already wired conceptually via `source_conflicts` table. The LLM
extractor logs every contradiction it sees between sources; the
deterministic Evidence Quality engine deducts points based on the
log size and the source-tier disparity.

## 16. The discipline boundary, restated

For every soft signal in this taxonomy, ask one question: *does it
become a number through a rule I can write down, or does it become a
number through someone's judgment?* Rule-based goes in. Judgment-based
flows into Evidence Quality (lowering it if it can't be corroborated)
or into the human-review queue. The LLM is allowed to do extraction
and citation. It is never allowed to produce the buy/sell verdict or
the score.

That boundary is the only thing that prevents this system from
gradually becoming yet another LLM-driven recommender, which the
methodology was deliberately written to avoid.

## 17. Implementation priority order (when you build these)

1. **Sector events table + tailwind engine** (replaces the `50`
   placeholder) — biggest single value upgrade per line of code.
2. **Macro snapshot + augmented regime classifier** — gives PES a
   real regime input on real data.
3. **Textual governance flag pipeline + reviewer CLI** — lets the
   system absorb auditor / regulator news without breaking the LLM-
   as-judge rule.
4. **Earnings revision component** — once earnings transcripts and
   broker estimates are ingested.
5. **Source-conflict driven Evidence Quality** — already half-wired;
   needs the actual LLM extractor populating the conflict log.

Each one is a self-contained PR, each one is testable in isolation,
each one preserves the architectural invariants. The catalogue above
is the universe the system can ultimately consume; this priority
order is the order in which to build the consumers.

## 18. What's NOT on this list (deliberately)

- Astrology / lunar phases / numerology. These genuinely move some
  retail-driven small-caps in India, but the methodology is empirical
  not folk; if a relationship exists it shows up in the cohort engine
  via the structural buckets without being explicitly named.
- "Insider tips" / unverified rumours. By definition they fail the
  source-tier rule and the Evidence Quality rubric.
- Anything from social media without corroboration. Tier 6, useful
  only as an early warning that *something* may be happening; the
  system will not act on it unless higher-tier sources confirm.

## 19. Honest current-state vs end-state

Currently in code:
- Sector tailwind score is a constant 50 for every sector.
- Market regime classifier uses only price-based signals (200-DMA,
  breadth, vol percentile).
- Textual governance flags are routed to human review (correct), but
  no LLM extractor yet populates candidate flags.
- Earnings revision and concall sentiment are not modelled.
- News conflict logging is wired in `source_conflicts` table but no
  ingestor populates it.

End state described in this taxonomy:
- Sector tailwind reflects real macro events with decay.
- Market regime ingests macro snapshot.
- Textual governance flag pipeline is the operating reviewer queue.
- Earnings revision and post-call sentiment feed earnings
  acceleration.
- News conflict log is populated daily and feeds Evidence Quality.

The gap is engineering work, not methodology rethink. The
methodology already says exactly how each soft signal should enter
the system. The catalogue above is the data the engineering needs to
consume — it's deliberately exhaustive so nothing material gets
missed when the catalogue is checked into the repo.
