"""Tests for the as-of-cutoff popularity signals, with a focus on leakage."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.features.signals import build_features, window_min, window_sums

SHOW_DATE = pd.Timestamp("2019-07-01")
CUTOFF = SHOW_DATE - pd.Timedelta(days=182)  # 2018-12-31


def _dates(*days):
    return np.array(pd.to_datetime(list(days)), dtype="datetime64[ns]")


def test_window_sums_includes_start_and_excludes_end():
    events = _dates("2020-01-01", "2020-01-05", "2020-01-10")
    sums = window_sums(events, np.array([1, 10, 100]), _dates("2020-01-01"), _dates("2020-01-10"))
    assert sums.tolist() == [11]  # the event on the end date is not counted


def test_window_min_is_nan_for_an_empty_window():
    events = _dates("2020-01-05")
    result = window_min(events, np.array([3]), _dates("2020-02-01", "2020-01-01"),
                        _dates("2020-03-01", "2020-02-01"))
    assert np.isnan(result[0]) and result[1] == 3


def _credit(week, rank=1, chart="hot100", role="lead", artist="Artist A"):
    return {"artist": artist, "chart": chart, "chart_week": pd.Timestamp(week), "rank": rank, "role": role}


def _pageviews(start, end, views=10, views_es=0, artist="Artist A"):
    days = pd.date_range(start, end)
    return pd.DataFrame({"artist": artist, "date": days, "views_total": views, "views_es": views_es})


def _spotify(day, streams=1000, chart="top200", role="lead", artist="Artist A"):
    return {"artist": artist, "chart": chart, "date": pd.Timestamp(day), "streams": streams, "role": role}


@pytest.fixture
def inputs():
    shows = pd.DataFrame({"engagement_id": [1], "artist": ["Artist A"], "first_date": [SHOW_DATE]})
    credits = pd.DataFrame([
        _credit("2018-12-01", rank=1),                   # inside every window
        _credit("2018-06-01", rank=50),                  # inside 52w only
        _credit("2018-12-15", rank=10, role="featured"),
        _credit("2018-12-08", rank=200, chart="billboard200"),
    ])
    pageviews = _pageviews("2015-07-01", "2019-12-31")
    spotify = pd.DataFrame([_spotify("2018-12-01")])
    return shows, credits, pageviews, spotify


def test_chart_points_reward_high_ranks(inputs):
    features = build_features(*inputs).iloc[0]
    assert features["hot100_lead_entries_13w"] == 1
    assert features["hot100_lead_points_13w"] == 100   # #1 on a 100-slot chart
    assert features["hot100_lead_points_52w"] == 100 + 51
    assert features["hot100_featured_points_13w"] == 91
    assert features["billboard200_lead_points_13w"] == 1  # last place earns 1
    assert features["hot100_best_rank_52w"] == 1


def test_signals_ignore_everything_on_or_after_the_cutoff(inputs):
    shows, credits, pageviews, spotify = inputs
    baseline = build_features(shows, credits, pageviews, spotify)

    # A tour announcement spike: huge chart runs, pageviews and streams from
    # the cutoff day through the show. None of it may change any feature.
    future_credits = pd.DataFrame([_credit(day, rank=1) for day in
                                   pd.date_range(CUTOFF, SHOW_DATE, freq="7D")])
    future_spotify = pd.DataFrame([_spotify(CUTOFF, streams=10**9)])
    leaked = build_features(
        shows,
        pd.concat([credits, future_credits], ignore_index=True),
        pageviews.assign(views_total=np.where(pageviews["date"] >= CUTOFF, 10**6, 10),
                         views_es=np.where(pageviews["date"] >= CUTOFF, 10**6, 0)),
        pd.concat([spotify, future_spotify], ignore_index=True),
    )
    pd.testing.assert_frame_equal(baseline, leaked)


def test_show_date_cutoff_does_see_recent_data(inputs):
    # The robustness version (cutoff_days=0) should pick up the pre-show buzz
    shows, credits, pageviews, spotify = inputs
    recent = pd.DataFrame([_credit("2019-06-01", rank=1)])
    features = build_features(shows, pd.concat([credits, recent]), pageviews, spotify, cutoff_days=0)
    assert features.iloc[0]["hot100_lead_entries_13w"] == 1


def test_pageviews_are_null_before_the_data_starts(inputs):
    shows, credits, pageviews, spotify = inputs
    early = shows.assign(first_date=pd.Timestamp("2016-06-01"))  # 52w window starts in 2014
    features = build_features(early, credits, pageviews, spotify).iloc[0]
    assert np.isnan(features["pageviews_mean_52w"])
    assert features["in_model_window"] == 0
    assert not np.isnan(features["pageviews_mean_13w"])  # 13w window is covered


def test_pageviews_mean_and_momentum(inputs):
    shows, credits, pageviews, spotify = inputs
    features = build_features(shows, credits, pageviews, spotify).iloc[0]
    assert features["pageviews_mean_52w"] == pytest.approx(10)
    assert features["pageviews_momentum"] == pytest.approx(0)  # flat attention
    assert features["in_model_window"] == 1


def test_spotify_counts_streams_inside_the_data(inputs):
    features = build_features(*inputs).iloc[0]
    assert features["spotify_lead_streams_13w"] == 1000
    assert features["spotify_lead_streams_52w"] == 1000


def test_spotify_is_null_when_window_starts_before_the_data(inputs):
    shows, credits, pageviews, spotify = inputs
    # Cutoff 2017-06-02: the 13w window is inside Spotify's 2017-2021 data,
    # the 52w window starts in mid-2016, before it
    early = shows.assign(first_date=pd.Timestamp("2017-12-01"))
    features = build_features(early, credits, pageviews, spotify).iloc[0]
    assert features["spotify_lead_streams_13w"] == 0
    assert np.isnan(features["spotify_lead_streams_52w"])


def test_pageviews_add_spanish_views_and_keep_an_english_only_version(inputs):
    shows, credits, _, spotify = inputs
    pageviews = _pageviews("2015-07-01", "2019-12-31", views=10, views_es=30)
    features = build_features(shows, credits, pageviews, spotify).iloc[0]
    assert features["pageviews_mean_52w"] == pytest.approx(40)
    assert features["pageviews_en_mean_52w"] == pytest.approx(10)


def test_top10_weeks_count_only_ranks_ten_and_better(inputs):
    features = build_features(*inputs).iloc[0]
    assert features["hot100_lead_top10_52w"] == 1          # the #1, not the #50
    assert features["billboard200_lead_top10_13w"] == 0    # #200 isn't a top-10 week


def test_chart_momentum_is_zero_when_activity_is_steady():
    shows = pd.DataFrame({"engagement_id": [1], "artist": ["Artist A"], "first_date": [SHOW_DATE]})
    # One #1 week every 4 weeks for a year: the last 13 weeks look like the year
    weeks = pd.date_range(CUTOFF - pd.Timedelta(weeks=52), CUTOFF - pd.Timedelta(days=1), freq="28D")
    credits = pd.DataFrame([_credit(week) for week in weeks])
    features = build_features(shows, credits, _pageviews("2015-07-01", "2019-12-31"),
                              pd.DataFrame([_spotify("2018-12-01")])).iloc[0]
    assert abs(features["hot100_lead_momentum"]) < 0.25


def test_spotify_keeps_lead_and_featured_streams_apart(inputs):
    shows, credits, pageviews, _ = inputs
    spotify = pd.DataFrame([_spotify("2018-12-01", streams=1000),
                            _spotify("2018-12-02", streams=50, role="featured")])
    features = build_features(shows, credits, pageviews, spotify).iloc[0]
    assert features["spotify_lead_streams_13w"] == 1000
    assert features["spotify_featured_streams_13w"] == 50


def test_co_headlined_show_uses_the_stronger_act_whole():
    shows = pd.DataFrame({"engagement_id": [7], "artist": ["Small Act"], "first_date": [SHOW_DATE],
                          "co_headliners": ["Big Act"]})
    pageviews = pd.concat([_pageviews("2015-07-01", "2019-12-31", views=10, artist="Small Act"),
                           _pageviews("2015-07-01", "2019-12-31", views=500, artist="Big Act")])
    # The weaker act has the chart hit: a per-column max would wrongly mix it in
    credits = pd.DataFrame([_credit("2018-12-01", artist="Small Act")])
    spotify = pd.DataFrame([_spotify("2018-12-01", artist="Small Act")])
    features = build_features(shows, credits, pageviews, spotify)
    assert len(features) == 1
    row = features.iloc[0]
    assert (row["artist"], row["signal_artist"]) == ("Small Act", "Big Act")
    assert row["pageviews_mean_52w"] == pytest.approx(500)
    assert row["hot100_lead_entries_52w"] == 0


def test_solo_show_signals_belong_to_the_headliner(inputs):
    features = build_features(*inputs).iloc[0]
    assert features["signal_artist"] == features["artist"] == "Artist A"
