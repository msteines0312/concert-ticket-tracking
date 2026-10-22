"""Tests for the Part 2 fractional logit."""

import numpy as np
import pandas as pd
import pytest

from concert_demand.models.fill_rate import fit_fractional_logit, predict_fill, tour_bootstrap_mae


def _rates(n=2000, slope=0.8, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    rate = 1 / (1 + np.exp(-(1.5 + slope * x)))  # true fill rate on the log-odds scale
    return pd.DataFrame({"x": x}), pd.Series(np.clip(rate + rng.normal(0, 0.02, n), 0, 1))


def test_fractional_logit_recovers_the_log_odds_slope():
    X, y = _rates()
    fit = fit_fractional_logit(X, y)
    assert fit.params["x"] == pytest.approx(0.8, abs=0.05)


def test_predictions_stay_between_zero_and_one():
    X, y = _rates()
    far_out = pd.DataFrame({"x": [-50.0, 50.0]})  # extreme inputs a linear model would push past 0-1
    p = predict_fill(X, y, far_out)
    assert ((p >= 0) & (p <= 1)).all()


def test_identical_predictions_change_mae_by_nothing():
    y = np.linspace(0.5, 0.99, 100)
    p = np.full(100, 0.9)
    intervals = tour_bootstrap_mae(y, {"a": p, "b": p.copy()}, np.repeat(np.arange(10), 10), n_boot=30)
    assert intervals[1]["change_low"] == 0 and intervals[1]["change_high"] == 0
