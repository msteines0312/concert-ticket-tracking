"""Tests for country standardization and gap filling."""

import pandas as pd
import pytest

from concert_demand.clean.countries import standardize_country, tag_countries


@pytest.mark.parametrize("raw, expected", [
    ("United States", "United States"),
    ("Scotland", "United Kingdom"),
    ("Perú", "Peru"),
    ("Czechia", "Czech Republic"),
    (" Canada ", "Canada"),
    ("North America", None),  # a continent, used as a leg label
    (None, None),
    ("", None),
])
def test_standardize_country(raw, expected):
    assert standardize_country(raw) == expected


def _engagements(rows):
    """Build engagements from (tour, city, country) tuples."""
    return pd.DataFrame(rows, columns=["tour", "city", "country"])


def test_tag_countries_fills_gap_inside_a_leg():
    # J. Cole's tour labels a block of US dates "North America"
    eng = _engagements([
        ("T", "Denver", "United States"),
        ("T", "Phoenix", "North America"),
        ("T", "Oakland", "United States"),
    ])
    out = tag_countries(eng)
    assert out.loc[1, "country"] == "United States"
    assert out.loc[1, "country_source"] == "tour_neighbors"
    assert out.loc[1, "country_raw"] == "North America"


def test_tag_countries_does_not_fill_across_a_border():
    # Neighbors disagree, and "Smalltown" isn't in the city lookup
    eng = _engagements([
        ("T", "Seattle", "United States"),
        ("T", "Smalltown", None),
        ("T", "Vancouver", "Canada"),
    ])
    assert pd.isna(tag_countries(eng).loc[1, "country"])


def test_tag_countries_neighbors_never_overrule_a_known_city():
    # A UK show listed between two US shows must not become US
    eng = _engagements([
        ("A", "Glasgow", "Scotland"),
        ("T", "Boston", "United States"),
        ("T", "Glasgow", None),
        ("T", "Chicago", "United States"),
    ])
    out = tag_countries(eng)
    assert out.loc[2, "country"] == "United Kingdom"
    assert out.loc[2, "country_source"] == "city_lookup"


def test_tag_countries_neighbors_stay_within_one_tour():
    eng = _engagements([
        ("A", "Denver", "United States"),
        ("B", "Smalltown", None),
        ("C", "Austin", "United States"),
    ])
    assert pd.isna(tag_countries(eng).loc[1, "country"])


def test_tag_countries_skips_cities_in_several_countries():
    # London is in England and in Ontario, so the city alone can't decide
    eng = _engagements([
        ("A", "London", "England"),
        ("B", "London", "Canada"),
        ("C", "London", None),
    ])
    assert pd.isna(tag_countries(eng).loc[2, "country"])


def test_tag_countries_neighbors_settle_an_ambiguous_city():
    # Mariah Carey's UK leg has no Country column. Glasgow is unambiguous, so
    # it's filled first, and the London between Glasgow and a known English
    # show resolves to England's London.
    eng = _engagements([
        ("A", "London", "England"),
        ("B", "London", "Canada"),
        ("C", "Leeds", "England"),
        ("D", "Glasgow", "Scotland"),
        ("T", "Glasgow", None),
        ("T", "London", None),
        ("T", "Leeds", None),
    ])
    out = tag_countries(eng)
    assert list(out.loc[4:6, "country"]) == ["United Kingdom"] * 3
    assert out.loc[5, "country_source"] == "tour_neighbors"


def test_tag_countries_neighbors_must_be_a_country_the_city_is_in():
    # Hamburg appears in Germany and the US. A Hamburg between two UK dates
    # can't be either one for sure, so it stays blank.
    eng = _engagements([
        ("A", "Hamburg", "Germany"),
        ("B", "Hamburg", "United States"),
        ("T", "Leeds", "England"),
        ("T", "Hamburg", None),
        ("T", "Cardiff", "Wales"),
    ])
    assert pd.isna(tag_countries(eng).loc[3, "country"])


@pytest.mark.parametrize("city, expected", [
    ("Tampa, U.S.", "United States"),
    ("London, Canada", "Canada"),
    ("Philadelphia, Pennsylvania", "United States"),
])
def test_tag_countries_reads_city_cells_with_a_region(city, expected):
    eng = _engagements([
        ("A", "Philadelphia", "United States"),
        ("T", city, None),
    ])
    assert tag_countries(eng).loc[1, "country"] == expected


def test_tag_countries_flags_us_canada_market_including_puerto_rico():
    eng = _engagements([
        ("T", "San Juan", "Puerto Rico"),
        ("T", "Toronto", "Canada"),
        ("T", "Mexico City", "Mexico"),
    ])
    out = tag_countries(eng)
    assert list(out["in_us_canada"]) == [True, True, False]
    assert list(out["is_puerto_rico"]) == [True, False, False]
