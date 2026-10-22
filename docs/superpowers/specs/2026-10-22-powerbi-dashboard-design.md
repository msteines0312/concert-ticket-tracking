# Power BI Dashboard Design

Date: 2026-10-22. Phase 3, deliverable 1 of 4 (dashboard, talent buyer brief, AI collaboration log, README).

## Intent

The dashboard is for a talent buyer checking a specific artist before booking a room, and for anyone
(buyer or hiring manager) who wants the general lesson. Matt's framing: show which metrics lead to a
sellout rather than overbooking an artist into too big a space, and keep a brief run on the Billboard
charts from making a buyer overconfident about where an act can play.

The Phase 2 results support that framing:

- Recent chart signals (52 weeks before the 6-month booking cutoff) did not predict sellouts on later
  years. Test AUC 0.52 to 0.60, charts block Wald p = 0.27, sellout rate roughly flat across chart deciles.
- Room size relative to the previous tour, interacted with how full that previous tour was, held up.
  Upsizing after a tour that was not nearly full is the risky case (break-even about 93% full after the
  noise review, survives leave-one-tour-out).
- Right-sizing flags: 193 shows / 18 tours have at least one flagged show, 66.8% sold out vs 79.5% for the
  rest. The dashboard uses a stricter tour rule (see page 1), so its figures will differ.

## Goals

- Page 1 teaches the rule in under a minute.
- Page 2 lets a buyer look up one artist and see their room history and hype vs. outcome.
- Matt builds it himself as a guided Power BI lesson (first time using Power BI; Tableau background).
  Each step maps to the Tableau concept he knows: Power Query vs. data source prep, model relationships
  vs. Tableau relationships, DAX measures vs. calculated fields, drill-through vs. dashboard actions.

## Non-goals

- No sellout probabilities or model scores shown as forecasts. The model barely beats chance on later
  years, so a "73% chance" tile would overstate what it knows.
- Not a catalog of everything in the database. Every visual serves the argument.
- No Pollstar rows (copyrighted). Wikipedia / Wikimedia derived data only.

## Anti-goals (would be a failure even if it works)

- The dashboard quietly fills gaps with chart buzz, doing the thing it warns against.
- A recruiter clones the repo and can't open it without installing extra software.

## Layout (Matt's decision: option C, two pages, drill-through)

### Page 1: Before you upsize

- Headline text: moving an act into a bigger room only paid off when their last tour was about 93%+ full.
  The number must come from the current break-even in the pipeline, not be typed by hand.
- Sellout-rate grid (matrix with conditional formatting): rows = previous-tour fill bucket
  (Under 90%, 90-95%, 95-99.9%, 100%), columns = room change (smaller, same, up to 2x, 2x+), cells = sellout rate
  with show count.
- Chart buzz panel (Matt accepted the recommendation after the builder check): test AUC for controls only
  vs. controls + chart signals, on the 2019 and 2022-25 tests. Caption: "Charts look like they matter, but
  they barely improve the forecast once you account for room size and market." (Matt changed "genre" to "market" in planning: genre is no longer a predictive control.) Correction: an earlier draft
  said the raw sellout-by-chart-decile view was flat. It is not (Billboard 200: 60.6% with no chart points to
  85.1% in the top decile), because bigger acts and later years both chart more and sell out more. The raw
  view is not shown.
- Flagged tours table: artist, tour, median room ratio, previous tour fill, sellout rate. Right-click a
  row to drill through to page 2. A tour is flagged when 50% or more of its shows were upsized past the
  rule (share_upsized_past_rule >= 0.5): 13 tours. The "any flagged show" rule (18 tours) included tours
  that mostly downsized (Noel Gallagher, Linkin Park). Headline counts and rates are recomputed from this rule.
