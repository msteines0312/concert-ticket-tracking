"""Tests for parsing Pollstar year-end PDFs and matching them to Wikipedia.

Pollstar data is copyrighted, so every row here is made up. The layout
copies the real text layer: four lines per show, support acts running onto
the end of each line, and pypdf's replacement character for accents.
"""

import pandas as pd

from concert_demand.ingest.pollstar import artist_matches, match_to_wikipedia, parse_text

PDF_TEXT = """\
 Date Artist Support Tickets Sold Gross Date Artist Support Tickets Sold Gross
1
2
06/01/22 The Example Band Opener One 100,000 $9,000,000
 06/03/22 Big Stadium, Springfield, IL Opener Two
 2 shows Live Promoter
  CAP: 50,000 | 100% Sold | Tkt: 45.00 - 150.00 | 7,000,000 Euro
07/04/22 Beyonc�  40,000 $5,000,000
  Arena Of Light, Testville, UNITED KINGDOM
  Some Promoter
  CAP: 41,000 | 98% Sold | Tkt: 60.00
"""


def test_parse_text_reads_each_record():
    shows = parse_text(PDF_TEXT, chart_year=2022)
    assert len(shows) == 2
    first = shows.iloc[0]
    assert first["start_date"] == pd.Timestamp("2022-06-01")
    assert first["end_date"] == pd.Timestamp("2022-06-03")
    assert first["n_shows"] == 2
    assert first["tickets_sold"] == 100_000
    assert first["gross_usd"] == 9_000_000
    assert first["capacity_per_show"] == 50_000
    assert (first["ticket_min"], first["ticket_max"]) == (45.0, 150.0)


def test_parse_text_single_show_has_no_end_date_or_show_count():
    single = parse_text(PDF_TEXT, chart_year=2022).iloc[1]
    assert single["end_date"] == single["start_date"]
    assert single["n_shows"] == 1
    assert single["ticket_max"] == single["ticket_min"] == 60.0  # one price, no range
    assert single["pct_sold"] == 98


def test_parse_text_skips_page_furniture():
    # Column headers and bare rank numbers aren't records
    assert parse_text(" Date Artist Support\n1\n2\n", chart_year=2022).empty


def test_artist_matches_ignores_support_acts_and_lost_accents():
    assert artist_matches("The Example Band", "The Example Band Opener One")
    assert artist_matches("Beyoncé", "Beyonc�")
    assert artist_matches("Guns N' Roses", "Guns N� Roses")
    assert not artist_matches("Example", "Another Act")


def _engagement(**overrides):
    row = {"artist": "The Example Band", "first_date": pd.Timestamp("2022-06-01"),
           "last_date": pd.Timestamp("2022-06-03"), "n_shows": 2, "tickets_sold": 100_000,
           "capacity": 100_000, "sold_out": True}
    return {**row, **overrides}


def test_match_compares_whole_run_to_whole_run():
    matches = match_to_wikipedia(parse_text(PDF_TEXT, 2022), pd.DataFrame([_engagement()]))
    assert len(matches) == 1
    match = matches.iloc[0]
    assert match["complete"]
    assert match["tickets_diff_pct"] == 0
    assert match["sold_out_pollstar"]


def test_match_sums_nightly_pollstar_rows_into_one_engagement():
    # Pollstar sometimes lists each night of a run separately
    nightly = pd.DataFrame([
        {"chart_year": 2022, "start_date": pd.Timestamp(day), "end_date": pd.Timestamp(day),
         "artist_text": "The Example Band", "venue_text": "Big Stadium", "n_shows": 1,
         "tickets_sold": 50_000, "gross_usd": 1.0, "capacity_per_show": 50_000,
         "pct_sold": 100, "ticket_min": 1.0, "ticket_max": 1.0}
        for day in ["2022-06-01", "2022-06-03"]
    ])
    match = match_to_wikipedia(nightly, pd.DataFrame([_engagement()])).iloc[0]
    assert match["pollstar_rows"] == 2
    assert match["tickets_sold_pollstar"] == 100_000
    assert match["complete"]


def test_match_flags_partial_coverage_as_incomplete():
    # Wikipedia has a 3-night run, Pollstar only reports 2 of the nights
    engagements = pd.DataFrame([_engagement(n_shows=3, last_date=pd.Timestamp("2022-06-04"))])
    match = match_to_wikipedia(parse_text(PDF_TEXT, 2022), engagements).iloc[0]
    assert not match["complete"]


def test_match_requires_dates_inside_the_engagement():
    engagements = pd.DataFrame([_engagement(first_date=pd.Timestamp("2022-06-02"))])
    assert match_to_wikipedia(parse_text(PDF_TEXT, 2022), engagements).empty
