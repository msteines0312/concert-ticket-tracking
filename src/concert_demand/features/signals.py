"""Build popularity signals for each show, measured before the show to avoid leakage.

A talent buyer picks a venue months before the show, when the tour is
booked and tickets go on sale. So every signal is measured as of a cutoff
date six months (182 days) before the show, and only data dated strictly
before the cutoff is used. Measuring on the show date instead would let the
tour's own hype (announcements, sellout news) leak into the signal. That
version is still built, as a robustness check.

Windows end at the cutoff and look back 13, 26 or 52 weeks:

    |<------------- 52 weeks ------------->|<-- 182 days -->|
                              |<- 13 wks ->|                |
                                         cutoff          show date

Signals per window
------------------
- Billboard, separately for the Hot 100 and Billboard 200 and for lead and
  featured credits: entries (song-weeks on the chart) and points, where a
  #1 earns chart_size points and the last position earns 1. Points reward
  ranking high, not just being on the chart.
- Billboard best rank, any role.
- Wikipedia pageviews: mean daily views (current title + former names).
- Spotify US + Canada (2017-2021 sub-analysis): Top 200 streams and Viral 50
  entries, lead and featured credits together (a feature earns the song's
  full streams). Null when the window isn't fully inside the Spotify data.

Plus career totals (all Billboard history before the cutoff) and a
pageview momentum ratio comparing the last 13 weeks to the last 52.

Usage
-----
    python -m concert_demand.features.signals
"""

import logging
import sqlite3

import numpy as np
import pandas as pd

from concert_demand.load_db import DB_PATH
from concert_demand.paths import PROCESSED_DIR

CUTOFF_DAYS = 182          # main analysis: signals as of ~6 months before the show
WINDOW_WEEKS = [13, 26, 52]
PRIMARY_WINDOW_WEEKS = 52  # sets the model start date
CHART_SIZES = {"hot100": 100, "billboard200": 200}

PAGEVIEWS_START = pd.Timestamp("2015-07-01")
SPOTIFY_START = pd.Timestamp("2017-01-01")
SPOTIFY_END = pd.Timestamp("2021-12-31")

# Output tables: main features, and the show-date version for robustness checks
FEATURE_TABLES = {"show_features": CUTOFF_DAYS, "show_features_show_date": 0}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core: sum of events in a date window, for many windows at once
# ---------------------------------------------------------------------------

def window_sums(event_dates, values, starts, ends):
    """Sum event values dated in [start, end) for each window.

    Uses a cumulative sum and binary search, so each window costs
    O(log n) instead of a scan over every event.

    Parameters
    ----------
    event_dates : numpy.ndarray of datetime64
        Sorted ascending.
    values : numpy.ndarray
        Value of each event, aligned with `event_dates`.
    starts, ends : numpy.ndarray of datetime64
        Window bounds. The start is included and the end is excluded, so
        an event dated on the cutoff itself is never counted.

    Returns
    -------
    numpy.ndarray
        One sum per window.
    """
    cumulative = np.concatenate([[0], np.cumsum(values, dtype=float)])
    first = np.searchsorted(event_dates, starts, side="left")
    last = np.searchsorted(event_dates, ends, side="left")
    return cumulative[last] - cumulative[first]


def window_min(event_dates, values, starts, ends):
    """Smallest event value dated in [start, end) for each window, NaN if none.

    Used for best chart rank. A loop is fine here: it runs once per show
    and each slice is a single artist's chart history.
    """
    first = np.searchsorted(event_dates, starts, side="left")
    last = np.searchsorted(event_dates, ends, side="left")
    return np.array([values[i:j].min() if j > i else np.nan for i, j in zip(first, last)])


# ---------------------------------------------------------------------------
# Signal builders: one artist's events -> one column per window
# ---------------------------------------------------------------------------

def _windows(cutoffs, weeks):
    """Start and end bounds for windows ending at each cutoff."""
    ends = cutoffs.to_numpy()
    starts = (cutoffs - pd.Timedelta(weeks=weeks)).to_numpy()
    return starts, ends


def chart_signals(shows, credits):
    """Billboard entries, points and best rank per show and window.

    Parameters
    ----------
    shows : pandas.DataFrame
        One artist's shows, with a `cutoff` column.
    credits : pandas.DataFrame
        That artist's chart credits: chart, chart_week, rank, role.

    Returns
    -------
    pandas.DataFrame
        Indexed like `shows`.
    """
    features = {}
    for chart, size in CHART_SIZES.items():
        on_chart = credits[credits["chart"] == chart]
        for role in ["lead", "featured"]:
            events = on_chart[on_chart["role"] == role].sort_values("chart_week")
            dates = events["chart_week"].to_numpy()
            points = (size + 1 - events["rank"]).to_numpy()
            for weeks in WINDOW_WEEKS:
                starts, ends = _windows(shows["cutoff"], weeks)
                features[f"{chart}_{role}_entries_{weeks}w"] = window_sums(dates, np.ones(len(dates)), starts, ends)
                features[f"{chart}_{role}_points_{weeks}w"] = window_sums(dates, points, starts, ends)
            # Career depth: every entry before the cutoff, back to the chart's start
            features[f"{chart}_{role}_entries_career"] = window_sums(
                dates, np.ones(len(dates)), np.full(len(shows), np.datetime64("1900-01-01")),
                shows["cutoff"].to_numpy())

        events = on_chart.sort_values("chart_week")
        for weeks in WINDOW_WEEKS:
            starts, ends = _windows(shows["cutoff"], weeks)
            features[f"{chart}_best_rank_{weeks}w"] = window_min(
                events["chart_week"].to_numpy(), events["rank"].to_numpy(), starts, ends)
    return pd.DataFrame(features, index=shows.index)


