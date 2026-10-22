# Power BI Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a small, committed set of dashboard CSVs from the pipeline, then guide Matt through building
the two-page Power BI report (rule page + tour drill-through page) himself.

**Architecture:** A new `concert_demand.dashboard` package reads `concert_demand.db` and `reports/tables/`
and writes four CSVs to `data/dashboard/` (a small star schema: artists, tours, shows, chart quarters) plus
a one-row `headline.csv`. Tasks 1-3 are Python, built and tested by Claude. Tasks 4-8 are Power BI lessons:
Matt clicks, Claude explains each step against its Tableau equivalent and checks the result.

**Tech Stack:** Python 3.13, pandas, sqlite3, pytest. Power BI Desktop (Microsoft Store build 2.159).

**Spec:** `docs/superpowers/specs/2026-10-22-powerbi-dashboard-design.md`

## Global Constraints

- No em dashes anywhere: code comments, captions, CSV headers, README, commit messages (CLAUDE.md).
- Commit messages in plain human voice, no conventional prefixes, no Co-Authored-By line (CLAUDE.md).
- NumPy-style docstrings, small single-purpose functions, match the style of `models/right_sizing.py`.
- Sample for show-level data: model-ready US + Canada shows (`model_dataset`, `right_sizing_shows`).
- No Pollstar data in any export.
- Billboard-derived columns are aggregates only (points, entry counts). Never weekly ranks or song titles.
- Flagged tour: `share_upsized_past_rule >= 0.5` (13 tours today).
- Grid buckets: room ratio "Smaller" < 0.9, "Same" 0.9 to 1.1 inclusive, "Up to 2x" > 1.1 to 2.0,
  "2x+" > 2.0. Previous-tour fill "Under 90%", "90-95%", "95-99.9%", "100%" (exactly 1.0).
- Break-even fill is read from the pipeline output, never typed by hand.
- No-previous-tour caption, exact copy: "weak signal: use as context, not a forecast"
- `.pbix` stays gitignored; `.pbit` is committed.
- Every decision Matt makes during the lessons is logged in `docs/ai_collaboration_log.md`.

## Review Focus

1. Artists whose tours are all outside the US + Canada sample except one: the tours table must still carry
   their earlier worldwide tours so the timeline is not empty. Test in Task 2.
2. A tour with a previous tour that never appears in `tour_summary` (sparse page): `prev_tour` must still
   be a plain label, not a broken relationship key. Test in Task 2.
3. Ratios exactly on bucket edges (0.9, 1.1, 2.0) and fill exactly 0.95 / 1.0 land in one documented
   bucket. Test in Task 1.
4. Artists with no chart credits at all: they get zero chart-quarter rows, and the export must not drop them
   from `artists.csv`. Test in Task 2.
5. Running the export before the model stage: fail with a clear message naming the missing input. Test in Task 3.

---

### Task 1: Save the room effect and add the bucket and flag helpers

**Files:**
- Modify: `src/concert_demand/models/right_sizing.py` (`run`: also write `reports/tables/room_effect.csv`)
- Create: `src/concert_demand/dashboard/__init__.py`, `src/concert_demand/dashboard/buckets.py`
- Test: `tests/test_dashboard_buckets.py`, add one test to `tests/test_right_sizing.py`

**Interfaces:**
- Produces: `reports/tables/room_effect.csv` with one row: `room_main, room_interaction, interaction_p, break_even_fill`
- Produces: `room_change_bucket(ratio: pd.Series) -> pd.Series` (str labels, NaN stays NaN)
- Produces: `prev_fill_bucket(fill: pd.Series) -> pd.Series` (str labels, NaN stays NaN)
- Produces: `is_flagged_tour(share_upsized: pd.Series, threshold: float = FLAG_THRESHOLD) -> pd.Series` (bool)
- Constants in `buckets.py`: `FLAG_THRESHOLD = 0.5`, `ROOM_ORDER`, `FILL_ORDER` (label lists in display order)

- [ ] **Step 1: Write the failing tests**

