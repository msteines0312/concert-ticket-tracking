"""Tests for parsing and cleaning Wikipedia tour attendance tables.

The edge cases here come from real tour pages (Guts World Tour, ÷ Tour,
WorldWired Tour, Popestar Tour, Billy Joel in Concert).
"""

import pandas as pd
import pytest

from concert_demand.clean.attendance import (
    clean_tour_table,
    collapse_engagements,
    parse_attendance,
    parse_revenue,
    parse_show_date,
    standardize_columns,
    strip_footnotes,
)


# ---------------------------------------------------------------------------
# Cell-level parsers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Thousand Palms[c]", "Thousand Palms"),
    ("The Fillmore[11]", "The Fillmore"),
    ("January 30[l]", "January 30"),
    ("Acrisure Arena", "Acrisure Arena"),
    ("  Madrid  ", "Madrid"),
])
def test_strip_footnotes(raw, expected):
    assert strip_footnotes(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("9,998 / 9,998", (9998, 9998)),
    ("2,056 / 2,717", (2056, 2717)),
    ("1,657,377 / 1,657,377 (100%)", (1657377, 1657377)),
    ("2,800/2,800", (2800, 2800)),
    ("114,031 / 114,031[e]", (114031, 114031)),
])
def test_parse_attendance_valid(raw, expected):
    assert parse_attendance(raw) == expected


@pytest.mark.parametrize("raw", ["—N/a", "—", "N/A", "TBA", "", None, float("nan"), "4198613"])
def test_parse_attendance_missing_or_unusable(raw):
    # A bare number with no capacity ("4198613") can't give a fill rate.
    assert parse_attendance(raw) == (None, None)


@pytest.mark.parametrize("raw, expected", [
    ("$1,733,194", 1733194.0),
    ("$208,648,942", 208648942.0),
    ("$224,718[e]", 224718.0),
    ("—N/a", None),
    ("£3,000,000", None),  # non-USD revenue is not converted, so it's dropped
    (None, None),
])
def test_parse_revenue(raw, expected):
    assert parse_revenue(raw) == expected


@pytest.mark.parametrize("raw, header_year, expected", [
    ("February 23", 2024, "2024-02-23"),
    ("19 February[e]", 2018, "2018-02-19"),
    ("January 7, 2014", None, "2014-01-07"),
    ("January 7, 2014", 2020, "2014-01-07"),  # a year in the cell wins
    ("25 August 2019", None, "2019-08-25"),
])
def test_parse_show_date(raw, header_year, expected):
    assert parse_show_date(raw, header_year) == pd.Timestamp(expected)


@pytest.mark.parametrize("raw, header_year", [
    ("February 23", None),  # no year anywhere, so the date is unknowable
    ("Total", 2024),
    ("—N/a", 2024),
])
def test_parse_show_date_unparseable(raw, header_year):
    assert pd.isna(parse_show_date(raw, header_year))


# ---------------------------------------------------------------------------
# Table-level cleaning
# ---------------------------------------------------------------------------

def test_standardize_columns_maps_variants_and_reads_header_year():
    df = pd.DataFrame(columns=["Dates (2018)", "City", "Country", "Venue",
                               "Opening act(s)", "Attendance", "Box Office"])
    out, header_year = standardize_columns(df)
    assert header_year == 2018
    assert {"date", "city", "country", "venue", "attendance", "revenue"} <= set(out.columns)


def test_standardize_columns_flattens_leg_header():
    # Billy Joel's table has a second header row naming the tour leg.
    cols = pd.MultiIndex.from_tuples([("Date", "North America"), ("Venue", "North America"),
                                      ("Attendance", "North America")])
    out, header_year = standardize_columns(pd.DataFrame(columns=cols))
    assert list(out.columns) == ["date", "venue", "attendance"]
    assert header_year is None


def _raw_table():
    """A table shaped like read_html output for a Wikipedia tour page."""
    return pd.DataFrame({
        "Date (2024)": ["October 18", "October 21", "October 22", "October 25[a]",
                        "Australia", "October 30", "Total"],
        "City": ["Sydney", "Sydney", "Sydney", "Brisbane[b]", "Australia", "Perth", "Total"],
        "Country": ["Australia"] * 4 + ["Australia", "Australia", "Total"],
        "Venue": ["Qudos Bank Arena"] * 3 + ["Brisbane Ent. Centre", "Australia", "RAC Arena", "Total"],
        "Attendance": ["64,096 / 64,096"] * 3 + ["9,800 / 11,000", "Australia", "—N/a",
                                                 "87,896 / 89,096 (98.7%)"],
        "Revenue": ["$7,197,262"] * 3 + ["$900,000", "Australia", "—N/a", "$8,097,262"],
    })


