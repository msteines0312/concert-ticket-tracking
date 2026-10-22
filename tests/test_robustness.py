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
