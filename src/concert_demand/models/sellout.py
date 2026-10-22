"""Part 1: logistic regression for P(sellout), built up block by block.

The question is whether chart and pageview signals tell a buyer anything
beyond what the booking itself already says (room size, genre, country).
So predictors enter in blocks and each step is scored on held-out tours.
Matt's design (Phase 2 planning, 2026-10-21):

Ladders. Shared variance between charts and pageviews gets credited to
whichever enters first, so both orders run. A block's gain when it enters
second is what it adds that the other one doesn't. Career chart history is
its own block, to separate charting now (buzz) from having a catalog
(legacy). The history ladder is the harder test: do signals still help
after the model knows how the artist's previous tour sold? It only covers
shows whose artist has a previous tour (40 training tours), so it is thin.

Two jobs, two tools:
- Prediction (scikit-learn): plain logistic regression fit on train tours,
  scored on test_2019 and holdout_post. AUC is the main score because the
  sellout rate drifts upward by year and the model has no year term, so
  its probabilities are off by roughly the drift; the calibration gap is
  reported rather than hidden. Intervals come from resampling whole tours.
- Explanation (statsmodels): the full model fit on every split with year
  dummies, standard errors clustered by artist. Coefficients are per one
  standard deviation, so blocks can be compared on one scale.

Usage
-----
    python -m concert_demand.models.sellout
"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH
from concert_demand.models.dataset import PRICE_COLUMN
from concert_demand.paths import PROJECT_ROOT

OUTCOME = "sold_out"
TEST_SPLITS = ["test_2019", "holdout_post"]
N_BOOTSTRAP = 1000
SEED = 42
FIRST_YEAR, LAST_YEAR = 2017, 2025   # years outside this range join the nearest one

# Categorical controls and their reference level (the largest group, so
# every dummy reads as "compared with the most common case").
CATEGORICAL_CONTROLS = {
    "venue_size": "2. 5K-20K (arenas, amphitheaters)",
    "genre_group": "Rock/Alternative",
    "country": "United States",
}

BLOCKS = {
    "controls": ["log_capacity_per_show"],  # + the categorical dummies, added in design_matrix
    "charts": ["hot100_charted_52w", "log_hot100_points_52w", "billboard200_charted_52w",
               "log_billboard200_points_52w", "hot100_lead_momentum"],
    "pageviews": ["log_pageviews_52w", "pageviews_momentum"],
    "career": ["log_hot100_career_entries", "log_billboard200_career_entries"],
    "history": ["prev_tour_sellout_rate", "prev_tour_fill_rate", "log_prev_tour_price"],
}

LADDERS = {
    "charts_first": ["controls", "charts", "pageviews", "career"],
    "pageviews_first": ["controls", "pageviews", "charts", "career"],
    "history": ["controls", "history", "charts", "pageviews", "career"],
}

TABLES_DIR = PROJECT_ROOT / "reports" / "tables"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Design matrix
# ---------------------------------------------------------------------------

def add_model_columns(dataset):
    """Add the few transforms that only the models need.

    Career entries and price are skewed like the other signals, so they
    are logged too.
    """
    out = dataset.copy()
    out["log_hot100_career_entries"] = np.log1p(out["hot100_lead_entries_career"].fillna(0))
    out["log_billboard200_career_entries"] = np.log1p(out["billboard200_lead_entries_career"].fillna(0))
    out["log_prev_tour_price"] = np.log(out[PRICE_COLUMN])
    return out


def control_dummies(dataset):
    """One-hot encode the categorical controls with fixed reference levels.

    Encoding the whole dataset at once (not each split separately) keeps
    the same columns in train and test even when a test split lacks a
    category.

    Returns
    -------
    pandas.DataFrame
        One 0/1 column per non-reference level, named "<column>=<level>".
    """
    dummies = []
    for column, reference in CATEGORICAL_CONTROLS.items():
        levels = sorted(set(dataset[column].dropna()) - {reference})
        for level in levels:
            dummies.append((dataset[column] == level).astype(int).rename(f"{column}={level}"))
    if not dummies:  # every row at the reference level: no columns, same index
        return pd.DataFrame(index=dataset.index)
    return pd.concat(dummies, axis=1)


def block_columns(blocks, dummy_columns):
    """Predictor names for a list of blocks, controls' dummies included."""
    columns = []
    for block in blocks:
        columns += BLOCKS[block]
        if block == "controls":
            columns += list(dummy_columns)
    return columns


