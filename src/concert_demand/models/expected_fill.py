"""Combine Parts 1 and 2 into one expected fill rate, with a Tobit model as a check.

Two-part model (Matt's outcome design from Phase 0):
    expected fill = P(sellout) x 100% + (1 - P(sellout)) x E[fill | not sold out]
Part 1 is the sellout logistic regression, Part 2 the fractional logit on
non-sellouts, each fit on train tours with the same predictor blocks.

Tobit (robustness): one model for fill rate that treats sold-out shows as
censored at 100%. The idea is that demand could have exceeded the room but
the room capped what was observed. It assumes one process drives both
"sold out or not" and "how full", which the two-part model does not, so
agreement between the two means the result doesn't hinge on that choice.
statsmodels has no Tobit, so the likelihood is written out below.

Scoring: root mean squared error (percentage points) on all shows in each
test split. Expected fill is an average, and squared error is the score
that rewards getting averages right. MAE was the first choice, but it
rewards predicting the median, and the median show sold out: predicting
100% for every show scored an MAE of 2.4-2.9 points against 6.5-7.3 for
every model, while saying nothing. MAE is still reported. Two baselines:
the training mean for every show, and 100% for every show.

Usage
-----
    python -m concert_demand.models.expected_fill
"""

import logging

import numpy as np
import pandas as pd
from scipy import optimize, stats

from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH
from concert_demand.models.fill_rate import predict_fill, standardize, tour_bootstrap_mae

CEILING = 1.0
VARIANTS = {  # name -> predictor blocks used by every model in that row
    "controls": ["controls"],
    "full": ["controls", "charts", "pageviews", "career"],
}

logger = logging.getLogger(__name__)


def root_mean_squared_error(errors):
    """RMSE of an error array."""
    return np.sqrt(np.mean(np.square(errors)))


# ---------------------------------------------------------------------------
# Tobit, right-censored at 100%
# ---------------------------------------------------------------------------

def tobit_negative_loglik(params, X, y, censored):
    """Negative log-likelihood of a Tobit model censored from above at CEILING, and its gradient.

    Uncensored shows contribute the normal density of their fill rate;
    sold-out shows contribute the probability that latent demand reached
    the ceiling. Sigma is fit on the log scale so it stays positive.

    The exact gradient is returned too. With scipy's numerical estimate the
    optimizer stopped early ("precision loss") because the estimate was too
    noisy near the optimum.

    Returns
    -------
    tuple of (float, numpy.ndarray)
    """
    beta, log_sigma = params[:-1], params[-1]
    sigma = np.exp(log_sigma)
    mean = X @ beta
    r = (y - mean) / sigma                 # standardized residual, uncensored shows
    z = (CEILING - mean) / sigma           # standardized distance to the ceiling, sold-out shows
    loglik = np.where(censored, stats.norm.logsf(z), stats.norm.logpdf(r) - log_sigma)

    # Inverse Mills ratio phi(z) / (1 - Phi(z)), computed on the log scale for stability.
    mills = np.exp(stats.norm.logpdf(z) - stats.norm.logsf(z))
    d_mean = np.where(censored, mills, r) / sigma            # d loglik / d mean
    d_log_sigma = np.where(censored, mills * z, r ** 2 - 1)  # d loglik / d log(sigma)
    gradient = np.append(X.T @ d_mean, d_log_sigma.sum())
    return -loglik.sum(), -gradient


def fit_tobit(X, y, censored):
    """Fit the Tobit model by maximum likelihood.

    Returns
    -------
    tuple of (numpy.ndarray, float)
        Coefficients (constant first) and sigma.
    """
    X = np.column_stack([np.ones(len(X)), X])
    start = np.append(np.linalg.lstsq(X, y, rcond=None)[0], np.log(y.std()))
    result = optimize.minimize(tobit_negative_loglik, start, args=(X, y, censored),
                               jac=True, method="BFGS")
    # Judge convergence by the gradient itself: at a maximum it is ~0 per show.
    gradient_per_show = np.abs(result.jac).max() / len(y)
    if gradient_per_show > 1e-4:
        raise RuntimeError(f"Tobit did not converge: {result.message}")
    return result.x[:-1], float(np.exp(result.x[-1]))


