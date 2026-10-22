"""Tests for the dashboard star schema tables."""

import numpy as np
import pandas as pd

from concert_demand.dashboard.tables import (
    build_artists,
    build_chart_quarters,
    build_shows,
    build_tours,
)


def _model_dataset():
    """Two in-sample tours: Act A's 2019 tour (has a previous tour) and Act B's 2022 tour (doesn't)."""
    return pd.DataFrame({
        "engagement_id": [1, 2, 3],
        "artist": ["Act A", "Act A", "Act B"],
        "tour": ["Big Tour", "Big Tour", "First Tour"],
        "first_date": ["2019-05-01", "2019-06-01", "2022-03-01"],
        "capacity_per_show": [20000.0, 18000.0, 3000.0],
        "sold_out": [0, 1, 1], "fill_rate": [0.8, 1.0, 1.0],
        "hot100_lead_points_52w": [500.0, 700.0, 0.0],
        "hot100_lead_top10_52w": [2, 4, 0],
        "billboard200_lead_points_52w": [1000.0, 1000.0, 0.0],
        "pageviews_mean_52w": [9000.0, 11000.0, 400.0],
        "hot100_lead_entries_career": [30, 31, 0],
        "billboard200_lead_entries_career": [80, 82, 0],
        # The real model_dataset carries this too; build_shows must not collide with it.
        "prev_tour_fill_rate": [0.85, 0.85, np.nan],
    })


def _right_sizing_shows():
    return pd.DataFrame({"engagement_id": [1, 2], "room_ratio": [2.5, 2.2],
                         "prev_tour_fill_rate": [0.85, 0.85], "upsized_past_rule": [1, 1]})


def _right_sizing_tours(share=1.0, prev_tour="Small Tour"):
    return pd.DataFrame({"artist": ["Act A"], "tour": ["Big Tour"], "prev_tour": [prev_tour],
                         "median_room_ratio": [2.35], "prev_tour_fill_rate": [0.85],
                         "share_upsized_past_rule": [share]})


def _tour_summary(extra_rows=()):
    rows = [("Act A", "Small Tour", "2014-04-01", 0.5, 0.85),
            ("Act A", "Big Tour", "2019-05-01", 0.5, 0.9),
            ("Act B", "First Tour", "2022-03-01", 1.0, 1.0), *extra_rows]
    return pd.DataFrame(rows, columns=["artist", "tour", "tour_start", "sellout_rate", "fill_rate"])


def _engagements():
    return pd.DataFrame({"artist": ["Act A", "Act A", "Act A", "Act B"],
                         "tour": ["Small Tour", "Big Tour", "Big Tour", "First Tour"],
                         "capacity_per_show": [8000.0, 20000.0, 18000.0, 3000.0]})


def _tours(**kwargs):
    return build_tours(_tour_summary(), _engagements(), _right_sizing_tours(**kwargs), _model_dataset())


def test_tours_keep_out_of_sample_previous_tours():
    tours = _tours().set_index("tour")
    assert tours.loc[["Small Tour", "Big Tour"], "in_sample"].tolist() == [False, True]
    assert tours.loc["Small Tour", "median_room"] == 8000.0
    assert tours.loc["Big Tour", "median_room"] == 19000.0


def test_prev_tour_missing_from_summary_is_a_label_only():
    tours = _tours(prev_tour="Ghost Tour")
    assert tours.loc[tours["tour"] == "Big Tour", "prev_tour"].item() == "Ghost Tour"
    assert "Ghost Tour" not in tours["tour"].tolist()


def test_flagged_matches_half_rule():
    assert not _tours(share=0.4).set_index("tour").loc["Big Tour", "is_flagged"]
    assert _tours(share=0.6).set_index("tour").loc["Big Tour", "is_flagged"]


def test_tour_without_previous_tour_is_not_flagged():
    tours = _tours().set_index("tour")
    assert not tours.loc["First Tour", "has_prev_tour"]
    assert not tours.loc["First Tour", "is_flagged"]


def test_latest_in_sample_is_one_per_artist():
    extra = [("Act A", "Later Tour", "2023-01-01", 1.0, 1.0)]
    dataset = pd.concat([_model_dataset(), _model_dataset().iloc[[0]].assign(
        engagement_id=4, tour="Later Tour", first_date="2023-01-01")])
    engagements = pd.concat([_engagements(), pd.DataFrame(
        {"artist": ["Act A"], "tour": ["Later Tour"], "capacity_per_show": [20000.0]})])
    tours = build_tours(_tour_summary(extra), engagements, _right_sizing_tours(), dataset)
    latest = tours[tours["is_latest_in_sample"]]
    assert latest.groupby("artist").size().tolist() == [1, 1]
    assert latest.set_index("artist").loc["Act A", "tour"] == "Later Tour"


def test_hype_is_median_of_sample_shows_and_career_is_from_first_show():
    big = _tours().set_index("tour").loc["Big Tour"]
    assert big["hot100_points_52w"] == 600.0
    assert big["career_entries"] == 30 + 80
    assert np.isnan(_tours().set_index("tour").loc["Small Tour", "hot100_points_52w"])


def test_shows_have_buckets_only_with_a_previous_tour():
    shows = build_shows(_model_dataset(), _right_sizing_shows()).set_index("engagement_id")
    assert shows.loc[1, "tour_key"] == "Act A | Big Tour"
    assert shows.loc[1, "room_change_bucket"] == "2x+"
    assert shows.loc[1, "prev_fill_bucket"] == "Under 90%"
    assert pd.isna(shows.loc[3, "room_change_bucket"])
    assert pd.isna(shows.loc[3, "upsized_past_rule"])


def test_artist_without_chart_credits_is_kept():
    artists = build_artists(_tours(), pd.DataFrame({"artist": ["Act A", "Act B"],
                                                    "genre_group": ["Pop", "Latin"]}))
    credits = pd.DataFrame({"chart": ["hot100"], "chart_week": ["2019-01-05"], "rank": [1],
                            "title": ["Song"], "artist": ["Act A"], "role": ["lead"]})
    quarters = build_chart_quarters(credits, artists)
    assert set(artists["artist"]) == {"Act A", "Act B"}
    assert "Act B" not in quarters["artist"].tolist()
    assert artists.set_index("artist").loc["Act A", "latest_tour_key"] == "Act A | Big Tour"


def test_chart_quarters_have_no_ranks_or_titles():
    artists = pd.DataFrame({"artist": ["Act A"], "genre_group": ["Pop"], "latest_tour_key": ["x"]})
    credits = pd.DataFrame({
        "chart": ["hot100", "hot100", "billboard200", "hot100"],
        "chart_week": ["2019-01-05", "2019-02-02", "2019-01-05", "2019-01-05"],
        "rank": [1, 100, 200, 3], "title": ["Song", "Song", "Album", "Feature"],
        "artist": ["Act A"] * 4, "role": ["lead", "lead", "lead", "featured"]})
    quarters = build_chart_quarters(credits, artists)
    assert set(quarters.columns) == {"artist", "quarter_start", "chart", "lead_points"}
    hot100 = quarters[quarters["chart"] == "hot100"]
    # #1 earns 100, #100 earns 1, and the featured credit is left out.
    assert hot100["lead_points"].tolist() == [101]
    assert hot100["quarter_start"].astype(str).tolist() == ["2019-01-01"]
    assert quarters.loc[quarters["chart"] == "billboard200", "lead_points"].tolist() == [1]
