"""Tests for the right-sizing (upsizing risk) score."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.models.right_sizing import score_shows

# Doubling the room: odds x e^0.35 after a full tour, break-even at 95% full.
EFFECT = {"room_main": 0.35, "room_interaction": -7.0, "break_even_fill": 0.95}


def _shows(log2_ratios, prev_fills):
    n = len(log2_ratios)
    return pd.DataFrame({"engagement_id": range(n), "artist": "Act", "tour": "Tour",
                         "first_date": "2019-01-01", "split": "test_2019", "prev_tour": "Old",
                         "log2_room_ratio": log2_ratios, "prev_tour_fill_rate": prev_fills,
                         "room_up": np.clip(log2_ratios, 0, None),
                         "sold_out": 1, "fill_rate": 1.0})


def test_upsizing_after_a_full_tour_helps_and_after_a_soft_tour_hurts():
    scores = score_shows(_shows([1.0, 1.0], [1.0, 0.85]), EFFECT)
    assert scores["upsize_odds_multiplier"].tolist() == pytest.approx(
        [np.exp(0.35), np.exp(0.35 - 7.0 * 0.15)])
    assert scores["upsized_past_rule"].tolist() == [0, 1]


def test_downsizing_is_not_scored_as_a_risk():
    scores = score_shows(_shows([-2.5], [1.0]), EFFECT)   # stadiums to theaters after a sellout tour
    assert scores["upsize_odds_multiplier"].iloc[0] == 1.0
    assert scores["upsized_past_rule"].iloc[0] == 0


def test_shows_without_a_previous_tour_are_not_scored():
    assert score_shows(_shows([np.nan], [np.nan]), EFFECT).empty
