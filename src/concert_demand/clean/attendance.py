"""Clean Wikipedia tour tables into one row per engagement.

Wikipedia tour pages list shows in a table with Attendance ("sold / capacity")
and Revenue columns, usually sourced from Billboard Boxscore or Pollstar.
`pandas.read_html` gets the table into a DataFrame, but it needs cleaning:

- Footnote markers like "Sydney[c]" are stuck to values.
- Dates often lack a year ("February 23"), which lives in the header instead
  ("Date (2024)").
- "Total" rows and tour-leg divider rows ("North America") aren't shows.
- A multi-night run shares one merged Attendance cell. read_html copies that
  value into every row, so naive summing would count the run several times.

The last point is why the output unit is an *engagement*: consecutive shows
at one venue reported under one figure. Pollstar reports runs the same way
("2 shows"), which lets the two sources line up later.
"""

import re

import pandas as pd

# Footnote markers: "[a]", "[12]", "[note 3]"
FOOTNOTE_PATTERN = re.compile(r"\[[^\]]*\]")

# "9,998 / 9,998" or "1,657,377 / 1,657,377 (100%)"
ATTENDANCE_PATTERN = re.compile(r"^([\d,]+)\s*/\s*([\d,]+)")

# "$1,733,194" or "US$1,733,194". Other currencies are not converted.
REVENUE_PATTERN = re.compile(r"^(?:US)?\$\s*([\d,]+(?:\.\d+)?)")

YEAR_PATTERN = re.compile(r"\b(\d{4})\b")

# Header keyword -> canonical column name. Checked with str.startswith on the
# lowercased header, so "Dates (2018)" -> date and "Box Office" -> revenue.
COLUMN_KEYWORDS = {
    "date": "date",
    "city": "city",
    "country": "country",
    "venue": "venue",
    "attendance": "attendance",
    "revenue": "revenue",
    "box office": "revenue",
    "gross": "revenue",
}

SHOW_COLUMNS = ["date", "city", "country", "venue", "attendance", "revenue"]


# ---------------------------------------------------------------------------
# Cell-level parsers
# ---------------------------------------------------------------------------

def strip_footnotes(value):
    """Remove Wikipedia footnote markers and surrounding whitespace.

    Parameters
    ----------
    value : object
        A table cell. Non-string values are returned unchanged.

    Returns
    -------
    object
        The cleaned string, or the original value if it wasn't a string.
    """
    if not isinstance(value, str):
        return value
    return FOOTNOTE_PATTERN.sub("", value).strip()


def parse_attendance(value):
    """Parse a "sold / capacity" cell into two integers.

    Parameters
    ----------
    value : object
        Raw Attendance cell, e.g. "2,056 / 2,717".

    Returns
    -------
    tuple of (int or None, int or None)
        (tickets_sold, capacity), or (None, None) when the cell is missing,
        a placeholder like "N/a", or a bare number with no capacity.
    """
    if not isinstance(value, str):
        return None, None
    match = ATTENDANCE_PATTERN.match(strip_footnotes(value))
    if not match:
        return None, None
    sold, capacity = (int(group.replace(",", "")) for group in match.groups())
    if capacity == 0:
        return None, None
    return sold, capacity


def parse_revenue(value):
    """Parse a USD revenue cell into a float.

    Parameters
    ----------
    value : object
        Raw Revenue cell, e.g. "$1,733,194".

    Returns
    -------
    float or None
        Revenue in US dollars, or None if missing or in another currency.
    """
    if not isinstance(value, str):
        return None
    match = REVENUE_PATTERN.match(strip_footnotes(value))
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_show_date(value, header_year):
    """Parse a show date, borrowing the year from the column header if needed.

    Parameters
    ----------
    value : object
        Raw Date cell, e.g. "February 23", "19 February", "January 7, 2014".
    header_year : int or None
        Year found in the column header ("Date (2024)"), if any.

    Returns
    -------
    pandas.Timestamp
        The parsed date, or NaT if it can't be determined.
    """
    if not isinstance(value, str):
        return pd.NaT
    text = strip_footnotes(value)
    # Date ranges like "July 4–5": keep the first day
    text = re.split(r"\s*[–-]\s*", text)[0]
    if not re.search(r"\d", text):
        return pd.NaT
    if not YEAR_PATTERN.search(text):
        if header_year is None:
            return pd.NaT
        text = f"{text} {header_year}"
    return pd.to_datetime(text, errors="coerce")


# ---------------------------------------------------------------------------
# Table-level cleaning
# ---------------------------------------------------------------------------

