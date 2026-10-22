"""Tests for the Part 1 sellout ladders."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.models import sellout
from concert_demand.models.sellout import (
    add_model_columns,
    control_dummies,
    ladder_rows,
    run_ladder,
    tour_bootstrap_auc,
)


def _controls(n, **overrides):
    frame = pd.DataFrame({"venue_size": ["2. 5K-20K (arenas, amphitheaters)"] * n,
                          "genre_group": ["Rock/Alternative"] * n,
                          "country": ["United States"] * n})
    for column, values in overrides.items():
        frame[column] = values
    return frame


def test_dummies_keep_the_same_columns_when_a_split_lacks_a_level():
    data = _controls(3, genre_group=["Rock/Alternative", "Pop", "Latin"])
    dummies = control_dummies(data)
    assert "genre_group=Pop" in dummies and "genre_group=Latin" in dummies
    assert "genre_group=Rock/Alternative" not in dummies  # reference level
    # A test split with only rock shows still gets the Pop column (all zeros).
    assert dummies.iloc[[0]]["genre_group=Pop"].tolist() == [0]


def test_every_ladder_step_scores_the_same_rows():
    data = pd.DataFrame({column: [1.0, 1.0, 1.0]
                         for block in sellout.BLOCKS.values() for column in block})
    data["split"] = ["train", "test_2019", "excluded"]
    data.loc[1, "prev_tour_sellout_rate"] = np.nan  # only the history ladder needs this
    assert ladder_rows(data, "charts_first").tolist() == [True, True, False]
    assert ladder_rows(data, "history").tolist() == [True, False, False]


def test_identical_predictions_gain_exactly_nothing():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200)
    p = rng.random(200)
    tours = np.repeat(np.arange(20), 10)
    intervals = tour_bootstrap_auc(y, {"a": p, "b": p.copy()}, tours, n_boot=50)
    gain = intervals.iloc[1]
    assert gain["gain_low"] == 0 and gain["gain_high"] == 0


def test_a_perfect_predictor_has_auc_one_in_every_resample():
    y = np.array([0, 1] * 50)
    tours = np.repeat(np.arange(10), 10)
    intervals = tour_bootstrap_auc(y, {"perfect": y.astype(float)}, tours, n_boot=50)
    assert intervals.iloc[0]["auc_low"] == 1.0


def test_a_block_that_drives_the_outcome_raises_test_auc(monkeypatch):
    # Synthetic shows where sellouts depend on pageviews only.
    rng = np.random.default_rng(1)
    n = 600
    data = _controls(n)
    data["log_capacity_per_show"] = rng.normal(9, 1, n)
    data["log_pageviews_52w"] = rng.normal(0, 1, n)
    data["pageviews_momentum"] = rng.normal(0, 1, n)
    data["sold_out"] = (data["log_pageviews_52w"] + rng.normal(0, 0.5, n) > 0).astype(int)
    data["tour"] = np.repeat(np.arange(60), 10)
    data["split"] = np.where(data["tour"] < 40, "train", "test_2019")

    monkeypatch.setattr(sellout, "LADDERS", {"toy": ["controls", "pageviews"]})
    monkeypatch.setattr(sellout, "TEST_SPLITS", ["test_2019"])
    monkeypatch.setattr(sellout, "N_BOOTSTRAP", 50)
    results = run_ladder(data, control_dummies(data), "toy")

    controls, pageviews = results["auc"].tolist()
    assert controls == pytest.approx(0.5, abs=0.1)
    assert pageviews > 0.9
    assert results.iloc[1]["gain_low"] > 0


def test_room_interaction_is_zero_after_a_full_tour():
    data = pd.DataFrame({"hot100_lead_entries_career": [0, 0], "billboard200_lead_entries_career": [0, 0],
                         "prev_tour_price_2024usd": [100.0, 100.0], "log2_room_ratio": [1.0, 1.0],
                         "prev_tour_fill_rate": [1.0, 0.9]})
    out = add_model_columns(data)
    # Doubling after a 100%-full tour: only the main effect applies.
    assert out["room_x_prev_unfilled"].tolist() == pytest.approx([0.0, 0.1])
