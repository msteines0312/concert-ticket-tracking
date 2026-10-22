"""Tests for the robustness checks."""

import pandas as pd
import pytest

from concert_demand.models.robustness import room_effect


def test_break_even_is_where_doubling_the_room_changes_nothing():
    table = pd.DataFrame({"predictor": ["log2_room_ratio", "room_x_prev_unfilled"],
                          "coef": [0.5, -10.0], "p_value": [0.1, 0.01]})
    effect = room_effect(table)
    # 0.5 - 10 * unfilled = 0 at unfilled = 0.05, i.e. 95% full
    assert effect["break_even_fill"] == pytest.approx(0.95)
    assert effect["interaction_p"] == 0.01


def test_swapped_signals_rebuild_the_model_columns_and_keep_the_index():
    import numpy as np
    from concert_demand.models.robustness import swap_signals

    dataset = pd.DataFrame({
        "engagement_id": [10, 11], "hot100_lead_points_52w": [0.0, 0.0],
        "billboard200_lead_points_52w": [0.0, 0.0], "pageviews_mean_52w": [100.0, 100.0],
        "pageviews_en_mean_52w": [50.0, 50.0], "capacity_per_show": [1000, 1000],
        "hot100_lead_entries_career": [0, 0], "billboard200_lead_entries_career": [0, 0],
        "prev_tour_price_2024usd": [100.0, 100.0], "show_price_2024usd": [90.0, 90.0],
        "log2_room_ratio": [0.0, 0.0], "prev_tour_fill_rate": [1.0, 1.0], "n_shows": [1, 1]},
        index=[7, 3])
    replacement = pd.DataFrame({"engagement_id": [11, 10], "pageviews_mean_52w": [999.0, 9.0]})
    out = swap_signals(dataset, replacement)
    assert out.index.tolist() == [7, 3]
    assert out["log_pageviews_52w"].tolist() == pytest.approx([np.log(10), np.log(1000)])