def tobit_expected_fill(X, beta, sigma):
    """Expected observed fill rate: the latent demand, capped at CEILING.

    E[min(y*, c)] = c * P(y* >= c) + E[y* ; y* < c]
                  = c * (1 - Phi(z)) + mean * Phi(z) - sigma * phi(z),  z = (c - mean) / sigma
    """
    mean = np.column_stack([np.ones(len(X)), X]) @ beta
    z = (CEILING - mean) / sigma
    return CEILING * stats.norm.sf(z) + mean * stats.norm.cdf(z) - sigma * stats.norm.pdf(z)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def two_part_prediction(train, test, columns):
    """Expected fill for test shows from the two-part model."""
    p_sellout = sellout.fit_predict(train[columns], train["sold_out"], test[columns])
    misses = train[train["sold_out"] == 0]
    fill_if_miss = predict_fill(misses[columns], misses["fill_rate"], test[columns])
    return p_sellout * CEILING + (1 - p_sellout) * fill_if_miss


def tobit_prediction(train, test, columns):
    """Expected fill for test shows from the Tobit model."""
    X_train, X_test = standardize(train[columns].astype(float), test[columns].astype(float))
    beta, sigma = fit_tobit(X_train.to_numpy(), train["fill_rate"].to_numpy(),
                            train["sold_out"].to_numpy() == 1)
    return tobit_expected_fill(X_test.to_numpy(), beta, sigma)


def score_variants(dataset, dummies):
    """RMSE and MAE of every model on each test split, with paired RMSE intervals vs. the mean baseline."""
    rows = sellout.ladder_rows(dataset, "charts_first")
    data = pd.concat([dataset[rows], dummies[rows]], axis=1)
    train = data[data["split"] == "train"]
    results = []
    for test_split in sellout.TEST_SPLITS:
        test = data[data["split"] == test_split]
        predictions = {"mean_only": np.full(len(test), train["fill_rate"].mean()),
                       "always_100": np.full(len(test), CEILING)}
        for variant, blocks in VARIANTS.items():
            columns = sellout.block_columns(blocks, dummies.columns)
            predictions[f"two_part_{variant}"] = two_part_prediction(train, test, columns)
            predictions[f"tobit_{variant}"] = tobit_prediction(train, test, columns)
        y = test["fill_rate"].to_numpy()
        for model, p in predictions.items():
            # Each model vs. the mean-only baseline, paired on the same resampled tours.
            interval = tour_bootstrap_mae(y, {"base": predictions["mean_only"], model: p},
                                          test["tour"].to_numpy(),
                                          metric=root_mean_squared_error)[1]
            results.append({"test_split": test_split, "model": model, "test_shows": len(test),
                            "test_tours": test["tour"].nunique(),
                            "rmse_pts": 100 * root_mean_squared_error(y - p),
                            "mae_pts": 100 * np.mean(np.abs(y - p)),
                            "mean_predicted": float(np.mean(p)), "actual_mean": float(np.mean(y)),
                            "vs_baseline_low": 100 * interval["change_low"],
                            "vs_baseline_high": 100 * interval["change_high"]})
    return pd.DataFrame(results)


def run(dataset_path=DATASET_PATH):
    """Score the combined models and save the table."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    results = score_variants(dataset, sellout.control_dummies(dataset))
    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(sellout.TABLES_DIR / "expected_fill.csv", index=False)
    logger.info("Expected fill (RMSE and MAE, percentage points):\n%s", results[
        ["test_split", "model", "rmse_pts", "vs_baseline_low", "vs_baseline_high", "mae_pts",
         "mean_predicted", "actual_mean"]].round(3).to_string(index=False))
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