def standardize_columns(table):
    """Rename a raw tour table's columns to canonical names.

    Parameters
    ----------
    table : pandas.DataFrame
        Output of `pandas.read_html` for one tour table. Two-row headers
        (column name plus tour leg) are flattened to the first row.

    Returns
    -------
    tuple of (pandas.DataFrame, int or None)
        The table with only the recognized columns, renamed, and the year
        found in the date header (None if the header has no year).
    """
    table = table.copy()
    if isinstance(table.columns, pd.MultiIndex):
        table.columns = table.columns.get_level_values(0)

    rename = {}
    header_year = None
    for column in table.columns:
        header = str(column).strip().lower()
        for keyword, canonical in COLUMN_KEYWORDS.items():
            # First matching header wins if two map to the same name
            if header.startswith(keyword) and canonical not in rename.values():
                rename[column] = canonical
                if canonical == "date":
                    year_match = YEAR_PATTERN.search(header)
                    header_year = int(year_match.group(1)) if year_match else None
                break

    table = table[list(rename)].rename(columns=rename)
    return table, header_year


def _is_non_show_row(row):
    """Flag "Total" rows and tour-leg divider rows.

    A leg divider like "North America" spans the full width of the table,
    so read_html repeats the same text in every cell.
    """
    values = [strip_footnotes(v) for v in row if isinstance(v, str)]
    if any(v == "Total" for v in values):
        return True
    return len(values) == len(row) and len(set(values)) == 1


def clean_tour_table(table, tour):
    """Turn one raw tour table into one row per show with parsed fields.

    Parameters
    ----------
    table : pandas.DataFrame
        Output of `pandas.read_html` for one tour table.
    tour : str
        Wikipedia title of the tour page, kept for traceability.

    Returns
    -------
    pandas.DataFrame
        Columns: tour, show_date, city, country, venue, attendance_raw,
        tickets_sold, capacity, revenue_usd.
    """
    table, header_year = standardize_columns(table)
    for column in SHOW_COLUMNS:
        if column not in table.columns:
            table[column] = pd.NA

    table = table[~table.apply(_is_non_show_row, axis=1)]

    attendance = table["attendance"].map(parse_attendance)
    shows = pd.DataFrame({
        "tour": tour,
        "show_date": table["date"].map(lambda v: parse_show_date(v, header_year)),
        "city": table["city"].map(strip_footnotes),
        "country": table["country"].map(strip_footnotes),
        "venue": table["venue"].map(strip_footnotes),
        "attendance_raw": table["attendance"],
        "tickets_sold": attendance.map(lambda pair: pair[0]),
        "capacity": attendance.map(lambda pair: pair[1]),
        "revenue_usd": table["revenue"].map(parse_revenue),
    })
    shows["show_date"] = pd.to_datetime(shows["show_date"])
    return shows.reset_index(drop=True)


def collapse_engagements(shows):
    """Merge multi-night runs into single engagements and compute fill rate.

    Consecutive rows with the same tour, venue, city and raw attendance
    string come from one merged table cell, so they are one reported run.
    The same venue with *different* numbers stays separate, because those
    dates were reported separately.

    Parameters
    ----------
    shows : pandas.DataFrame
        Output of `clean_tour_table`.

    Returns
    -------
    pandas.DataFrame
        One row per engagement with first_date, last_date, n_shows,
        tickets_sold, capacity, revenue_usd, fill_rate (capped at 1.0),
        sold_out and over_capacity. Rows without attendance are dropped.
    """
    shows = shows.dropna(subset=["tickets_sold", "capacity"]).reset_index(drop=True)

    key_columns = ["tour", "venue", "city", "attendance_raw"]
    keys = shows[key_columns].astype(str)
    # A new engagement starts whenever the key differs from the row above
    starts_new_run = (keys != keys.shift()).any(axis=1)
    run_id = starts_new_run.cumsum()

    engagements = (
        shows.groupby(run_id, sort=False)
        .agg(
            tour=("tour", "first"),
            venue=("venue", "first"),
            city=("city", "first"),
            country=("country", "first"),
            first_date=("show_date", "min"),
            last_date=("show_date", "max"),
            n_shows=("tour", "size"),
            tickets_sold=("tickets_sold", "first"),
            capacity=("capacity", "first"),
            revenue_usd=("revenue_usd", "first"),
        )
        .reset_index(drop=True)
    )

    engagements["tickets_sold"] = engagements["tickets_sold"].astype(int)
    engagements["capacity"] = engagements["capacity"].astype(int)
    # Comps and standing room can push reported attendance past capacity.
    # Cap fill rate at 100% but keep a flag so those rows can be inspected.
    engagements["over_capacity"] = engagements["tickets_sold"] > engagements["capacity"]
    engagements["sold_out"] = engagements["tickets_sold"] >= engagements["capacity"]
    engagements["fill_rate"] = (
        engagements["tickets_sold"] / engagements["capacity"]
    ).clip(upper=1.0)
    return engagements
