# Data Sources

Authoritative spec for which data sources are used per data type, the source-tier ordering used to resolve conflicts, the delisted-company seed list, the symbol-to-sector mapping, and the document storage rules. The Evidence Quality rubric in `scoring_methodology.md` §2.1 and the survivorship-correct universe in `backtest_validity_methodology.md` §3.1 both depend on this document.

## 1. Preamble

`india-monthly-alpha-engine` is a personal-use Indian equity capital deployment system. All numeric scores are deterministic or cohort-based; LLMs may extract evidence with citations but never produce numbers. Every ingested data point must carry source metadata sufficient to reconstruct the audit trail behind any prediction the system makes.

## 2. Conventions

Every row in every history table records:

- `source_id`: foreign key to a `sources` table that captures source URL, source type, ingestion timestamp, parser version, document hash.
- `as_known_at`: when the value first became known (per `point_in_time_methodology.md` §2). For original announcements equals the public announcement date; for restatements equals the restatement's announcement date.
- `document_hash`: SHA-256 of the underlying source document (PDF, XBRL, HTML, CSV).
- `parser_version`: version of the parser that extracted the value. Re-extraction with a new parser version creates a new row, not an update.

These four fields are mandatory across every history table. Their absence is a data-quality bug.

## 3. Source-tier ordering

The Evidence Quality rubric in `scoring_methodology.md` §2.1 references this ordering. Conflicts between sources are auto-resolved by tier: higher tier wins; lower-tier-only flags become "unverified" and route to human review for textual governance flags.

- **Tier 1**: NSE / BSE official corporate filings — regulatory disclosures, results announcements, shareholding patterns, corporate action notifications.
- **Tier 2**: SEBI disclosures — insider trading, takeover, mutual fund holdings, regulatory orders.
- **Tier 3**: Audited annual report PDF — filed with MCA or hosted on the company website. Audited financials carry the auditor's opinion and are authoritative for annual figures.
- **Tier 4**: Structured third-party — Screener, Tijori, Trendlyne, Capitaline, Moneycontrol structured data. Convenient and well-maintained, but not authoritative; used as a fallback when tier 1–3 are unavailable.
- **Tier 5**: Concall transcripts — sourced from company IR pages (primary), Researchbytes, AlphaStreet (backups). LLM-extracted facts also count as tier 5 per `architecture.md` §4.
- **Tier 6**: News — Bloomberg, Mint, Business Standard, Economic Times, ET Markets. The lowest tier; useful for surfacing developments that have not yet appeared in formal disclosures, but never authoritative.

Conflict-resolution rule: when two sources disagree on a value, the higher-tier source's value is the truth. The conflict is logged to `source_conflicts` for periodic human review. When a lower-tier source flags an issue (e.g., a news report of a possible auditor resignation) that no higher-tier source confirms, the issue is recorded as "unverified" and does not enter scoring. For textual governance flag candidates, unverified flags route to human review per `scoring_methodology.md` §2.2 and §4.3.

## 4. Per-data-type primary sources

