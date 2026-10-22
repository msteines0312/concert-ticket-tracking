"""Standardize country names and fill in countries that tour tables leave blank.

The main analysis uses US + Canada shows, so every engagement needs a
reliable country. Wikipedia tables get there most of the time, but:

- The same country is spelled several ways ("Perú" and "Peru", "Czechia"
  and "Czech Republic"), and UK shows are split into England, Scotland,
  Wales and Northern Ireland on some pages and "United Kingdom" on others.
- Some rows are blank, or name a continent ("North America") instead.

Blanks are filled from evidence in the data itself, in two passes:

1. City lookup: the city appears in exactly one country across all tagged
   shows, or the cell names its country ("Tampa, U.S.", "London, Canada").
2. Tour neighbors: the nearest tagged shows above and below on the same
   tour are in the same country. Tours travel in legs, so a gap inside a
   leg belongs to that leg. This pass runs second because blanks usually
   come in whole blocks (a table with no Country column), and pass 1 fills
   in the shows around an ambiguous city. A neighbor's country is only
   accepted if the city is known to exist there, so a "London" between two
   English dates becomes England's London, never a German one.

Anything still uncertain stays blank. `country_source` records how each
value was set, so filled rows can be audited or excluded.

Puerto Rico is kept as its own country but counted in the US + Canada
market: its shows are tracked by Billboard's US charts, but its listening
leans much more toward Latin music, so `is_puerto_rico` lets the models
control for it.
"""

import pandas as pd

# Spelling variants and UK constituent countries -> one standard name
COUNTRY_ALIASES = {
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
    "Wales": "United Kingdom",
    "Northern Ireland": "United Kingdom",
    "Perú": "Peru",
    "Czechia": "Czech Republic",
    "UAE": "United Arab Emirates",
    "Republic of Ireland": "Ireland",
    "Macedonia": "North Macedonia",
    "U.S.": "United States",
    "USA": "United States",
}

# Values that sit in the country column but aren't countries
NOT_COUNTRIES = {"North America"}

US_CANADA_MARKET = {"United States", "Canada", "Puerto Rico"}

# Suffixes accepted as a country in "City, Country" cells. Kept to countries
# that actually appear in these cells, so a state like "Georgia" never reads
# as the country Georgia.
KNOWN_COUNTRIES = {"United States", "Canada"}


def standardize_country(name):
    """Map a raw country cell to its standard name.

    Parameters
    ----------
    name : object
        A country cell from a tour table.

    Returns
    -------
    str or None
        The standard country name, or None for blanks and non-countries.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    if name in NOT_COUNTRIES:
        return None
    return COUNTRY_ALIASES.get(name, name)


def build_city_countries(engagements):
    """Map each city to every country it appears in across tagged shows.

    Parameters
    ----------
    engagements : pandas.DataFrame
        Must have `city` and a standardized `country` column.

    Returns
    -------
    dict
        city -> set of countries. One country means the city is unambiguous.
    """
    known = engagements.dropna(subset=["city", "country"])
    return known.groupby("city")["country"].agg(set).to_dict()


def country_from_city(city, city_countries):
    """Country implied by a city cell alone, or None if it's ambiguous or unknown.

    Tries the whole cell first, then a trailing country ("Tampa, U.S."),
    then the part before the comma ("Philadelphia, Pennsylvania").

    Parameters
    ----------
    city : object
        A city cell.
    city_countries : dict
        Output of `build_city_countries`.

    Returns
    -------
    str or None
    """
    if not isinstance(city, str):
        return None
    base, _, suffix = city.rpartition(", ")
    candidates = [city_countries.get(city, set())]
    if base:
        suffix_country = standardize_country(suffix)
        candidates.append({suffix_country} if suffix_country in KNOWN_COUNTRIES else set())
        candidates.append(city_countries.get(base, set()))
    for countries in candidates:
        if len(countries) == 1:
            return next(iter(countries))
        if len(countries) > 1:
            return None  # a known city in several countries: don't guess
    return None


def _neighbor_country(engagements):
    """Country shared by the nearest tagged shows above and below on the same tour.

    Returns a Series aligned with `engagements`. A row gets a value only when
    both neighbors exist and agree, so the first and last gaps of a tour and
    gaps at a border crossing stay blank.
    """
    by_tour = engagements.groupby("tour", sort=False)["country"]
    above = by_tour.ffill()
    below = by_tour.bfill()
    return above.where(above == below)


def _city_allows(city, country, city_countries):
    """True if `country` is consistent with what's known about `city`."""
    known = city_countries.get(city, set())
    return not known or country in known


def tag_countries(engagements):
    """Standardize countries, fill blanks, and flag the US + Canada market.

    Parameters
    ----------
    engagements : pandas.DataFrame
        One row per engagement in table order, with tour, city and country.

    Returns
    -------
    pandas.DataFrame
        A copy with `country` standardized and filled where possible, plus
        `country_raw` (the page's text), `country_source` ("page",
        "tour_neighbors", "city_lookup" or None), `in_us_canada` and
        `is_puerto_rico`.
    """
    out = engagements.copy()
    out.insert(out.columns.get_loc("country") + 1, "country_raw", out["country"])
    out["country"] = out["country"].map(standardize_country)
    out["country_source"] = out["country"].notna().map({True: "page", False: None})

    # Both passes learn only from countries the pages themselves state
    city_countries = build_city_countries(out)

    city_country = out["city"].map(lambda city: country_from_city(city, city_countries))
    from_city = out["country"].isna() & city_country.notna()
    out.loc[from_city, "country"] = city_country[from_city]
    out.loc[from_city, "country_source"] = "city_lookup"

    neighbor = _neighbor_country(out)
    from_neighbors = out["country"].isna() & neighbor.notna() & pd.Series(
        [_city_allows(city, country, city_countries)
         for city, country in zip(out["city"], neighbor)], index=out.index)
    out.loc[from_neighbors, "country"] = neighbor[from_neighbors]
    out.loc[from_neighbors, "country_source"] = "tour_neighbors"

    out["in_us_canada"] = out["country"].isin(US_CANADA_MARKET)
    out["is_puerto_rico"] = out["country"] == "Puerto Rico"
    return out