- Grid buckets (Claude's call): "same room" = room ratio within ±10% of the previous tour; the "100%" row =
  previous tour exactly 100% full, matching the sellout definition.

Matt approved page 1 contents as proposed ("all good"), then the changes above.

### Page 2: Artist check (drill-through target, also usable via an artist slicer)

Grain (Matt accepted the recommendation): the page is about one tour. Drill-through key = tour. When a
buyer picks an artist from the slicer instead, the page shows that artist's latest tour, with a tour
slicer to switch. Tiles and hype vs. outcome are per tour; the timeline covers the whole career.

Timeline scope (Claude's calls): every tour by the artist is drawn, including previous tours outside
the US + Canada sample, so the "last tour" tile points at a visible bar. The chart strip covers the whole
career.

After the final code review (Matt accepted the recommendations): the first build used tour_summary, which
is US + Canada only, so 7 previous tours (Halsey's Manic World Tour, Drake's Assassination Vacation Tour)
had no bar, and the tiles and timeline described the same tour with different numbers (Niall Horan: 78.3%
vs 50.8% full). Now:
- Timeline tours come from the same usable worldwide history the model uses for previous tours, with fill
  as an unweighted mean of shows, so a previous tour's bar matches the tiles.
- The tiles are labeled "at booking time": they count only shows finished before the booking cutoff, so a
  previous tour still running at booking can differ slightly from its bar.
- "What happened" uses the tour's US + Canada model-sample shows (sample_sellout_rate, sample_fill_rate)
  with the show count next to it, since some tours have only one sample show.
- Artist names show a display name without Wikipedia's disambiguator ("Halsey", not "Halsey (singer)").

Top, scorecard (Matt: scorecard on top, timeline below):
- Tiles: last tour fill rate, room vs. last tour (ratio), upsize risk flag.
- Side by side: "Hype going in" (52w chart points, top-10 weeks, pageviews) vs. "What happened"
  (sellout rate, average fill).

Bottom, career timeline:
- One mark per tour on a time axis: median room size (bar) and fill rate (dot).
- Chart activity strip underneath on the same time axis.

No previous tour (121 of 240 tours): Matt's decision. The first two tiles are replaced by a
"No previous tour to compare" note and a career chart history tile (career Hot 100 / Billboard 200 lead
entries) with the caption "weak signal: use as context, not a forecast." Career history was the one chart
signal with some support (block p = 0.053 overall, 0.0001 in the history sample), so it is the most
defensible stand-in, but it is labeled as weak.

### Footer (both pages)

Source credits: Wikipedia tour articles (CC BY-SA, link to docs/wikipedia_sources.csv), Billboard charts via
utdata/rwd-billboard-data, Wikimedia pageviews. No Pollstar.

## Data connection (Matt's decision: CSV export)

- A new pipeline step writes the tables the dashboard needs to `data/dashboard/*.csv` from
  `concert_demand.db`. Power BI loads them with the built-in Text/CSV connector.
- A Power Query parameter holds the folder path so anyone who clones the repo can point the `.pbit`
  at their own copy.
- Rejected: SQLite ODBC driver (every viewer would need a third-party driver).
- The export also writes the current break-even fill (0.929 today) so the headline is never typed by hand.
  It is only computed in robustness.room_effect right now.
- Committed (Matt accepted the recommendation): the small aggregated dashboard CSVs, through a .gitignore
  exception for data/dashboard/, so the .pbit opens without running the pipeline. This changes the README
  line "No data files are committed." Licensing: Wikipedia-derived columns are CC BY-SA (fine with
  attribution). Billboard chart data is © Billboard (only the archive code is MIT), so committed files hold
  aggregates only (points and entry counts per tour or per quarter), never weekly ranks or song titles.

## Constraints

- Sample: model-ready US + Canada shows (model_dataset / right_sizing_shows), consistent with Phase 2.
- Commit the `.pbit` template plus screenshots / GIF in the README. `.pbix` is gitignored.
- Add `.superpowers/` to `.gitignore` (brainstorm mockups live there).
- CLAUDE.md copy rules apply to every label and caption (no em dashes).
- Decisions get logged in docs/ai_collaboration_log.md.

## Left to the builder

- Exact list and shape of exported CSVs (star schema with an artist / tour dimension is expected).
- Which DAX measures exist and how they're named.
- Visual types within the layout above, colors, and theme.