- **Daily prices and volumes (NSE-listed)**: NSE bhavcopy daily ZIP files (https://archives.nseindia.com/products/content/sec_bhavdata_full.csv-style endpoints). Backup: BSE bhavcopy. The bhavcopy is tier-1 official.
- **Adjusted prices**: derived locally from `corporate_actions` rows. Third-party adjusted prices are not used as the canonical series. The system computes adjustment from raw splits, bonuses, dividends per `backtest_validity_methodology.md` §4.1.
- **Quarterly financial statements**: NSE / BSE corporate filings — XBRL where available, PDF parse otherwise. The tagged XBRL is preferred because it is machine-readable; PDF parses fall back to the structured tables Screener / Tijori publish (tier 4) when the XBRL is incomplete.
- **Annual reports**: company IR pages (primary) or BSE / NSE annual filings page. Stored as PDF locally with `document_hash`.
- **Filings (corporate announcements, regulatory disclosures)**: NSE corporate announcements page. Each announcement has a filing_id, filing_type, filing_date, and a downloadable PDF.
- **Index constituents and reconstitutions**: NSE Indices' monthly methodology and constituent change announcements at niftyindices.com. Stored in `index_constituents_history` with `effective_from` and `effective_to`.
- **Corporate actions** (splits, bonuses, dividends, rights, buybacks, mergers, demergers, delistings): BSE / NSE corp action announcements. Each has an ex_date, action_type, and a source document.
- **Credit ratings**: CRISIL, ICRA, CARE, Fitch India (India Ratings) public press releases. Sourced from the agency websites. Each rating action records agency, rating, outlook, publication_date, and the press release document_hash.
- **Promoter pledge**: shareholding pattern + pledge disclosures from BSE / NSE. Quarterly cadence; tier 1.
- **Concall transcripts**: company IR page (primary), Researchbytes, AlphaStreet (backups). Tier 5.
- **Insider trading disclosures**: SEBI insider trading filings via BSE / NSE (PIT regulations 2015). Tier 2.
- **Risk-free rate**: RBI weekly 91-day T-bill auction yields. Tier 1 (sovereign source).
- **CPI**: MoSPI Combined - All India monthly publication. Tier 1.

## 5. Source registry

Every ingested data point references a row in `sources` with:

- `source_id` (PK).
- `source_url`: the URL or path the data came from.
- `source_type`: enum (`bhavcopy`, `xbrl_filing`, `annual_report_pdf`, `corp_action_announcement`, `rating_press_release`, `screener_table`, `concall_transcript_pdf`, `news_article`, `nse_indices_csv`, `rbi_auction_csv`, `mospi_cpi_csv`, etc.).
- `ingestion_timestamp`: when this row was ingested.
- `parser_version`: version of the parser used to extract structured values.
- `document_hash`: SHA-256 of the source document.

Re-ingestion of the same logical source with different content produces a new `source_id` row (and increments `ingest_version`); the prior row is preserved for historical reproducibility. This makes the source registry append-only.

## 6. Delisted-company seed list

Required by `backtest_validity_methodology.md` §3.1: at least 50 known-distressed Indian equity cases with full price + financial history through their delisting / suspension event. The list is curated in `data/raw/delisted_companies/seed_list.md`. Each entry records: `company_name`, last NSE / BSE symbol, `delisting_or_distress_event_date`, `recovery_rate` (estimated proceeds as percentage of cost basis, default 0% conservative), `event_type` (NCLT, IBC resolution, voluntary delisting, regulatory delisting, suspension, recapitalisation), `source_url` for the event.

The starter list of widely-known cases — to be expanded with confirmed dates and symbols during Phase 2.5 ingestion:

Yes Bank (recapitalisation, severe distress 2020), DHFL (NCLT / IBC resolution, delisted 2021), IL&FS group entities (multiple, NCLT 2018), Jet Airways (NCLT, delisted), Cox & Kings (NCLT), Reliance Communications (NCLT, delisted), Reliance Capital (NCLT), Reliance Naval & Engineering, Reliance Home Finance, Punj Lloyd (NCLT), Bhushan Steel (resolution under IBC, acquired by Tata), Bhushan Power & Steel (IBC), Essar Steel (IBC, acquired by ArcelorMittal), Videocon Industries (NCLT, multiple group entities), Lanco Infratech (NCLT), ABG Shipyard (delisted), Educomp Solutions (NCLT), Suzlon Energy (severe distress, recovered), Karuturi Global (delisted), Gitanjali Gems (PNB fraud case, delisted), Manpasand Beverages (auditor resignation governance case), Vakrangee (governance case), PC Jeweller (governance flags), Sintex Industries (NCLT), Amtek Auto (NCLT), Ricoh India (governance), Vodafone Idea (severe distress, ongoing), Alok Industries (IBC, acquired by RIL), Monnet Ispat (IBC, acquired by JSW), Electrosteel Steels (IBC, acquired by Vedanta), Jaiprakash Associates (NCLT), Jaypee Infratech (NCLT), Unitech (regulatory action), Deccan Chronicle Holdings (delisted), Kingfisher Airlines (delisted, defunct), Era Infra Engineering (NCLT), Bombay Rayon Fashions (severe distress), Ruchi Soya (IBC, acquired by Patanjali, re-listed as Patanjali Foods), Kwality (NCLT), Geodesic (delisted), ICSA India (delisted), Uttam Galva Steels (delisted), CG Power & Industrial Solutions (governance, recovered), Talwalkars Better Value Fitness (severe distress), Coffee Day Enterprises (severe distress post-2019), Castex Technologies (NCLT), Castrol India (no — remove), Suzlon (already listed), Reliance Group financial services entities, Educomp Infrastructure, GTL Infrastructure (severe distress), McNally Bharat Engineering, Rolta India (delisted), Cox & Kings Financial Services.

This list reaches the 50-name target with widely-known cases. Specific event dates and last-traded NSE / BSE symbols are TODOs in `seed_list.md` because those facts must be verified against primary sources during ingestion, not invented in this document.

Recovery-rate curation rules:

- Default: 0% (conservative; no proceeds recovered).
- Recapitalisation case (e.g., Yes Bank): use the realised market value at the recapitalisation event date.
- IBC residual proceeds when paid (e.g., Bhushan Steel acquired by Tata at known valuation; pro-rata share to equity holders): record the actual proceeds.
- IBC equity wipeout (most cases): 0%.
- Voluntary delisting via reverse book-building: use the discovered exit price as the proceeds.
- Suspension followed by exchange removal with no recovery: 0%.

The 50-name minimum is a gate for strategy promotion. If the seed list has fewer than 50 confirmed entries, the survivorship test in `backtest_validity_methodology.md` §10.2 fails coverage and promotion is blocked.

## 7. Symbol → sector mapping

`scoring_methodology.md` §3.1 defines an 11-bucket sector taxonomy. The mapping from NIC (National Industrial Classification) codes — published by the Ministry of Statistics — to these 11 buckets:

- **financials**: NIC Section K (Financial and insurance activities) — banks, NBFCs, insurance, AMCs, exchanges, brokerages.
- **materials**: NIC Section B (Mining and quarrying) plus NIC Section C 2-digit codes 17 (paper), 19 (coke and refined petroleum products), 20 (chemicals), 22 (rubber and plastics), 23 (other non-metallic mineral products), 24 (basic metals), 25 (fabricated metal products) where the company is a basic-materials producer.
- **energy**: NIC Section B 2-digit code 06 (extraction of crude petroleum and natural gas), Section D 2-digit 35 (electricity, gas, steam supply) for power generation; oil and gas refiners straddle materials and energy and are classified by dominant revenue.
- **industrials**: NIC Section C 2-digit codes 25 (fabricated metal products) where capital-goods, 27 (electrical equipment), 28 (machinery and equipment n.e.c.), 29 (motor vehicles, trailers), 30 (other transport equipment); plus Section F (construction); plus Section H (transportation and storage) for logistics and shipping; plus capital-goods companies generally.
- **consumer_discretionary**: NIC Section C 2-digit codes 13 (textiles), 14 (apparel), 15 (leather), 16 (wood), 31 (furniture), 32 (other manufacturing including jewellery, watches); Section G (wholesale and retail trade) for retail; Section I (accommodation and food services); Section R (arts, entertainment, recreation) for media/hospitality; auto OEMs (29) when consumer-facing.
- **consumer_staples**: NIC Section C 2-digit codes 10 (food products), 11 (beverages), 12 (tobacco); FMCG manufacturers and packaged-food companies.
- **healthcare**: NIC Section C 2-digit codes 21 (pharmaceuticals); Section Q (human health and social work activities) for hospitals and diagnostics.
- **IT**: NIC Section J 2-digit codes 62 (computer programming, consultancy), 63 (information service activities); IT services, products, BPM, KPO.
- **communications**: NIC Section J 2-digit codes 58 (publishing), 59 (motion picture / sound recording), 60 (broadcasting), 61 (telecommunications); telecom operators, towercos, broadcasters.
- **utilities**: NIC Section D (electricity, gas, steam supply) for utilities other than power generation; Section E (water supply, sewerage, waste management).
- **real_estate**: NIC Section L (real estate activities); developers, REITs, real-estate-focused construction (subset of Section F).

Edge cases — conglomerates listed under multiple NIC codes use the dominant-revenue segment from the latest annual report at `as_of_date`. Dominant means ≥ 50% of revenue; if no segment exceeds 50%, the company is tagged `conglomerate` in a separate flag and assigned to the bucket of its largest segment.

The mapping is stored in `data/raw/sector_mapping.csv` with columns `(symbol, isin, nic_code, sector_bucket, effective_from, effective_to, source_url)`. The mapping is versioned: a sector reclassification creates a new row with the new effective range; the prior row's `effective_to` is updated. Methodology changes to the bucket taxonomy require a `scoring_methodology_version` bump.

## 8. Refresh cadence

**v1 (manual)**: data is ingested manually via `make ingest` against files dropped into `data/raw/`. Each ingestion logs `source_id`, `ingestion_timestamp`, `files_loaded`, `rows_added`, `rows_updated`. The user runs ingestion before the monthly deployment cycle.

**v1.x (Phase 2.7, automated)**: scheduled ingestion. Cron-equivalent schedule:

- Daily at 18:30 IST: NSE bhavcopy + BSE bhavcopy + corp actions for the trading day.
- Weekly on Sunday at 02:00 IST: filings sweep — pull the week's corporate announcements from NSE / BSE.
- Monthly on the first business day at 09:00 IST: index reconstitution check against NSE Indices methodology page.
- Event-driven: credit rating ingestion on agency RSS feed publication.
- Quarterly within 21 days of quarter-end: shareholding patterns and quarterly results.

Automated ingestion writes the same source registry as manual ingestion; the only difference is the trigger.

## 9. Document storage rules

Raw documents (PDFs, XBRL, HTML, CSV) are stored under `data/raw/<type>/<company_id>/<filing_id>.<ext>`. For example: `data/raw/annual_reports/12345/AR_2023_24.pdf`.

Each file has a `document_hash` (SHA-256 of the file bytes). Re-storing the same logical document with different bytes (e.g., a corrected PDF) produces a new file with a new hash; the prior file is preserved. The `filings.parser_version` is incremented when the parser used to extract structured fields changes; re-extraction creates a new row.

`data/raw/` is gitignored (per `.gitignore`). The repo holds the schema and the ingestion code, not the source documents themselves. A reader who clones the repo must re-ingest from primary sources, which is correct for a personal-use system.

## 10. Source conflicts

When the system detects a value conflict between two sources for the same logical field, it logs the conflict to a `source_conflicts` table with: `(field, company_id, period_end_date, source_a_id, source_a_value, source_b_id, source_b_value, resolution, resolved_at)`. The auto-resolution (higher tier wins per §3) is applied without blocking; the log allows periodic human review.

If both conflicting sources are tier 1 (both NSE and BSE filings disagree, for example), the conflict is escalated: the row's resolution is set to `pending_human_review` and the field is marked `unverified` for scoring purposes. Such conflicts should be rare for direct equity but do occur (typo in one filing, late correction in another).

## 11. Open questions deferred to sibling docs

1. **XBRL parser pinning**: which XBRL library version handles the Indian taxonomy edge cases — `architecture.md`.
2. **Concall transcript provider quality**: Researchbytes vs AlphaStreet coverage gaps — empirical question to resolve at Phase 2.
3. **Insider-trading T+2 lag handling**: SEBI disclosures arrive with a regulatory lag; the PIT loader's `as_of_date` must respect this — `point_in_time_methodology.md`.
4. **MCA portal coverage gap**: annual reports older than 5 years are sometimes unavailable on MCA; backup is the company website or a paid archive — operational question.
5. **Rating agency RSS feed coverage**: not all agencies publish reliable feeds; some require manual scraping.
6. **Pre-2012 backfill**: the train window starts 2012, but cohort lookback uses 10y. Coverage of 2002–2012 is sparse on filings; document policy when ingesting historical periods.

## 12. Dependencies

This document is referenced by:

- `scoring_methodology.md` §2.1 (Evidence Quality rubric source-tier deductions).
- `scoring_methodology.md` §3.1 (sector buckets used in cohort matching).
- `backtest_validity_methodology.md` §3.1 (delisted-company seed list for survivorship-correct universe).
- `backtest_validity_methodology.md` §4.2 (recovery-rate curation rules).
- `point_in_time_methodology.md` (source_timestamp and as_known_at semantics depend on what the source actually publishes).
- `cost_tax_methodology.md` (specific fund / ETF instrument identifiers and exit-load schedules).
- `architecture.md` (LLM-as-tier-5 source rule, sources table schema).

Changes to this document force a re-ingestion of affected data (and therefore an `ingest_version` bump) and possibly a `scoring_methodology_version` bump if the source-tier ordering or sector taxonomy changes.
