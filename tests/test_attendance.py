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
    # Separator variants found in the full 2015-2025 run
    ("26,922 / 31 580", (26922, 31580)),         # space as thousands separator
    ("26,922 / 31 580", (26922, 31580)),    # non-breaking space
    ("18,309 / 21, 000", (18309, 21000)),        # stray space after the comma
    ("105,249 / 120.000", (105249, 120000)),     # European period separator
    ("12,371 / 12.371", (12371, 12371)),
    ("1.234.567 / 1.300.000", (1234567, 1300000)),
])
def test_parse_attendance_valid(raw, expected):
    assert parse_attendance(raw) == expected


@pytest.mark.parametrize("raw", ["\u2014N/a", "\u2014", "N/A", "TBA", "", None, float("nan"), "4198613"])
def test_parse_attendance_missing_or_unusable(raw):
    # A bare number with no capacity ("4198613") can't give a fill rate.
    assert parse_attendance(raw) == (None, None)


@pytest.mark.parametrize("raw, expected", [
    ("$1,733,194", 1733194.0),
    ("$208,648,942", 208648942.0),
    ("$224,718[e]", 224718.0),
    ("\u2014N/a", None),
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
    ("\u2014N/a", 2024),
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


def test_standardize_columns_finds_year_in_lower_header_row():
    # Maroon V Tour: header levels are Date, then 2015, then the leg name
    cols = pd.MultiIndex.from_tuples([("Date", "2015", "Leg 1"), ("Venue", "2015", "Leg 1"),
                                      ("Attendance", "2015", "Leg 1")])
    out, header_year = standardize_columns(pd.DataFrame(columns=cols))
    assert list(out.columns) == ["date", "venue", "attendance"]
    assert header_year == 2015


@pytest.mark.parametrize("label", ["Total", "TOTAL", "Totals", "Grand Total",
                                   "Totals for the tour", "Total[a]"])
def test_clean_tour_table_drops_all_total_row_variants(label):
    df = pd.DataFrame({"Date (2016)": ["May 1", label], "Venue": ["Arena", label],
                       "City": ["Austin", label],
                       "Attendance": ["9,000 / 10,000", "2,486,058 / 2,520,141"]})
    shows = clean_tour_table(df, tour="T")
    assert len(shows) == 1
    assert shows.loc[0, "venue"] == "Arena"


def test_clean_tour_table_keeps_venue_names_containing_total():
    # Only labels that *are* a total should match, not venues that mention one
    df = pd.DataFrame({"Date (2016)": ["May 1"], "Venue": ["Total Energies Stadium"],
                       "City": ["Paris"], "Attendance": ["9,000 / 10,000"]})
    assert len(clean_tour_table(df, tour="T")) == 1


def test_clean_tour_table_uses_caption_year_as_fallback():
    # One on One (tour): plain "Date" header, year only in the caption
    df = pd.DataFrame({"Date": ["13 April"], "Venue": ["Save Mart Center"],
                       "City": ["Fresno"], "Attendance": ["11,976 / 11,976"]})
    shows = clean_tour_table(df, tour="One on One (tour)", fallback_year=2016)
    assert shows.loc[0, "show_date"] == pd.Timestamp("2016-04-13")


def test_header_year_beats_caption_year():
    df = pd.DataFrame({"Date (2017)": ["13 April"], "Venue": ["X"], "City": ["Y"],
                       "Attendance": ["1,000 / 1,000"]})
    shows = clean_tour_table(df, tour="T", fallback_year=2016)
    assert shows.loc[0, "show_date"] == pd.Timestamp("2017-04-13")


def _raw_table():
    """A table shaped like read_html output for a Wikipedia tour page."""
    return pd.DataFrame({
        "Date (2024)": ["October 18", "October 21", "October 22", "October 25[a]",
                        "Australia", "October 30", "Total"],
        "City": ["Sydney", "Sydney", "Sydney", "Brisbane[b]", "Australia", "Perth", "Total"],
        "Country": ["Australia"] * 4 + ["Australia", "Australia", "Total"],
        "Venue": ["Qudos Bank Arena"] * 3 + ["Brisbane Ent. Centre", "Australia", "RAC Arena", "Total"],
        "Attendance": ["64,096 / 64,096"] * 3 + ["9,800 / 11,000", "Australia", "\u2014N/a",
                                                 "87,896 / 89,096 (98.7%)"],
        "Revenue": ["$7,197,262"] * 3 + ["$900,000", "Australia", "\u2014N/a", "$8,097,262"],
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


def _shows(rows):
    """Build clean_tour_table-style output from (venue, attendance_raw, revenue) tuples."""
    return pd.DataFrame([{
        "tour": "T", "show_date": pd.Timestamp("2011-10-23") + pd.Timedelta(days=i),
        "city": venue, "country": "Germany", "venue": venue, "attendance_raw": raw,
        "tickets_sold": int(raw.split("/")[0].replace(",", "")),
        "capacity": int(raw.split("/")[1].replace(",", "")), "revenue_usd": revenue,
    } for i, (venue, raw, revenue) in enumerate(rows)])


def test_collapse_engagements_drops_figures_shared_across_venues():
    # The Neverending World Tour: one merged cell covers a whole leg of
    # different arenas, so no single venue's numbers can be recovered.
    shows = _shows([
        ("O2 World", "266,000 / 266,000", 9e6),
        ("SAP Arena", "266,000 / 266,000", 9e6),
        ("Messehalle", "266,000 / 266,000", 9e6),
        ("Stadthalle", "8,000 / 9,000", 5e5),
    ])
    eng = collapse_engagements(shows)
    assert list(eng["venue"]) == ["Stadthalle"]


def test_collapse_engagements_keeps_coincidentally_equal_sellouts():
    # Two different arenas can both sell exactly 15,000 / 15,000. Different
    # revenue means they were reported separately, so both are kept.
    shows = _shows([
        ("Arena A", "15,000 / 15,000", 1.2e6),
        ("Arena B", "15,000 / 15,000", 1.4e6),
    ])
    assert len(collapse_engagements(shows)) == 2


def test_clean_tour_table_drops_total_label_in_venue_column_only():
    # Josh Groban on Stage: "Total" appears only in the venue column
    df = pd.DataFrame({"Date (2016)": ["May 1", ""], "Venue": ["Arena", "Total"],
                       "City": ["Austin", ""], "Attendance": ["9,000 / 10,000", "38,232 / 40,000"]})
    shows = clean_tour_table(df, tour="T")
    assert list(shows["venue"]) == ["Arena"]


def test_collapse_engagements_flags_festivals_and_suspect_capacity():
    shows = _shows([
        ("Summer Sonic Festival", "235,000 / 235,000", 1e6),
        ("Wembley Stadium", "90,000 / 90,000", 2e6),
        ("Some Arena", "250,000 / 266,000", 3e6),  # leg total stuck on one row
    ])
    eng = collapse_engagements(shows).set_index("venue")
    assert eng.loc["Summer Sonic Festival", "is_festival"]
    assert not eng.loc["Wembley Stadium", "is_festival"]
    assert not eng.loc["Wembley Stadium", "suspect_capacity"]
    assert eng.loc["Some Arena", "suspect_capacity"]
    assert eng.loc["Wembley Stadium", "capacity_per_show"] == 90000
