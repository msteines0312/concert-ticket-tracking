"""Part 2: how full do shows get when they don't sell out?

Matt's design (2026-10-21): a fractional logit, which is a binomial GLM fit
directly on the fill rate. Like logistic regression it works on the
log-odds scale, so predictions stay between 0 and 100% and coefficients
read like Part 1's. It is fit only on shows that did not sell out (about
1,600, median 91% full), using Part 1's blocks, rows and dummies.

Scored by mean absolute error in percentage points against a baseline that
predicts the training mean for every show. Intervals resample whole tours,
as in Part 1. The explanatory version uses year dummies and standard
errors clustered by artist.

Usage
-----
    python -m concert_demand.models.fill_rate
"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm

from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH

OUTCOME = "fill_rate"
LADDERS = ["charts_first", "pageviews_first"]

logger = logging.getLogger(__name__)


def standardize(X_train, X_other):
    """Scale columns by the training mean and SD; constant columns are only centered."""
    mean, sd = X_train.mean(), X_train.std().replace(0, 1)
    return (X_train - mean) / sd, (X_other - mean) / sd


def fit_fractional_logit(X, y, groups=None):
    """Fit a binomial GLM on a rate between 0 and 1.

    Parameters
    ----------
    X : pandas.DataFrame
        Predictors (a constant is added here).
    y : pandas.Series
        Fill rates.
    groups : array-like, optional
        Cluster labels; when given, standard errors are clustered on them.

    Returns
    -------
    statsmodels GLMResults
    """
    kwargs = {"cov_type": "cluster", "cov_kwds": {"groups": groups}} if groups is not None else {}
    # A binomial GLM accepts non-integer outcomes between 0 and 1; statsmodels
    # warns about it, but the quasi-likelihood estimate is the standard
    # fractional logit (Papke and Wooldridge, 1996).
    return sm.GLM(y, sm.add_constant(X, has_constant="add"),
                  family=sm.families.Binomial()).fit(**kwargs)


def predict_fill(X_train, y_train, X_test):
    """Fit on train shows and predict fill rates for test shows."""
    X_train, X_test = standardize(X_train.astype(float), X_test.astype(float))
    fit = fit_fractional_logit(X_train, y_train)
    return np.asarray(fit.predict(sm.add_constant(X_test, has_constant="add")))


def tour_bootstrap_mae(y_true, predictions, tours, n_boot=sellout.N_BOOTSTRAP, seed=sellout.SEED):
    """95% intervals for each step's MAE and its change from the step before (paired by tour)."""
    rng = np.random.default_rng(seed)
    unique_tours = np.unique(tours)
    rows_by_tour = {tour: np.flatnonzero(tours == tour) for tour in unique_tours}
    steps = list(predictions)
    maes = {step: [] for step in steps}
    for _ in range(n_boot):
        rows = np.concatenate([rows_by_tour[t] for t in rng.choice(unique_tours, len(unique_tours))])
        for step in steps:
            maes[step].append(np.mean(np.abs(y_true[rows] - predictions[step][rows])))
    out = []
    for i, step in enumerate(steps):
        mae = np.array(maes[step])
        row = {"mae_low": np.percentile(mae, 2.5), "mae_high": np.percentile(mae, 97.5)}
        if i > 0:
            change = mae - np.array(maes[steps[i - 1]])
            row.update(change_low=np.percentile(change, 2.5), change_high=np.percentile(change, 97.5))
        out.append(row)
    return out


