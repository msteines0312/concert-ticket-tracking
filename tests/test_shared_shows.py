"""Tests for merging shows listed on two tour pages, and COVID era labels."""

import pandas as pd

from concert_demand.clean.covid import assign_covid_era
from concert_demand.clean.shared_shows import merge_shared_shows

BILLS = {
    "Aldean Tour": ("Chesney Tour", "co-headline"),
    "Opener Tour": ("Headliner Tour", "opener"),
}


def _engagements(rows):
    """Build engagements from (artist, tour, city, venue, date, tickets) tuples."""
    df = pd.DataFrame(rows, columns=["artist", "tour", "city", "venue", "first_date", "tickets_sold"])
    df["first_date"] = pd.to_datetime(df["first_date"])
    df["last_date"] = df["first_date"]
    df["capacity"] = df["tickets_sold"]
    df["co_headliners"] = None
    df["n_headliners"] = 1
    return df


def test_co_headline_keeps_one_row_with_both_artists():
    eng = _engagements([
        ("Kenny Chesney", "Chesney Tour", "Foxborough", "Gillette Stadium", "2015-08-28", 60000),
        ("Jason Aldean", "Aldean Tour", "Foxborough", "Gillette Stadium", "2015-08-28", 60000),
        ("Jason Aldean", "Aldean Tour", "Tulsa", "BOK Center", "2015-09-01", 12000),
    ])
    out = merge_shared_shows(eng, BILLS)
    assert len(out) == 2
    shared = out[out["city"] == "Foxborough"].iloc[0]
    assert shared["artist"] == "Kenny Chesney"
    assert shared["co_headliners"] == "Jason Aldean"
    assert shared["n_headliners"] == 2
    # Aldean's solo date isn't shared, so it stays
    assert "Tulsa" in out["city"].values


def test_opener_row_is_dropped_without_adding_a_co_headliner():
    # Venue spelled differently on the two pages, as with Lali and Katy Perry
    eng = _engagements([
        ("Katy Perry", "Headliner Tour", "Buenos Aires", "Hipódromo Argentino de Palermo",
         "2015-10-03", 17623),
        ("Lali", "Opener Tour", "Buenos Aires", "Hipódromo de Palermo", "2015-10-03", 17623),
    ])
    out = merge_shared_shows(eng, BILLS)
    assert list(out["artist"]) == ["Katy Perry"]
    assert pd.isna(out.loc[0, "co_headliners"])
    assert not out.loc[0, "conflicting_sources"]


def test_merged_show_with_different_numbers_is_flagged():
    eng = _engagements([
        ("Kenny Chesney", "Chesney Tour", "Kansas City", "Arrowhead Stadium", "2015-08-01", 53864),
        ("Jason Aldean", "Aldean Tour", "Kansas City", "Arrowhead Stadium", "2015-08-01", 57368),
    ])
    out = merge_shared_shows(eng, BILLS)
    assert len(out) == 1
    assert out.loc[0, "conflicting_sources"]


def test_unlisted_overlap_flags_both_rows():
    # Queen + Adam Lambert (two nights) and Maroon 5 can't share an arena
    eng = _engagements([
        ("Queen", "Queen Tour", "Sydney", "Qudos Bank Arena", "2018-02-21", 24791),
        ("Maroon 5", "Maroon Tour", "Sydney", "Qudos Bank Arena", "2018-02-21", 16602),
        ("Maroon 5", "Maroon Tour", "Brisbane", "Brisbane Entertainment Centre", "2018-02-24", 9000),
    ])
    eng.loc[0, "last_date"] = pd.Timestamp("2018-02-22")
    out = merge_shared_shows(eng, BILLS)
    assert list(out["conflicting_sources"]) == [True, True, False]


def test_other_acts_between_residency_nights_are_not_conflicts():
    # Harry Styles' 15 MSG nights spanned a month; Roger Waters played in between
    eng = _engagements([
        ("Harry Styles", "Love On Tour", "New York City", "Madison Square Garden",
         "2022-08-20", 276852),
        ("Roger Waters", "This Is Not a Drill", "New York City", "Madison Square Garden",
         "2022-08-30", 29314),
    ])
    eng.loc[0, "last_date"] = pd.Timestamp("2022-09-21")
    assert not merge_shared_shows(eng, BILLS)["conflicting_sources"].any()


def test_same_tour_at_same_venue_is_not_a_conflict():
    eng = _engagements([
        ("Adele", "Adele Tour", "London", "Wembley Stadium", "2017-06-28", 98000),
        ("Adele", "Adele Tour", "London", "Wembley Stadium", "2017-06-29", 98000),
    ])
    assert not merge_shared_shows(eng, BILLS)["conflicting_sources"].any()


def test_assign_covid_era_boundaries():
    dates = pd.to_datetime(pd.Series(
        ["2020-03-11", "2020-03-12", "2021-07-31", "2021-08-01", None]))
    assert list(assign_covid_era(dates)) == ["pre", "during", "during", "post", None]