```python
def test_room_bucket_edges():
    ratios = pd.Series([0.5, 0.9, 1.0, 1.1, 1.11, 2.0, 2.01, np.nan])
    assert room_change_bucket(ratios).tolist()[:7] == [
        "Smaller", "Same", "Same", "Same", "Up to 2x", "Up to 2x", "2x+"]
    assert pd.isna(room_change_bucket(ratios).iloc[7])

def test_fill_bucket_edges():
    fills = pd.Series([0.80, 0.90, 0.95, 0.999, 1.0])
    assert prev_fill_bucket(fills).tolist() == ["Under 90%", "90-95%", "95-99.9%", "95-99.9%", "100%"]

def test_flag_threshold_is_half_or_more():
    assert is_flagged_tour(pd.Series([0.0, 0.49, 0.5, 1.0])).tolist() == [False, False, True, True]
```

Bucket rule for fill: "90-95%" is 0.90 up to but not including 0.95; "95-99.9%" is 0.95 up to but not including 1.0.

In `tests/test_right_sizing.py`, add `test_run_saves_room_effect` only if `run` can be exercised cheaply;
otherwise assert in Task 3's verification that the file exists with the four columns (executor's call).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_buckets.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `buckets.py`; in `right_sizing.run`, write `pd.DataFrame([effect])` to `room_effect.csv`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_buckets.py tests/test_right_sizing.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/concert_demand/dashboard src/concert_demand/models/right_sizing.py tests/test_dashboard_buckets.py
git commit -m "Save the room effect and add dashboard bucket and flag rules"
```

### Task 2: Build the four dashboard tables

**Files:**
- Create: `src/concert_demand/dashboard/tables.py`
- Test: `tests/test_dashboard_tables.py`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces, all pure functions on DataFrames (no I/O):
  - `build_shows(model_dataset, right_sizing_shows) -> DataFrame`. One row per model-sample show. Columns:
    `engagement_id, tour_key, first_date, capacity_per_show, sold_out, fill_rate, room_ratio,
    room_change_bucket, prev_fill_bucket, upsized_past_rule`. Room columns null when no previous tour.
  - `build_tours(tour_summary, engagements, right_sizing_tours, model_dataset) -> DataFrame`. One row per
    worldwide tour by any artist in the model sample. Columns: `tour_key, artist, tour, tour_start,
    median_room, sellout_rate, fill_rate, in_sample, has_prev_tour, prev_tour, median_room_ratio,
    prev_tour_fill_rate, share_upsized_past_rule, is_flagged, is_latest_in_sample,
    hot100_points_52w, hot100_top10_52w, billboard200_points_52w, pageviews_52w, career_entries`.
    `tour_key = artist + " | " + tour`. `median_room` = median `capacity_per_show` from `engagements`.
    Hype columns = median over the tour's model-sample shows (null for out-of-sample tours).
    `career_entries` = Hot 100 + Billboard 200 lead career entries at the tour's first sample show.
    `is_latest_in_sample` = the artist's in-sample tour with the latest `tour_start`.
  - `build_artists(tours, artists_table) -> DataFrame`: `artist, genre_group, latest_tour_key`, one row per
    artist with at least one in-sample tour.
  - `build_chart_quarters(chart_credits, artists) -> DataFrame`: `artist, quarter_start, chart, lead_points`.
    Lead role only, points = chart size + 1 - rank (same rule as `features/signals.py`; Hot 100 size 100,
    Billboard 200 size 200), summed per calendar quarter. No rank or title columns.

- [ ] **Step 1: Write the failing tests** (small hand-made frames, style of `tests/test_right_sizing.py`)

  - `test_tours_keep_out_of_sample_previous_tours`: an artist with one worldwide-only 2014 tour and one
    in-sample 2019 tour yields two rows, `in_sample == [False, True]`.
  - `test_prev_tour_missing_from_summary_is_a_label_only`: `prev_tour = "Ghost Tour"` absent from
    `tour_summary` keeps the text, and no `tour_key` row is invented for it.
  - `test_flagged_matches_half_rule`: shares 0.4 and 0.6 give `is_flagged == [False, True]`.
  - `test_latest_in_sample_is_one_per_artist`: `tours.groupby("artist")["is_latest_in_sample"].sum()` is all 1
    for in-sample artists.
  - `test_artist_without_chart_credits_is_kept`: present in `build_artists`, zero rows in `build_chart_quarters`.
  - `test_chart_quarters_have_no_ranks_or_titles`: `set(columns) == {"artist", "quarter_start", "chart", "lead_points"}`,
    and a #1 Hot 100 week contributes 100 points.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_tables.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement the four builders in `tables.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_tables.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/concert_demand/dashboard/tables.py tests/test_dashboard_tables.py
