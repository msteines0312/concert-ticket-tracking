# Project To-Do: Billboard Charts vs. Concert Ticket Demand

## Phase 0: Data feasibility
- [x] Survey ticket sales sources (Billboard Boxscore, Pollstar, Wikipedia tour tables)
- [x] Survey chart history sources (utdata/rwd-billboard-data)
- [x] Check terms for setlist.fm, Last.fm, Billboard, MusicBrainz/ListenBrainz
- [x] Pick a scope: Wikipedia tour tables as backbone, Pollstar year-end PDFs to fill gaps and validate
- [x] Pick the outcome: two-part model (P(sellout) + fill rate when not sold out), combined into expected fill rate
- [x] Spike: Wikipedia tours 2015-2025. 1,349 tour pages, 386 with 5+ attendance rows, ~13.7K rows (rough regex count)
  - Coverage drops sharply after 2019 (2015-19: 277 tours, 2022-25: 98 tours)
  - 68% of attendance cells are exactly 100% sold, 79% are 95%+. Confirms the two-part model
- [x] Spike: Pollstar PDFs
  - Top 300 Concert Grosses (2022, 2023) has extractable text with capacity, % sold, ticket prices
  - 2019 is a Top 200 version. 2024-25 charts appear to be behind a subscription
  - Club / theatre / arena charts rank venues, not shows, and are image-only. Not usable as show data

- [x] Geography: load worldwide, main analysis on US + Canada, worldwide as robustness check
- [x] Database: SQLite

## Phase 1: Pipeline
- [x] Repo skeleton, .gitignore, requirements.txt, git init
- [x] Package setup: pyproject.toml with src layout, editable install into .venv
- [x] Clean: Wikipedia attendance parsing + tests (footnotes, header years, Total/leg rows,
      multi-night runs collapsed into engagements, fill rate capped at 100% with over_capacity flag)
- [x] Ingest: Wikipedia tour pages (MediaWiki API, cached raw JSON, artist from infobox) + tests
- [x] Ingest: retry with Retry-After / exponential backoff after hitting HTTP 429 + tests
- [x] Ingest: switched to batched wikitext + REST HTML; parity check on 99 pages = identical output
- [x] Ingest: fixed User-Agent (unidentified clients are capped at 10 req/min, compliant bots get 200)
- [x] Ingest: full 2015-2025 run. 1,349 pages, 0 rate-limit errors
- [x] Sanity-check the parsed output. Found and fixed 5 parser bugs (each with tests):
  - Total rows labeled TOTAL / Totals / Grand Total, or only in the venue column
  - Thousands separators as spaces, ", " and European periods ("120.000")
  - Year in a lower header row or the table caption (missing dates 671 -> 257)
  - One-line infoboxes: artist now read with mwparserfromhell (missing artist 487 -> 10)
  - Leg totals merged across different venues: dropped
- [x] Flags instead of deletes: is_festival (27), suspect_capacity > 100K per show (34)
- [x] Validation: 73% of tours with a page Total row match it within 0.5%. Mismatches checked
      by hand trace to the pages' own Total rows (subset totals, typos), not the parser
- Result: 13,300 engagements, 437 tours, 245 artists. Model-ready (artist + date, no flags):
  12,988 worldwide, 8,279 US + Canada (7,340 since pageviews start, Jul 2015), 69% sold out
- [ ] Validate against Pollstar rows once that ingest exists (independent check)
- [x] Ingest: Billboard Hot 100 + Billboard 200 CSVs, pinned to archive commit + tests
  - 976,949 entries: Hot 100 1958-2026, Billboard 200 1967-2026
  - Known issues (logged, not patched): 42 verbatim duplicate rows dropped; 23 incomplete
    Billboard 200 weeks before 1990; tied ranks in old charts kept; Billboard 200 has only
    100 of 200 entries since 2026-09-26 (archive scraper, cause unconfirmed). Re-check on refresh
- [ ] Ingest: Pollstar Top 300/200 PDFs (2019, 2022, 2023)
- [ ] Ingest: Wikipedia pageviews per artist
- [ ] Clean: country tagging for the US + Canada subset (some tables have no Country column)
- [x] Clean: artist name normalization + credit matching (lead vs featured) + tests
  - Canonical artist titles via Wikipedia API; package tours flagged (American Idol, Honda Civic
    Tour, Top Dawg Entertainment, Various Artists)
  - Former names from filtered Wikipedia redirects + hand-checked aliases; audit in alias_matches.csv
  - 244 of 255 tour artists matched; 212,563 credits (200,904 lead, 11,659 featured)
- [ ] Decide: Spotify Top 200 + Viral 50 (Kaggle, 2017-2021) as a streaming sub-analysis
- [ ] Load into SQLite (schema.sql)
- [ ] Features: as-of-show-date chart and pageview signals + tests (no leakage)
- [ ] SQL analysis layer (CTEs, window functions)

## Phase 2: Analysis
- [ ] Part 1: logistic regression for P(sellout)
- [ ] Part 2: model fill rate on shows that did not sell out
- [ ] Combine into expected fill rate; Tobit model as a robustness check
- [ ] Chart signal vs. pageview signal comparison
- [ ] Right-sizing score
- [ ] Robustness checks

## Licensing and attribution
- [x] README "Data Sources and Licensing" section with citations
- [ ] Source list: write wikipedia_sources.csv (title, URL, revision ID, retrieved date) for every article used
- [ ] Decide where the source list lives so it's visible on GitHub (it's metadata, not data)
- [ ] Power BI dashboard: credits on the report page, Wikipedia/Wikimedia data only, no Pollstar rows
- [ ] Brief: sources footer
- [ ] Add MIT LICENSE before making the repo public

## Phase 3: Deliverables
- [ ] Power BI dashboard (commit .pbit template + screenshots/GIF in README; .pbix is gitignored)
  - First time using Power BI (Tableau background), so build it as a guided lesson:
    Power Query, data model + relationships, DAX measures, visuals, each mapped to its Tableau equivalent
- [ ] Talent buyer brief
- [ ] docs/ai_collaboration_log.md: keep updated as decisions happen, final pass at the end
- [ ] README