def ladder_rows(dataset, ladder):
    """Rows usable by every step of a ladder, so all steps score the same shows.

    Comparing steps on different rows would mix a block's real gain with
    a change in which shows are being predicted.
    """
    needed = block_columns(LADDERS[ladder], [])
    return dataset[needed].notna().all(axis=1) & (dataset["split"] != "excluded")


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def fit_predict(X_train, y_train, X_test):
    """Fit an unpenalized logistic regression and return test probabilities.

    Predictors are standardized first. That doesn't change an unpenalized
    model's predictions, but it helps the solver converge.
    """
    # C=inf is no penalty (scikit-learn 1.8 deprecated penalty=None).
    model = make_pipeline(StandardScaler(),
                          LogisticRegression(C=np.inf, max_iter=5000))
    model.fit(X_train, y_train)
    return model.predict_proba(X_test)[:, 1]


def score(y_true, p_pred):
    """AUC, log loss, Brier score and the calibration gap for one set of predictions."""
    return {"auc": roc_auc_score(y_true, p_pred),
            "log_loss": log_loss(y_true, p_pred, labels=[0, 1]),
            "brier": brier_score_loss(y_true, p_pred),
            "mean_predicted": float(np.mean(p_pred)),
            "actual_rate": float(np.mean(y_true))}


def tour_bootstrap_auc(y_true, predictions, tours, n_boot=N_BOOTSTRAP, seed=SEED):
    """AUC of each step on resampled tours, plus each step's gain over the one before.

    Tours (not shows) are resampled, because shows on one tour move
    together. Every step is scored on the same resampled tours, so the
    gain between steps is a paired comparison and its interval is much
    tighter than the two AUC intervals would suggest.

    Parameters
    ----------
    y_true : numpy.ndarray
    predictions : dict of str -> numpy.ndarray
        Test probabilities per ladder step, in ladder order.
    tours : numpy.ndarray
        Tour of each test show.

    Returns
    -------
    pandas.DataFrame
        One row per step: auc_low, auc_high, gain_low, gain_high (95%),
        gain_share_positive (share of resamples where the step helped).
    """
    rng = np.random.default_rng(seed)
    unique_tours = np.unique(tours)
    rows_by_tour = {tour: np.flatnonzero(tours == tour) for tour in unique_tours}
    steps = list(predictions)
    aucs = {step: [] for step in steps}

    for _ in range(n_boot):
        sample = rng.choice(unique_tours, size=len(unique_tours), replace=True)
        rows = np.concatenate([rows_by_tour[tour] for tour in sample])
        if len(np.unique(y_true[rows])) < 2:
            continue  # AUC needs both sellouts and misses in the resample
        for step in steps:
            aucs[step].append(roc_auc_score(y_true[rows], predictions[step][rows]))

    out = []
    for i, step in enumerate(steps):
        auc = np.array(aucs[step])
        row = {"step": step, "auc_low": np.percentile(auc, 2.5), "auc_high": np.percentile(auc, 97.5)}
        if i > 0:
            gain = auc - np.array(aucs[steps[i - 1]])
            row.update(gain_low=np.percentile(gain, 2.5), gain_high=np.percentile(gain, 97.5),
                       gain_share_positive=float((gain > 0).mean()))
        out.append(row)
    return pd.DataFrame(out)


def run_ladder(dataset, dummies, ladder):
    """Fit every step of a ladder on train and score it on each test split.

    Returns
    -------
    pandas.DataFrame
        One row per (test split, step): blocks, n_predictors, the scores
        from `score`, the AUC gain over the previous step, and bootstrap
        intervals.
    """
    rows = ladder_rows(dataset, ladder)
    data = pd.concat([dataset[rows], dummies[rows]], axis=1)
    train = data[data["split"] == "train"]
    results = []
    for test_split in TEST_SPLITS:
        test = data[data["split"] == test_split]
        predictions = {}
        for depth in range(1, len(LADDERS[ladder]) + 1):
            blocks = LADDERS[ladder][:depth]
            columns = block_columns(blocks, dummies.columns)
            step = "+".join(blocks)
            predictions[step] = fit_predict(train[columns], train[OUTCOME], test[columns])
            results.append({"ladder": ladder, "test_split": test_split, "step": step,
                            "added_block": blocks[-1], "n_predictors": len(columns),
                            "train_shows": len(train), "train_tours": train["tour"].nunique(),
                            "test_shows": len(test), "test_tours": test["tour"].nunique(),
                            **score(test[OUTCOME], predictions[step])})
        intervals = tour_bootstrap_auc(test[OUTCOME].to_numpy(), predictions, test["tour"].to_numpy())
        intervals["test_split"] = test_split
        results[-len(predictions):] = [
            {**row, **interval} for row, interval in
            zip(results[-len(predictions):], intervals.drop(columns="step").to_dict("records"))]
    out = pd.DataFrame(results)
    out["auc_gain"] = out.groupby(["ladder", "test_split"])["auc"].diff()
    return out


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------

