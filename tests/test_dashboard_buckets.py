"""Tests for the dashboard's grid buckets and flagged-tour rule."""

import numpy as np
import pandas as pd

from concert_demand.dashboard.buckets import (
    is_flagged_tour,
    prev_fill_bucket,
    room_change_bucket,
)


def test_room_bucket_edges():
    # "Same" is within 10% either way; 2.0 exactly is still "Up to 2x".
    buckets = room_change_bucket(pd.Series([0.5, 0.9, 1.0, 1.1, 1.11, 2.0, 2.01, np.nan]))
    assert buckets.tolist()[:7] == [
        "Smaller", "Same", "Same", "Same", "Up to 2x", "Up to 2x", "2x+"]
    assert pd.isna(buckets.iloc[7])


def test_fill_bucket_edges():
    # Only an exactly full previous tour counts as 100%, matching the sellout definition.
    buckets = prev_fill_bucket(pd.Series([0.80, 0.90, 0.95, 0.999, 1.0, np.nan]))
    assert buckets.tolist()[:5] == ["Under 90%", "90-95%", "95-99.9%", "95-99.9%", "100%"]
    assert pd.isna(buckets.iloc[5])


def test_flag_threshold_is_half_or_more():
    assert is_flagged_tour(pd.Series([0.0, 0.49, 0.5, 1.0])).tolist() == [False, False, True, True]
