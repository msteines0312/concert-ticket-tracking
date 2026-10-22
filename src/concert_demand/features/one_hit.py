"""Flag shows by one-hit acts: hype from one viral song, not a dedicated fan base.

Matt's question: does a single hit lead tour managers to book an artist into
rooms bigger than their real fan base can fill? His definition of a one-hit
act, measured as of each show's cutoff (six months before the show):

1. One song dominates: it supplies at least 70% of the act's Hot 100 lead
   points in the 52 weeks before the cutoff.
2. Little attention before that song: mean daily Wikipedia pageviews
   (English + Spanish) in the year before the song first charted were under
   3,000. Unknown, and so never flagged, when that year starts before
   pageview data does (July 2015).
3. Weak album support across the whole career: Billboard 200 points are a
   small share of all lead chart points before the cutoff. Albums are
   bought by fans; a single viral song is streamed by everyone. A whole
   career is used so an established artist between albums (Brad Paisley)
   isn't mistaken for a newcomer.

Only 4 to 7 artists qualify, so this is a case study for the brief, not a
model feature.

Usage
-----
    python -m concert_demand.features.one_hit
"""

import logging
import sqlite3

import numpy as np
import pandas as pd

from concert_demand.features.signals import PAGEVIEWS_START
from concert_demand.load_db import DB_PATH

TOP_SONG_SHARE_MIN = 0.70
PRE_SONG_VIEWS_MAX = 3000
# Matt chose the pageview cutoff; both album thresholds he was shown are
# kept as columns until he picks one for is_one_hit.
ALBUM_SHARE_MAX = {"is_one_hit_album30": 0.30, "is_one_hit_album50": 0.50}
PRIMARY_FLAG = "is_one_hit_album30"

logger = logging.getLogger(__name__)


def top_song_share(hot100, cutoff):
    """The biggest song's share of Hot 100 lead points in the 52 weeks before `cutoff`.

    Parameters
    ----------
    hot100 : pandas.DataFrame
        One artist's Hot 100 lead credits: chart_week, rank, title.
    cutoff : pandas.Timestamp

    Returns
    -------
    tuple of (str or None, float)
        Top song title and its share, or (None, nan) with no chart run.
    """
    window = hot100[(hot100["chart_week"] >= cutoff - pd.Timedelta(weeks=52))
                    & (hot100["chart_week"] < cutoff)]
    if window.empty:
        return None, np.nan
    points = (101 - window["rank"]).groupby(window["title"]).sum()
    return points.idxmax(), points.max() / points.sum()


def pre_song_attention(pageviews, song_start):
    """Mean daily pageviews in the 52 weeks before a song first charted.

    Returns
    -------
    float
        NaN when that year starts before pageview data begins.
    """
    start = song_start - pd.Timedelta(weeks=52)
    if start < PAGEVIEWS_START:
        return np.nan
    window = pageviews[(pageviews["date"] >= start) & (pageviews["date"] < song_start)]
    return window["views"].sum() / (52 * 7)


def career_album_share(credits, cutoff):
    """Billboard 200 share of all lead chart points before `cutoff`, whole career.

    Points use each chart's own scale (#1 = 100 on the Hot 100, 200 on the
    Billboard 200), the same as the main features.
    """
    before = credits[credits["chart_week"] < cutoff]
    size = np.where(before["chart"] == "hot100", 100, 200)
    points = pd.Series(size + 1 - before["rank"].to_numpy(), index=before.index)
    album = points[before["chart"] == "billboard200"].sum()
    total = points.sum()
    return album / total if total else np.nan


def flag_shows(shows, credits, pageviews):
    """Measure the three one-hit conditions for every show.

    Parameters
    ----------
    shows : pandas.DataFrame
        engagement_id, signal_artist, cutoff_date (datetime).
    credits : pandas.DataFrame
        Lead chart credits: artist, chart, chart_week, rank, title.
    pageviews : pandas.DataFrame
        artist, date, views (English + Spanish).

    Returns
    -------
    pandas.DataFrame
        One row per show: the measures and one flag column per album threshold.
    """
    credits_by_artist = dict(tuple(credits.groupby("artist")))
    views_by_artist = dict(tuple(pageviews.groupby("artist")))
    first_charted = credits[credits["chart"] == "hot100"].groupby(["artist", "title"])["chart_week"].min()

    rows, cache = [], {}
    for show in shows.itertuples():
        key = (show.signal_artist, show.cutoff_date)
        if key not in cache:
            artist_credits = credits_by_artist.get(show.signal_artist, credits.iloc[0:0])
            hot100 = artist_credits[artist_credits["chart"] == "hot100"]
            song, share = top_song_share(hot100, show.cutoff_date)
            attention = np.nan
            if song is not None:
                attention = pre_song_attention(
                    views_by_artist.get(show.signal_artist, pageviews.iloc[0:0]),
                    first_charted[(show.signal_artist, song)])
            cache[key] = (song, share, attention, career_album_share(artist_credits, show.cutoff_date))
        song, share, attention, album = cache[key]
        rows.append({"engagement_id": show.engagement_id, "top_song": song, "top_song_share": share,
                     "pre_song_views": attention, "career_album_share": album})

    flags = pd.DataFrame(rows)
    hype = (flags["top_song_share"] >= TOP_SONG_SHARE_MIN) & (flags["pre_song_views"] < PRE_SONG_VIEWS_MAX)
    for column, album_max in ALBUM_SHARE_MAX.items():
        flags[column] = (hype & (flags["career_album_share"] < album_max)).astype(int)
    flags["is_one_hit"] = flags[PRIMARY_FLAG]
    return flags


def run(db_path=DB_PATH):
    """Flag every charting show in the model sample and save one_hit_shows."""
    with sqlite3.connect(db_path) as connection:
        shows = pd.read_sql(
            "SELECT engagement_id, signal_artist, cutoff_date FROM show_features "
            "WHERE in_model_window = 1 AND hot100_lead_points_52w > 0",
            connection, parse_dates=["cutoff_date"])
        credits = pd.read_sql("SELECT artist, chart, chart_week, rank, title FROM chart_credits "
                              "WHERE role = 'lead'", connection, parse_dates=["chart_week"])
        pageviews = pd.read_sql("SELECT artist, date, views_total + views_es AS views "
                                "FROM pageviews_daily", connection, parse_dates=["date"])
        flags = flag_shows(shows, credits, pageviews)
        flags.to_sql("one_hit_shows", connection, if_exists="replace", index=False)
    for column in ALBUM_SHARE_MAX:
        logger.info("%s: %d shows flagged", column, flags[column].sum())
    return flags


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
