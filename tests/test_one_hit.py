"""Tests for Matt's one-hit act definition."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.features.one_hit import (
    career_album_share,
    flag_shows,
    pre_song_attention,
    top_song_share,
)

CUTOFF = pd.Timestamp("2023-06-01")


def _credit(week, title="Viral Song", rank=1, chart="hot100", artist="New Act"):
    return {"artist": artist, "chart": chart, "chart_week": pd.Timestamp(week), "rank": rank, "title": title}


def test_top_song_share_uses_only_the_year_before_the_cutoff():
    hot100 = pd.DataFrame([_credit("2023-01-07", rank=1),          # 100 points
                           _credit("2023-02-04", "Other", rank=51),  # 50 points
                           _credit("2023-06-03", "Later", rank=1)])  # after cutoff: ignored
    song, share = top_song_share(hot100, CUTOFF)
    assert song == "Viral Song"
    assert share == pytest.approx(100 / 150)


def test_top_song_share_is_missing_without_a_chart_run():
    song, share = top_song_share(pd.DataFrame([_credit("2020-01-04")]), CUTOFF)  # years earlier
    assert song is None
    assert np.isnan(share)


def test_pre_song_attention_is_unknown_before_pageview_data():
    views = pd.DataFrame({"date": pd.date_range("2015-07-01", "2016-12-31"), "views": 10})
    assert np.isnan(pre_song_attention(views, pd.Timestamp("2016-01-01")))  # year starts in 2015-01
    assert pre_song_attention(views, pd.Timestamp("2016-12-01")) == pytest.approx(10)


def test_career_album_share_counts_the_whole_career():
    credits = pd.DataFrame([_credit("2010-01-02", "Old Album", rank=1, chart="billboard200"),  # 200 pts
                            _credit("2023-01-07", rank=1)])                                      # 100 pts
    assert career_album_share(credits, CUTOFF) == pytest.approx(200 / 300)


def _views(level, artist="New Act"):
    return pd.DataFrame({"artist": artist, "date": pd.date_range("2015-07-01", "2023-12-31"), "views": level})


def _shows(artist="New Act"):
    return pd.DataFrame({"engagement_id": [1], "signal_artist": [artist], "cutoff_date": [CUTOFF]})


def test_viral_song_with_no_fan_base_is_flagged():
    credits = pd.DataFrame([_credit("2023-01-07")])
    flags = flag_shows(_shows(), credits, _views(500)).iloc[0]
    assert flags["is_one_hit"] == 1


def test_established_artist_with_one_recent_single_is_not_flagged():
    # Big audience before the song, and a career of charting albums
    credits = pd.DataFrame([_credit("2023-01-07"),
                            _credit("2012-01-07", "Hit Album", chart="billboard200")])
    flags = flag_shows(_shows(), credits, _views(20_000)).iloc[0]
    assert flags["is_one_hit"] == 0


def test_album_career_alone_prevents_the_flag():
    # Low pageviews but a real album history (Brad Paisley between albums)
    credits = pd.DataFrame([_credit("2023-01-07"),
                            _credit("2012-01-07", "Hit Album", chart="billboard200")])
    flags = flag_shows(_shows(), credits, _views(500)).iloc[0]
    assert flags["is_one_hit"] == 0
