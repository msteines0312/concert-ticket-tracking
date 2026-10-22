"""Do chart and pageview signals predict sellouts differently before and after COVID?

Matt's design (2026-10-21): one explanatory model on every pre- and
post-shutdown show, where each signal also gets a "x post-COVID" term. A
significant interaction means that signal's effect changed. Year dummies
and artist-clustered standard errors as in Part 1. Shutdown-era shows
(drive-ins, test events) are left out. Shows that the splits excluded,
like post-shutdown dates on tours that began before COVID, are included
here, since their era is what this comparison is about.

The post-COVID indicator itself is not in the model. Without shutdown-era
shows, "post" is exactly "show year 2021 or later", which the year dummies
already cover, so the two can't be told apart. The interactions are still
identified. Signals are standardized before they are multiplied, so each
interaction is the change in the effect of a one-SD increase.

Usage
-----
    python -m concert_demand.models.covid_comparison
"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm

from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH

SIGNAL_BLOCKS = ["charts", "pageviews", "career"]

logger = logging.getLogger(__name__)


def comparison_sample(dataset):
    """Pre- and post-shutdown shows with every predictor present."""
    columns = sellout.block_columns(["controls"] + SIGNAL_BLOCKS, [])
    keep = dataset["covid_era"].isin(["pre", "post"]) & dataset[columns].notna().all(axis=1)
    return dataset[keep]


def design(data, dummies):
    """Controls, standardized signals, signal x post interactions and year dummies.

    Returns
    -------
    tuple of (pandas.DataFrame, list of str, dict)
        The design matrix with a constant, the signal columns, and a map
        from each interaction column to its block.
    """
    controls = sellout.block_columns(["controls"], dummies.columns)
    signals = sellout.block_columns(SIGNAL_BLOCKS, [])
    X = pd.concat([data, dummies.loc[data.index]], axis=1)[controls + signals].astype(float)
    X = X.loc[:, X.nunique() > 1]   # drop dummies with no shows in this sample

    continuous = [c for c in X if X[c].nunique() > 2]
    X[continuous] = (X[continuous] - X[continuous].mean()) / X[continuous].std()

    post = (data["covid_era"] == "post").astype(float)
    interaction_block = {}
    for block in SIGNAL_BLOCKS:
        for column in sellout.BLOCKS[block]:
            X[f"{column}_x_post"] = X[column] * post
            interaction_block[f"{column}_x_post"] = block

    year = pd.to_datetime(data["first_date"]).dt.year.clip(sellout.FIRST_YEAR, sellout.LAST_YEAR)
    years = pd.get_dummies(year, prefix="year", drop_first=True, dtype=float)
    return sm.add_constant(pd.concat([X, years], axis=1)), signals, interaction_block


def fit_comparison(dataset, dummies):
    """Fit the interaction model and summarize each signal's pre and post effect.

    Returns
    -------
    pandas.DataFrame
        Per signal: pre-COVID odds ratio, post-COVID odds ratio, the
        interaction's p-value, and the joint p-value of its block's
        interactions.
    """
    data = comparison_sample(dataset)
    X, signals, interaction_block = design(data, dummies)
    fit = sm.Logit(data["sold_out"].astype(float), X).fit(
        disp=False, maxiter=200, cov_type="cluster",
        cov_kwds={"groups": pd.factorize(data["artist"])[0]})
    if not fit.mle_retvals["converged"]:
        raise RuntimeError("COVID comparison model did not converge; check for separation")

    block_p = {}
    for block in SIGNAL_BLOCKS:
        members = [c for c, b in interaction_block.items() if b == block]
        restriction = np.zeros((len(members), len(fit.params)))
        for row, column in enumerate(members):
            restriction[row, fit.params.index.get_loc(column)] = 1
        block_p[block] = float(fit.wald_test(restriction, scalar=True).pvalue)

    rows = []
    for signal in signals:
        interaction = f"{signal}_x_post"
        block = interaction_block[interaction]
        rows.append({"block": block, "signal": signal,
                     "odds_ratio_pre": np.exp(fit.params[signal]),
                     "odds_ratio_post": np.exp(fit.params[signal] + fit.params[interaction]),
                     "interaction_p": fit.pvalues[interaction],
                     "block_interaction_p": block_p[block]})
    out = pd.DataFrame(rows)
    out["shows_pre"] = int((data["covid_era"] == "pre").sum())
    out["shows_post"] = int((data["covid_era"] == "post").sum())
    out["n_artists"] = data["artist"].nunique()
    return out


def run(dataset_path=DATASET_PATH):
    """Fit the COVID comparison and save it."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    table = fit_comparison(dataset, sellout.control_dummies(dataset, explain=True))
    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(sellout.TABLES_DIR / "covid_comparison.csv", index=False)
    logger.info("COVID comparison (%d pre, %d post shows, %d artists):\n%s",
                table["shows_pre"].iloc[0], table["shows_post"].iloc[0], table["n_artists"].iloc[0],
                table[["block", "signal", "odds_ratio_pre", "odds_ratio_post", "interaction_p",
                       "block_interaction_p"]].round(3).to_string(index=False))
    return table


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
