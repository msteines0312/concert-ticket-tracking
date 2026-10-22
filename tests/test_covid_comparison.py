"""Tests for the pre vs. post COVID interaction model."""

import numpy as np
import pandas as pd

from concert_demand.models import sellout
from concert_demand.models.covid_comparison import comparison_sample, design


def _shows(eras, years):
    n = len(eras)
    frame = pd.DataFrame({column: np.linspace(0, 1, n) + i
                          for i, column in enumerate(sellout.block_columns(
                              ["controls", "charts", "pageviews", "career"], []))})
    frame["covid_era"] = eras
    frame["first_date"] = [f"{y}-06-01" for y in years]
    for column, reference in sellout.CATEGORICAL_CONTROLS.items():
        frame[column] = reference
    return frame


def test_shutdown_era_shows_are_left_out():
    shows = _shows(["pre", "during", "post"], [2019, 2020, 2022])
    assert comparison_sample(shows)["covid_era"].tolist() == ["pre", "post"]


def test_interactions_are_zero_before_covid_and_post_has_no_main_effect():
    shows = _shows(["pre", "pre", "post", "post"], [2018, 2019, 2022, 2023])
    X, signals, interactions = design(shows, sellout.control_dummies(shows))
    pre = X.iloc[:2]
    assert (pre[list(interactions)] == 0).all().all()
    assert not any(column.startswith("post") for column in X)   # absorbed by year dummies
    assert len(interactions) == len(signals)