def pageview_signals(shows, pageviews):
    """Mean daily Wikipedia pageviews per show and window.

    Windows that start before pageview data begins (2015-07-01) are null,
    not zero: the artist wasn't unpopular, the data just doesn't exist.
    """
    pageviews = pageviews.sort_values("date")
    dates = pageviews["date"].to_numpy()
    views = pageviews["views_total"].to_numpy()
    features = {}
    for weeks in WINDOW_WEEKS:
        starts, ends = _windows(shows["cutoff"], weeks)
        mean_views = window_sums(dates, views, starts, ends) / (weeks * 7)
        mean_views[starts < np.datetime64(PAGEVIEWS_START)] = np.nan
        features[f"pageviews_mean_{weeks}w"] = mean_views
    features = pd.DataFrame(features, index=shows.index)
    # Momentum: log ratio of recent to longer-run attention. 0 = steady,
    # positive = rising. The +1 keeps artists with zero views defined.
    features["pageviews_momentum"] = np.log(
        (features["pageviews_mean_13w"] + 1) / (features["pageviews_mean_52w"] + 1))
    return features


def spotify_signals(shows, spotify):
    """Spotify US + Canada streams and viral entries per show and window.

    Null unless the whole window lies inside the 2017-2021 Spotify data, so
    a partly covered window can't look like a quiet stretch.
    """
    top200 = spotify[spotify["chart"] == "top200"].sort_values("date")
    viral = spotify[spotify["chart"] == "viral50"].sort_values("date")
    features = {}
    for weeks in WINDOW_WEEKS:
        starts, ends = _windows(shows["cutoff"], weeks)
        covered = (starts >= np.datetime64(SPOTIFY_START)) & (ends <= np.datetime64(SPOTIFY_END + pd.Timedelta(days=1)))
        streams = window_sums(top200["date"].to_numpy(), top200["streams"].to_numpy(), starts, ends)
        viral_entries = window_sums(viral["date"].to_numpy(), np.ones(len(viral)), starts, ends)
        features[f"spotify_streams_{weeks}w"] = np.where(covered, streams, np.nan)
        features[f"spotify_viral_entries_{weeks}w"] = np.where(covered, viral_entries, np.nan)
    return pd.DataFrame(features, index=shows.index)


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def build_features(shows, credits, pageviews, spotify, cutoff_days=CUTOFF_DAYS):
    """Compute every signal for every show.

    Parameters
    ----------
    shows : pandas.DataFrame
        engagement_id, artist, first_date (datetime).
    credits, pageviews, spotify : pandas.DataFrame
        All artists' rows, with datetime date columns.
    cutoff_days : int
        Days before the show that signals are measured.

    Returns
    -------
    pandas.DataFrame
        One row per show: engagement_id, artist, show_date, cutoff_date,
        in_model_window, then every signal.
    """
    shows = shows.assign(cutoff=shows["first_date"] - pd.Timedelta(days=cutoff_days))
    by_artist = {
        "credits": dict(tuple(credits.groupby("artist"))),
        "pageviews": dict(tuple(pageviews.groupby("artist"))),
        "spotify": dict(tuple(spotify.groupby("artist"))),
    }
    empty = {name: frame.iloc[0:0] for name, frame in
             [("credits", credits), ("pageviews", pageviews), ("spotify", spotify)]}

    parts = []
    for artist, artist_shows in shows.groupby("artist"):
        def events(name):
            return by_artist[name].get(artist, empty[name])
        parts.append(pd.concat([
            chart_signals(artist_shows, events("credits")),
            pageview_signals(artist_shows, events("pageviews")),
            spotify_signals(artist_shows, events("spotify")),
        ], axis=1))
    signals = pd.concat(parts).loc[shows.index]

    primary_start = shows["cutoff"] - pd.Timedelta(weeks=PRIMARY_WINDOW_WEEKS)
    meta = pd.DataFrame({
        "engagement_id": shows["engagement_id"],
        "artist": shows["artist"],
        "show_date": shows["first_date"].dt.strftime("%Y-%m-%d"),
        "cutoff_date": shows["cutoff"].dt.strftime("%Y-%m-%d"),
        # True when the 52-week pageview window is fully covered
        "in_model_window": (primary_start >= PAGEVIEWS_START).astype(int),
    })
    return pd.concat([meta, signals], axis=1)


def load_inputs(connection):
    """Read shows and event tables from the database, with parsed dates."""
    shows = pd.read_sql(
        "SELECT engagement_id, artist, first_date FROM engagements "
        "WHERE artist IS NOT NULL AND first_date IS NOT NULL", connection,
        parse_dates=["first_date"])
    credits = pd.read_sql("SELECT artist, chart, chart_week, rank, role FROM chart_credits",
                          connection, parse_dates=["chart_week"])
    pageviews = pd.read_sql("SELECT artist, date, views_total FROM pageviews_daily",
                            connection, parse_dates=["date"])
    spotify = pd.read_sql("SELECT artist, chart, date, streams FROM spotify_credits "
                          "WHERE region IN ('United States', 'Canada')", connection,
                          parse_dates=["date"])
    return shows, credits, pageviews, spotify


def run(db_path=DB_PATH):
    """Build both feature tables and write them to the database and CSV."""
    with sqlite3.connect(db_path) as connection:
        inputs = load_inputs(connection)
        for table, cutoff_days in FEATURE_TABLES.items():
            features = build_features(*inputs, cutoff_days=cutoff_days)
            features.to_sql(table, connection, if_exists="replace", index=False)
            features.to_csv(PROCESSED_DIR / f"{table}.csv", index=False)
            logger.info("%s: %d shows x %d columns (cutoff %d days before show)",
                        table, len(features), features.shape[1], cutoff_days)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
