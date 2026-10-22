"""Tests for the modeling dataset: transforms, previous-tour history and splits."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.models.dataset import (
    PRICE_COLUMN,
    add_signal_transforms,
    assign_split,
    previous_tour_history,
    usable_history,
)

CPI = pd.DataFrame({"year": [2014, 2016, 2018, 2024], "cpi_u": [200.0, 200.0, 200.0, 300.0]})


def _engagement(tour, first, last=None, sold_out=1, revenue=1000.0, tickets=10, artist="Act",
                fill_rate=1.0, **flags):
    row = {"artist": artist, "tour": tour, "first_date": pd.Timestamp(first),
           "last_date": pd.Timestamp(last or first), "sold_out": sold_out, "fill_rate": fill_rate,
           "revenue_usd": revenue, "tickets_sold": tickets, "is_festival": 0,
           "suspect_capacity": 0, "conflicting_sources": 0, "covid_era": "pre"}
    row.update(flags)
    return row


def _show(tour="New Tour", cutoff="2018-06-01", artist="Act", engagement_id=1):
    return {"engagement_id": engagement_id, "artist": artist, "tour": tour,
            "cutoff_date": pd.Timestamp(cutoff)}


def _history(rows):
    return usable_history(pd.DataFrame(rows), CPI)


# --- transforms -------------------------------------------------------------

def test_not_charting_is_zero_points_with_a_flag():
    shows = pd.DataFrame({"hot100_lead_points_52w": [np.nan, 0, 99],
                          "billboard200_lead_points_52w": [0, 0, 0],
                          "pageviews_mean_52w": [0, 9, 99], "pageviews_en_mean_52w": [0, 9, 99],
                          "capacity_per_show": [1000, 1000, 1000]})
    out = add_signal_transforms(shows)
    assert out["hot100_charted_52w"].tolist() == [0, 0, 1]
    assert out["log_hot100_points_52w"].tolist() == pytest.approx([0, 0, np.log(100)])
    assert out["log_pageviews_52w"].tolist() == pytest.approx([0, np.log(10), np.log(100)])


# --- previous-tour history --------------------------------------------------

def test_previous_tour_is_the_most_recent_other_tour():
    history = _history([_engagement("Old Tour", "2014-05-01", sold_out=1),
                        _engagement("Recent Tour", "2016-05-01", sold_out=0),
                        _engagement("New Tour", "2017-01-01")])  # the show's own tour
    result = previous_tour_history(pd.DataFrame([_show()]), history, min_shows=1).iloc[0]
    assert result["prev_tour"] == "Recent Tour"
    assert result["prev_tour_sellout_rate"] == 0


def test_shows_ending_after_the_cutoff_are_not_known_yet():
    history = _history([_engagement("Old Tour", "2014-05-01"),
                        # Started before the cutoff but ended on it: outcome not known yet.
                        _engagement("Recent Tour", "2018-05-01", last="2018-06-01")])
    result = previous_tour_history(pd.DataFrame([_show()]), history, min_shows=1).iloc[0]
    assert result["prev_tour"] == "Old Tour"


def test_a_tour_still_running_counts_only_its_finished_shows():
    history = _history([_engagement("Recent Tour", "2018-01-01", sold_out=1),
                        _engagement("Recent Tour", "2018-09-01", sold_out=0)])  # after cutoff
    result = previous_tour_history(pd.DataFrame([_show()]), history, min_shows=1).iloc[0]
    assert result["prev_tour_shows"] == 1
    assert result["prev_tour_sellout_rate"] == 1


def test_price_is_ticket_weighted_and_in_constant_dollars():
    history = _history([_engagement("Recent Tour", "2016-01-01", revenue=1000, tickets=10),
                        _engagement("Recent Tour", "2016-02-01", revenue=9000, tickets=30)])
    result = previous_tour_history(pd.DataFrame([_show()]), history, min_shows=1).iloc[0]
    # (1000 + 9000) / 40 tickets = $250 nominal, x 300/200 CPI = $375
    assert result[PRICE_COLUMN] == pytest.approx(375)


def _tour_run(tour, start, n, **kwargs):
    """n one-night engagements, a week apart."""
    return [_engagement(tour, pd.Timestamp(start) + pd.Timedelta(weeks=i), **kwargs) for i in range(n)]


def test_a_tour_that_barely_started_falls_back_to_the_one_before():
    # Bad Bunny case: a new tour is 1 show in at the cutoff, the old one had 36.
    history = _history(_tour_run("Old Tour", "2016-01-01", 6, sold_out=0)
                       + _tour_run("Just Started", "2018-05-20", 1))
    result = previous_tour_history(pd.DataFrame([_show()]), history).iloc[0]
    assert result["prev_tour"] == "Old Tour"
    assert result["prev_tour_shows"] == 6


def test_too_few_shows_anywhere_means_no_history():
    # Future case: the page lists a single box score row.
    history = _history(_tour_run("One Row Tour", "2017-08-24", 1))
    result = previous_tour_history(pd.DataFrame([_show()]), history).iloc[0]
    assert result["prev_tour"] is None


def test_fill_rate_separates_near_misses_from_flops():
    history = _history(_tour_run("Near Miss", "2016-01-01", 5, sold_out=0, fill_rate=0.96))
    result = previous_tour_history(pd.DataFrame([_show()]), history).iloc[0]
    assert result["prev_tour_sellout_rate"] == 0
    assert result["prev_tour_fill_rate"] == pytest.approx(0.96)


def test_flagged_and_shutdown_rows_are_not_history():
    history = _history([_engagement("Fest", "2016-01-01", is_festival=1),
                        _engagement("Drive-in", "2016-01-01", covid_era="during")])
    assert history.empty


def test_no_history_gives_nulls_and_zero_shows():
    history = _history([_engagement("Other Act Tour", "2016-01-01", artist="Someone Else")])
    result = previous_tour_history(pd.DataFrame([_show()]), history, min_shows=1).iloc[0]
    assert result["prev_tour"] is None
    assert result["prev_tour_shows"] == 0
    assert np.isnan(result["prev_tour_sellout_rate"])


# --- splits -----------------------------------------------------------------

def _split_show(tour, first, era="pre"):
    return {"tour": tour, "first_date": pd.Timestamp(first), "covid_era": era}


def test_whole_tours_go_to_one_split_by_their_first_show():
    shows = pd.DataFrame([_split_show("A", "2018-11-01"), _split_show("A", "2019-03-01"),
                          _split_show("B", "2019-02-01"), _split_show("C", "2022-05-01")])
    assert assign_split(shows).tolist() == ["train", "train", "test_2019", "holdout_post"]


def test_post_shutdown_shows_on_pre_covid_tours_are_excluded():
    shows = pd.DataFrame([_split_show("A", "2019-06-01"),
                          _split_show("A", "2021-09-01", era="post")])
    assert assign_split(shows).tolist() == ["test_2019", "excluded"]


def test_tours_starting_during_the_shutdown_are_excluded():
    shows = pd.DataFrame([_split_show("A", "2021-06-01", era="during"),
                          _split_show("A", "2021-09-01", era="post")])
    assert assign_split(shows).tolist() == ["excluded", "excluded"]