def explanatory_model(dataset, dummies, blocks=("controls", "charts", "pageviews", "career")):
    """Fit the full model on all splits with year dummies and artist-clustered SEs.

    Continuous predictors are standardized, so each coefficient is the
    change in log-odds of a sellout for a one standard deviation increase
    (0/1 flags and dummies are left as is, so theirs is yes vs. no).

    Returns
    -------
    pandas.DataFrame
        Per predictor: block, coef, se, p_value, odds_ratio, ci_low, ci_high
        (odds-ratio scale), plus the number of shows and artist clusters.
    """
    rows = dataset["split"] != "excluded"
    data = dataset[rows]
    columns = block_columns(list(blocks), dummies.columns)
    X = pd.concat([data, dummies[rows]], axis=1)[columns].astype(float)

    continuous = [c for c in columns if X[c].nunique() > 2]
    X[continuous] = (X[continuous] - X[continuous].mean()) / X[continuous].std()
    # Year dummies absorb the rising sellout rate, so the signals aren't
    # credited with whatever changed between 2017 and 2025. The edge years
    # are folded into their neighbors: 2016 (1 show) and 2026 (11 shows, one
    # artist) are all sellouts, and a year where every show sold out has an
    # infinitely large best-fit dummy, so the fit never converges.
    year = pd.to_datetime(data["first_date"]).dt.year.clip(FIRST_YEAR, LAST_YEAR)
    years = pd.get_dummies(year, prefix="year", drop_first=True, dtype=float)
    X = sm.add_constant(pd.concat([X, years], axis=1))

    groups = pd.factorize(data["artist"])[0]
    fit = sm.Logit(data[OUTCOME].astype(float), X).fit(
        disp=False, maxiter=200, cov_type="cluster", cov_kwds={"groups": groups})
    if not fit.mle_retvals["converged"]:
        raise RuntimeError("Explanatory model did not converge; check for separation")

    block_of = {c: b for b in blocks for c in block_columns([b], dummies.columns)}
    ci = fit.conf_int()
    table = pd.DataFrame({
        "predictor": columns,
        "block": [block_of[c] for c in columns],
        "coef": fit.params[columns].to_numpy(),
        "se": fit.bse[columns].to_numpy(),
        "p_value": fit.pvalues[columns].to_numpy(),
        "odds_ratio": np.exp(fit.params[columns]).to_numpy(),
        "ci_low": np.exp(ci.loc[columns, 0]).to_numpy(),
        "ci_high": np.exp(ci.loc[columns, 1]).to_numpy(),
        "standardized": [c in continuous for c in columns],
    })
    table["n_shows"] = int(fit.nobs)
    table["n_artists"] = len(np.unique(groups))
    return table


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(dataset_path=DATASET_PATH):
    """Run all ladders and the explanatory model; save both tables."""
    dataset = add_model_columns(pd.read_csv(dataset_path))
    dummies = control_dummies(dataset)
    ladders = pd.concat([run_ladder(dataset, dummies, name) for name in LADDERS], ignore_index=True)
    coefficients = explanatory_model(dataset, dummies)

    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    ladders.to_csv(TABLES_DIR / "sellout_ladders.csv", index=False)
    coefficients.to_csv(TABLES_DIR / "sellout_coefficients.csv", index=False)

    view = ["ladder", "test_split", "added_block", "test_tours", "auc", "auc_gain",
            "gain_low", "gain_high", "mean_predicted", "actual_rate"]
    logger.info("Ladders:\n%s", ladders[view].round(3).to_string(index=False))
    logger.info("Explanatory model (%d shows, %d artists):\n%s",
                coefficients["n_shows"].iloc[0], coefficients["n_artists"].iloc[0],
                coefficients[["block", "predictor", "odds_ratio", "ci_low", "ci_high", "p_value"]]
                .round(3).to_string(index=False))
    return ladders, coefficients


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