def run_ladder(dataset, dummies, ladder):
    """Score each step of a Part 1 ladder on non-sellouts, starting from a mean-only baseline.

    Returns
    -------
    pandas.DataFrame
        One row per (test split, step): MAE in percentage points, change
        from the previous step, and bootstrap intervals.
    """
    rows = sellout.ladder_rows(dataset, ladder) & (dataset["sold_out"] == 0)
    data = pd.concat([dataset[rows], dummies[rows]], axis=1)
    train = data[data["split"] == "train"]
    results = []
    for test_split in sellout.TEST_SPLITS:
        test = data[data["split"] == test_split]
        predictions = {"mean_only": np.full(len(test), train[OUTCOME].mean())}
        for depth in range(1, len(sellout.LADDERS[ladder]) + 1):
            blocks = sellout.LADDERS[ladder][:depth]
            columns = sellout.block_columns(blocks, dummies.columns)
            predictions["+".join(blocks)] = predict_fill(train[columns], train[OUTCOME], test[columns])
        y = test[OUTCOME].to_numpy()
        intervals = tour_bootstrap_mae(y, predictions, test["tour"].to_numpy())
        for (step, p), interval in zip(predictions.items(), intervals):
            results.append({"ladder": ladder, "test_split": test_split, "step": step,
                            "added_block": step.split("+")[-1], "test_shows": len(test),
                            "test_tours": test["tour"].nunique(),
                            "mae_pts": 100 * np.mean(np.abs(y - p)),
                            **{k: 100 * v for k, v in interval.items()}})
    out = pd.DataFrame(results)
    out["mae_change_pts"] = out.groupby(["ladder", "test_split"])["mae_pts"].diff()
    return out


def explanatory_model(dataset, dummies, blocks=("controls", "charts", "pageviews", "career")):
    """Fractional logit on all non-sellouts with year dummies and artist-clustered SEs.

    Continuous predictors are standardized; each coefficient is the change
    in log-odds of a seat being filled per one SD.
    """
    rows = sellout.ladder_rows(dataset, "charts_first") & (dataset["sold_out"] == 0)
    data = dataset[rows]
    columns = sellout.block_columns(list(blocks), dummies.columns)
    X = pd.concat([data, dummies[rows]], axis=1)[columns].astype(float)
    columns = [c for c in columns if X[c].nunique() > 1]
    X = X[columns]
    continuous = [c for c in columns if X[c].nunique() > 2]
    X[continuous] = (X[continuous] - X[continuous].mean()) / X[continuous].std()
    year = pd.to_datetime(data["first_date"]).dt.year.clip(sellout.FIRST_YEAR, sellout.LAST_YEAR)
    X = pd.concat([X, pd.get_dummies(year, prefix="year", drop_first=True, dtype=float)], axis=1)

    fit = fit_fractional_logit(X, data[OUTCOME], groups=pd.factorize(data["artist"])[0])
    block_of = {c: b for b in blocks for c in sellout.block_columns([b], dummies.columns)}
    return pd.DataFrame({"predictor": columns, "block": [block_of[c] for c in columns],
                         "coef": fit.params[columns].to_numpy(), "se": fit.bse[columns].to_numpy(),
                         "p_value": fit.pvalues[columns].to_numpy(),
                         "n_shows": int(fit.nobs), "n_artists": data["artist"].nunique()})


def run(dataset_path=DATASET_PATH):
    """Run both ladders and the explanatory model; save the tables."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    dummies = sellout.control_dummies(dataset)
    ladders = pd.concat([run_ladder(dataset, dummies, name) for name in LADDERS], ignore_index=True)
    coefficients = explanatory_model(dataset, dummies)

    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    ladders.to_csv(sellout.TABLES_DIR / "fill_rate_ladders.csv", index=False)
    coefficients.to_csv(sellout.TABLES_DIR / "fill_rate_coefficients.csv", index=False)
    logger.info("Fill rate ladders (MAE, percentage points):\n%s", ladders[
        ["ladder", "test_split", "added_block", "test_tours", "mae_pts", "mae_change_pts",
         "change_low", "change_high"]].round(2).to_string(index=False))
    logger.info("Explanatory (%d shows, %d artists):\n%s", coefficients["n_shows"].iloc[0],
                coefficients["n_artists"].iloc[0],
                coefficients[["block", "predictor", "coef", "p_value"]].round(3).to_string(index=False))
    return ladders, coefficients


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
