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
- [ ] Ingest: full 2015-2025 run (in progress)
- [ ] Sanity-check the parsed output: row counts, fill rate distribution, missing dates/countries,
      co-headline share, spot-check a few tours against their pages
- [ ] Ingest: Billboard Hot 100 + Billboard 200 CSVs
- [ ] Ingest: Pollstar Top 300/200 PDFs (2019, 2022, 2023)
- [ ] Ingest: Wikipedia pageviews per artist
- [ ] Clean: country tagging for the US + Canada subset (some tables have no Country column)
- [ ] Clean: artist name normalization across sources + tests
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

## Phase 3: Deliverables
- [ ] Tableau Public dashboard
- [ ] Talent buyer brief
- [ ] README