git commit -m "Build the dashboard star schema tables from the database"
```

### Task 3: Export runner, headline numbers, committed CSVs

**Files:**
- Create: `src/concert_demand/dashboard/export.py`, `src/concert_demand/dashboard/__main__.py`
- Modify: `.gitignore` (add `!data/dashboard/`, `!data/dashboard/**`, and `.superpowers/`),
  `src/concert_demand/paths.py` (`DASHBOARD_DIR = DATA_DIR / "dashboard"`)
- Test: `tests/test_dashboard_export.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 functions; `reports/tables/room_effect.csv`, `reports/tables/sellout_ladders.csv`.
- Produces: `run(db_path=DB_PATH, tables_dir=TABLES_DIR, out_dir=DASHBOARD_DIR) -> dict[str, DataFrame]`,
  writing `artists.csv, tours.csv, shows.csv, chart_quarters.csv, chart_test.csv, headline.csv`.
  - `chart_test.csv`: rows of `sellout_ladders.csv` where `ladder == "charts_first"` and
    `step in {"controls", "controls+charts"}`; columns `test_split, step, auc, auc_low, auc_high, test_tours`.
  - `headline.csv`, one row: `break_even_fill, flag_threshold, flagged_tours, flagged_shows,
    flagged_sellout_rate, other_sellout_rate` (rates over shows in `shows.csv`, flagged = show's tour is flagged).
  - Usage: `python -m concert_demand.dashboard`

- [ ] **Step 1: Write the failing tests**

  - `test_missing_model_output_names_the_file`: with an empty `tables_dir`, `run` raises `FileNotFoundError`
    whose message contains `room_effect.csv` and `python -m concert_demand.models`.
  - `test_chart_test_keeps_two_steps_per_split`: from a fixture ladder CSV, 4 rows (2 splits x 2 steps).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_export.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `export.run` and `__main__.py`, edit `.gitignore` and `paths.py`**

- [ ] **Step 4: Run the full suite, then the real export**

Run: `.venv/Scripts/python -m pytest -q` → all PASS.
Run: `.venv/Scripts/python -m concert_demand.models` (rebuilds `room_effect.csv`, ~4 min), then
`.venv/Scripts/python -m concert_demand.dashboard`.
Expected: `headline.csv` shows `flagged_tours == 13` and `break_even_fill` about 0.929; `git status`
lists the six CSVs as untracked (gitignore exception works); total size under 2 MB.

- [ ] **Step 5: Spot-check against the database**

Pick Halsey's Love and Power Tour: `tours.csv` row matches `right_sizing_tours` on room ratio, previous-tour
fill and sellout rate; `is_flagged` is True. Report the check to Matt.

- [ ] **Step 6: Commit**

```bash
git add .gitignore src/concert_demand/paths.py src/concert_demand/dashboard tests/test_dashboard_export.py data/dashboard
git commit -m "Export the dashboard tables to committed CSVs"
```

### Task 4 (lesson, Matt builds): Power Query load with a folder parameter

Tableau equivalent: connecting to text files in the Data Source pane, plus a parameter.

- [ ] Matt creates parameter `DashboardFolder` (text) and loads the six CSVs through Get Data > Text/CSV,
      then edits each query's Source step to use `DashboardFolder & "tours.csv"` and so on.
- [ ] Matt checks the column types Power Query guessed (dates, decimals, booleans) and fixes any wrong ones.
- [ ] Check: Close & Apply succeeds; the Data view shows 13 rows where `is_flagged` is true.

### Task 5 (lesson): Data model and DAX measures

Tableau equivalent: relationships in the logical layer; measures are calculated fields that aggregate.

- [ ] Relationships: `artists[artist]` 1-to-many `tours[artist]` and `chart_quarters[artist]`;
      `tours[tour_key]` 1-to-many `shows[tour_key]`. `chart_test` and `headline` stay unrelated.
- [ ] Sort-by-column: bucket labels sorted in display order (Matt adds a small order column in Power Query).
- [ ] Measures Matt writes (names fixed so pages can reference them): `Sellout Rate`, `Avg Fill`, `Shows`,
      `Break Even Text` (formats `headline[break_even_fill]` as a whole percent for the headline).
- [ ] Check: a scratch table of `Sellout Rate` by `tours[is_flagged]` matches `headline.csv`.

### Task 6 (lesson): Page 1, "Before you upsize"

- [ ] Headline card bound to `Break Even Text`.
- [ ] Matrix: rows `prev_fill_bucket`, columns `room_change_bucket`, values `Sellout Rate` + `Shows`,
      background color scale on `Sellout Rate`.
- [ ] Chart test panel: clustered bars of `auc` by `test_split` and `step`, error bars from `auc_low` / `auc_high`,
      0.5 reference line. Caption (see copy note at the end).
- [ ] Flagged tours table filtered to `is_flagged = True`.
- [ ] Check: grid cell counts sum to the number of shows with a previous tour.

### Task 7 (lesson): Page 2, "Artist check", with drill-through

Tableau equivalent: dashboard filter actions to a second sheet.

- [ ] Drill-through field `tours[tour_key]`; artist slicer plus tour slicer that defaults to `is_latest_in_sample`.
- [ ] Tiles: last tour fill, room vs. last tour, upsize risk. When `has_prev_tour` is false, a measure-driven
      card shows "No previous tour to compare" and a career entries card with the caption
      "weak signal: use as context, not a forecast".
- [ ] Hype going in vs. what happened cards.
- [ ] Timeline: `tours` by `tour_start`, columns = `median_room`, line or markers = `fill_rate`; chart strip below
      from `chart_quarters` on a matching date axis.
- [ ] Check: right-click Halsey Love and Power on page 1 lands on page 2 with the flag tile set; an artist with no
      previous tour shows the fallback cards.

### Task 8: Credits, template, screenshots, README

- [ ] Footer text box on both pages: Wikipedia tour articles (CC BY-SA 4.0, link to `docs/wikipedia_sources.csv`),
      Billboard charts via utdata/rwd-billboard-data (chart data © Billboard, aggregates only), Wikimedia Pageviews (CC0).
- [ ] Matt exports `reports/dashboard/concert_demand.pbit`; screenshots of both pages to `reports/dashboard/`.
- [ ] README: replace "No data files are committed to this repo" with a line naming `data/dashboard/` as the
      one committed, aggregated exception; add a "Dashboard" section with screenshots and open steps.
- [ ] Update `tasks/todo.md` and log Matt's lesson decisions in `docs/ai_collaboration_log.md`.
- [ ] Commit: `git commit -m "Add the Power BI dashboard template, screenshots and README section"`

## Copy note (resolved: Matt chose "room size and market")

The approved caption says "once you account for room size and genre." Genre is no longer in the
predictive controls (noise review: explanatory models only). The controls are room size, venue size class
and country. Proposed: "Charts look like they matter, but they barely improve the forecast once you account
for room size and market." Also, on the 2019 test charts add +0.088 AUC with a wide interval (-0.10 to
+0.27), and +0.001 on 2022-25, so the panel shows the intervals rather than hiding the 2019 bump.