def test_clean_tour_table_drops_total_and_leg_rows():
    shows = clean_tour_table(_raw_table(), tour="Guts World Tour")
    assert "Total" not in shows["venue"].values
    assert "Australia" not in shows["venue"].values
    assert len(shows) == 5


def test_clean_tour_table_parses_fields():
    shows = clean_tour_table(_raw_table(), tour="Guts World Tour")
    brisbane = shows[shows["city"] == "Brisbane"].iloc[0]
    assert brisbane["show_date"] == pd.Timestamp("2024-10-25")
    assert (brisbane["tickets_sold"], brisbane["capacity"]) == (9800, 11000)
    assert brisbane["revenue_usd"] == 900000.0
    assert brisbane["tour"] == "Guts World Tour"


def test_clean_tour_table_without_date_column_still_parses():
    # Popestar Tour has Venue / City / Attendance / Revenue only.
    df = pd.DataFrame({"Venue": ["The Fillmore[11]"], "City": ["Denver"],
                       "Attendance": ["2,240 / 3,600"], "Revenue": ["$70,322"]})
    shows = clean_tour_table(df, tour="Popestar Tour")
    assert pd.isna(shows.loc[0, "show_date"])
    assert shows.loc[0, "tickets_sold"] == 2240


# ---------------------------------------------------------------------------
# Engagement collapsing (multi-night runs)
# ---------------------------------------------------------------------------

def test_collapse_engagements_merges_repeated_multi_night_rows():
    shows = clean_tour_table(_raw_table(), tour="Guts World Tour")
    eng = collapse_engagements(shows)
    sydney = eng[eng["city"] == "Sydney"].iloc[0]
    assert sydney["n_shows"] == 3
    assert sydney["first_date"] == pd.Timestamp("2024-10-18")
    assert sydney["last_date"] == pd.Timestamp("2024-10-22")
    # The run's figure is counted once, not three times.
    assert sydney["tickets_sold"] == 64096
    assert eng["tickets_sold"].sum() == 64096 + 9800


def test_collapse_engagements_keeps_separate_runs_at_same_venue():
    # Same venue, different reported numbers means separately reported dates.
    shows = pd.DataFrame({
        "tour": ["T"] * 2, "show_date": pd.to_datetime(["2019-01-01", "2019-02-01"]),
        "city": ["New York City"] * 2, "country": ["United States"] * 2,
        "venue": ["Madison Square Garden"] * 2,
        "attendance_raw": ["18,000 / 18,000", "17,500 / 18,000"],
        "tickets_sold": [18000, 17500], "capacity": [18000, 18000],
        "revenue_usd": [2e6, 1.9e6],
    })
    assert len(collapse_engagements(shows)) == 2


def test_collapse_engagements_computes_fill_rate_and_sellout():
    shows = clean_tour_table(_raw_table(), tour="Guts World Tour")
    eng = collapse_engagements(shows).set_index("city")
    assert eng.loc["Sydney", "fill_rate"] == 1.0
    assert eng.loc["Sydney", "sold_out"]
    assert eng.loc["Brisbane", "fill_rate"] == pytest.approx(9800 / 11000)
    assert not eng.loc["Brisbane", "sold_out"]


def test_collapse_engagements_caps_fill_rate_when_over_capacity():
    # Comps or standing room can push reported attendance above capacity.
    shows = pd.DataFrame({
        "tour": ["T"], "show_date": [pd.Timestamp("2018-06-01")], "city": ["Dublin"],
        "country": ["Ireland"], "venue": ["Croke Park"], "attendance_raw": ["82,500 / 82,000"],
        "tickets_sold": [82500], "capacity": [82000], "revenue_usd": [None],
    })
    eng = collapse_engagements(shows)
    assert eng.loc[0, "fill_rate"] == 1.0
    assert eng.loc[0, "sold_out"]
    assert eng.loc[0, "over_capacity"]


def test_collapse_engagements_drops_rows_without_attendance():
    shows = clean_tour_table(_raw_table(), tour="Guts World Tour")
    eng = collapse_engagements(shows)
    assert "Perth" not in eng["city"].values
