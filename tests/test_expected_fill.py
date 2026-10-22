"""Tests for the combined expected fill rate and the Tobit check."""

import numpy as np
import pytest
from scipy import optimize

from concert_demand.models.expected_fill import (
    CEILING,
    fit_tobit,
    root_mean_squared_error,
    tobit_expected_fill,
    tobit_negative_loglik,
)


def _censored(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    latent = 0.95 + 0.05 * x + rng.normal(0, 0.05, n)  # true beta = (0.95, 0.05), sigma = 0.05
    return x[:, None], np.minimum(latent, CEILING), latent >= CEILING


def test_analytic_gradient_matches_a_numerical_one():
    X, y, censored = _censored(500)
    X1 = np.column_stack([np.ones(len(X)), X])
    params = np.array([0.9, 0.04, np.log(0.06)])
    error = optimize.check_grad(lambda p: tobit_negative_loglik(p, X1, y, censored)[0],
                                lambda p: tobit_negative_loglik(p, X1, y, censored)[1], params)
    assert error < 1e-3 * np.abs(tobit_negative_loglik(params, X1, y, censored)[1]).max()


def test_tobit_recovers_parameters_despite_the_ceiling():
    X, y, censored = _censored()
    assert censored.mean() > 0.2  # about 24% hit the ceiling: enough to test censoring
    beta, sigma = fit_tobit(X, y, censored)
    assert beta == pytest.approx([0.95, 0.05], abs=0.005)
    assert sigma == pytest.approx(0.05, abs=0.003)


def test_expected_fill_matches_simulated_capped_demand():
    rng = np.random.default_rng(1)
    beta, sigma = np.array([0.97, 0.0]), 0.05
    simulated = np.minimum(rng.normal(0.97, sigma, 200_000), CEILING).mean()
    assert tobit_expected_fill(np.zeros((1, 1)), beta, sigma)[0] == pytest.approx(simulated, abs=1e-3)


def test_rmse():
    assert root_mean_squared_error(np.array([3.0, -4.0])) == pytest.approx(np.sqrt(12.5))
