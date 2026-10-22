"""Robustness checks for the Phase 2 models.

Signal checks (the list Matt set in Phases 1 and 2): each reruns the
controls-only and full sellout models with one thing changed, and records
how much the signals add (full AUC minus controls AUC, paired by tour):
- sellout_97: a show counts as sold out at 97% full, not only 100%
  (the Pollstar check showed Wikipedia rounds some 96-99% shows up)
- show_date_cutoff: signals measured on the show date, not six months before
- english_pageviews: English Wikipedia only, no Spanish
- window_26w: 26-week chart and pageview windows instead of 52. Matt's rule:
  keep 26w only if it beats 52w on an inner time split of the training
  years (fit on tours starting before 2018, score tours starting in 2018)
- worldwide: every country, not only the US + Canada
- artist_cv: 5-fold cross-validation grouped by artist (each artist is only
  ever in train or test), all years, no time order, repeated with 10 random
  groupings. AUC is computed inside each fold and averaged. Pooling all
  out-of-fold predictions into one AUC was the first version, and it is
  biased: artists differ so much in how often they sell out that a fold
  holding out high-sellout artists predicts low for exactly the shows that
  sold out, which drags the pooled AUC below 0.5 (room size alone scored
  0.43 pooled vs. 0.54 per fold).
The nights leakage check lives in the sellout ladders (nights_leakage).

Leave one tour out (Matt's call, 2026-10-21): the room-change finding
(upsizing hurts after a tour that wasn't nearly full) rests on about 10
tours, so the history-sample explanatory model is refit once per tour with
that tour removed. If the interaction holds no matter which tour is
dropped, no single tour is driving it.

Usage
-----
    python -m concert_demand.models.robustness
"""

import logging
import sqlite3

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from concert_demand.ingest.cpi import load_annual
from concert_demand.load_db import DB_PATH
from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH
from concert_demand.models.dataset import add_signal_transforms, build_model_dataset
from concert_demand.paths import PROCESSED_DIR

# The upsizing terms (noise review: growing and shrinking the room are
# modeled separately, and only growing has an effect).
ROOM_MAIN, ROOM_INTERACTION = "room_up", "room_up_x_prev_unfilled"
N_REPEATS = 10
FULL_BLOCKS = ["controls", "charts", "pageviews", "career"]
INNER_TRAIN_END = pd.Timestamp("2018-01-01")   # window check: fit before, score after
N_FOLDS = 5

# Raw signal columns that the swaps below replace; the model columns are
# rebuilt from them, so every transform stays the same.
RAW_SIGNALS = ["hot100_lead_points_52w", "billboard200_lead_points_52w", "pageviews_mean_52w",
               "pageviews_en_mean_52w", "hot100_lead_momentum", "pageviews_momentum",
               "hot100_lead_entries_career", "billboard200_lead_entries_career"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal checks
# ---------------------------------------------------------------------------

def scored_row(check, test_name, scored, predictions):
    """One summary row from controls and full predictions on the same shows."""
    y = scored["sold_out"].to_numpy()
    interval = sellout.tour_bootstrap_auc(y, predictions, scored["tour"].to_numpy()).iloc[1]
    controls = roc_auc_score(y, predictions["controls"])
    full = roc_auc_score(y, predictions["full"])
    return {"check": check, "test": test_name, "shows": len(scored),
            "tours": scored["tour"].nunique(), "sellout_rate": y.mean(),
            "auc_controls": controls, "auc_full": full, "signal_gain": full - controls,
            "gain_low": interval["gain_low"], "gain_high": interval["gain_high"]}


def model_columns(dummies):
    """Predictors of the controls-only and full models."""
    return {"controls": sellout.block_columns(["controls"], dummies.columns),
            "full": sellout.block_columns(FULL_BLOCKS, dummies.columns)}


def signal_gain(check, data, dummies, train, tests):
    """Fit both models on `train` and score each test mask.

    Parameters
    ----------
    check : str
    data : pandas.DataFrame
        Model columns, already limited to the sample.
    dummies : pandas.DataFrame
        Control dummies covering `data`'s index.
    train : pandas.Series of bool
    tests : dict of str -> pandas.Series of bool

    Returns
    -------
    list of dict
    """
    frame = pd.concat([data, dummies.loc[data.index]], axis=1)
    rows = []
    for name, test in tests.items():
        fit, score = frame[train], frame[test]
        predictions = {step: sellout.fit_predict(fit[cols], fit["sold_out"], score[cols])
                       for step, cols in model_columns(dummies).items()}
        rows.append(scored_row(check, name, score, predictions))
    return rows


def time_split_gain(check, dataset, dummies):
    """The main design: fit on train tours, score test_2019 and holdout_post."""
    data = dataset[sellout.ladder_rows(dataset, "charts_first")]
    tests = {split: data["split"] == split for split in sellout.TEST_SPLITS}
    return signal_gain(check, data, dummies, data["split"] == "train", tests)


def inner_time_gain(check, dataset, dummies):
    """Within the training years: fit on tours starting before 2018, score the rest."""
    data = dataset[sellout.ladder_rows(dataset, "charts_first") & (dataset["split"] == "train")]
    tour_start = pd.to_datetime(data["first_date"]).groupby(data["tour"]).transform("min")
    early = tour_start < INNER_TRAIN_END
    return signal_gain(check, data, dummies, early, {"inner_2018": ~early})


def artist_cv_gain(dataset, dummies, n_repeats=N_REPEATS):
    """Per-fold AUC from repeated cross-validation grouped by artist.

    Returns
    -------
    list of dict
        One summary row: mean fold AUC of both models, the mean gain, the
        2.5th-97.5th percentile of fold gains, and the share of folds where
        the signals helped.
    """
    data = dataset[sellout.ladder_rows(dataset, "charts_first")]
    frame = pd.concat([data, dummies.loc[data.index]], axis=1)
    columns = model_columns(dummies)
    aucs = {step: [] for step in columns}
    for repeat in range(n_repeats):
        folds = GroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=repeat)
        for fit_idx, score_idx in folds.split(frame, groups=frame["artist"]):
            fit, score = frame.iloc[fit_idx], frame.iloc[score_idx]
            if score["sold_out"].nunique() < 2:
                continue  # AUC needs both outcomes in the fold
            for step, cols in columns.items():
                p = sellout.fit_predict(fit[cols], fit["sold_out"], score[cols])
                aucs[step].append(roc_auc_score(score["sold_out"], p))
    controls, full = np.array(aucs["controls"]), np.array(aucs["full"])
    gain = full - controls
    return [{"check": "artist_cv", "test": f"{n_repeats}x{N_FOLDS}_fold_mean",
             "shows": len(frame), "tours": frame["tour"].nunique(),
             "sellout_rate": frame["sold_out"].mean(),
             "auc_controls": controls.mean(), "auc_full": full.mean(), "signal_gain": gain.mean(),
             "gain_low": np.percentile(gain, 2.5), "gain_high": np.percentile(gain, 97.5),
             "share_folds_better": float((gain > 0).mean())}]


def swap_signals(dataset, replacement):
    """Replace raw signal columns and rebuild every model column from them.

    Parameters
    ----------
    dataset : pandas.DataFrame
    replacement : pandas.DataFrame
        engagement_id plus any of RAW_SIGNALS.
    """
    swapped = dataset.drop(columns=[c for c in replacement if c != "engagement_id"])
    swapped = swapped.merge(replacement, on="engagement_id", how="left", validate="one_to_one")
    swapped.index = dataset.index   # keep alignment with the control dummies
    return sellout.add_model_columns(add_signal_transforms(swapped))


def worldwide_dataset(db_path=DB_PATH):
    """The model dataset rebuilt without the US + Canada filter.

    Countries outside the US, Canada and Puerto Rico are pooled into one
    control level, since most have too few shows to get their own.
    """
    signals = ", ".join(f"f.{c}" for c in RAW_SIGNALS)
    query = (
        f"SELECT e.*, f.cutoff_date, f.signal_artist, {signals}, a.genre_group "
        "FROM engagements AS e JOIN show_features AS f USING (engagement_id) "
        "LEFT JOIN artists AS a ON a.artist = e.artist "
        "WHERE e.artist IS NOT NULL AND e.first_date IS NOT NULL AND e.is_festival = 0 "
        "AND e.suspect_capacity = 0 AND e.conflicting_sources = 0 AND e.is_package_tour = 0 "
        "AND f.in_model_window = 1")
    with sqlite3.connect(db_path) as connection:
        shows = pd.read_sql(query, connection, parse_dates=["first_date", "last_date", "cutoff_date"])
        engagements = pd.read_sql("SELECT * FROM engagements", connection,
                                  parse_dates=["first_date", "last_date"])
    # Same tiers as the model_sample view in sql/analysis_views.sql.
    shows["venue_size"] = np.select(
        [shows["capacity_per_show"] < 5000, shows["capacity_per_show"] <= 20000],
        ["1. Under 5K (clubs, theaters)", "2. 5K-20K (arenas, amphitheaters)"],
        default="3. Over 20K (stadiums)")
    local = ["United States", "Canada", "Puerto Rico"]
    shows["country"] = shows["country"].where(shows["country"].isin(local), "Outside US/Canada")
    return sellout.add_model_columns(build_model_dataset(shows, engagements, load_annual()))


def run_signal_checks(dataset, dummies):
    """Run every signal check.

    Returns
    -------
    tuple of (pandas.DataFrame, dict)
        The summary table, and the room effect under the 97% definition.
    """
    rows = time_split_gain("main", dataset, dummies)
    rows += inner_time_gain("main", dataset, dummies)

    strict = dataset.assign(sold_out=(dataset["fill_rate"] >= 0.97).astype(int))
    rows += time_split_gain("sellout_97", strict, dummies)

    show_date = pd.read_csv(PROCESSED_DIR / "show_features_show_date.csv",
                            usecols=["engagement_id"] + RAW_SIGNALS)
    rows += time_split_gain("show_date_cutoff", swap_signals(dataset, show_date), dummies)

    english = dataset[["engagement_id", "pageviews_en_mean_52w"]].rename(
        columns={"pageviews_en_mean_52w": "pageviews_mean_52w"})
    rows += time_split_gain("english_pageviews", swap_signals(dataset, english), dummies)

    # 26-week windows go into the 52-week column names so the model code is
    # unchanged; momentum (13 vs 52 weeks) is left as is.
    windows = pd.read_csv(PROCESSED_DIR / "show_features.csv", usecols=[
        "engagement_id", "hot100_lead_points_26w", "billboard200_lead_points_26w",
        "pageviews_mean_26w"])
    windows.columns = [c.replace("_26w", "_52w") for c in windows.columns]
    short = swap_signals(dataset, windows)
    rows += inner_time_gain("window_26w", short, dummies)
    rows += time_split_gain("window_26w", short, dummies)

    world = worldwide_dataset()
    rows += time_split_gain("worldwide", world, sellout.control_dummies(world))

    rows += artist_cv_gain(dataset, dummies)

    _, blocks = sellout.EXPLANATORY["history"]
    explain_dummies = sellout.control_dummies(dataset, explain=True)
    room_97 = room_effect(sellout.explanatory_model(strict, explain_dummies, "history", blocks))
    summary = pd.DataFrame(rows)
    summary["thin_test"] = summary["tours"] < sellout.THIN_TEST_TOURS
    return summary, room_97


# ---------------------------------------------------------------------------
# Leave one tour out (room finding)
# ---------------------------------------------------------------------------

def room_effect(coefficients):
    """Pull the room terms out of an explanatory-model table.

    Returns
    -------
    dict
        main and interaction coefficients, the interaction's p-value, and
        the break-even fill rate: how full the previous tour must have been
        for doubling the room to leave the sellout odds unchanged.
    """
    table = coefficients.set_index("predictor")
    main, interaction = table.loc[ROOM_MAIN, "coef"], table.loc[ROOM_INTERACTION, "coef"]
    # Odds are unchanged when main + interaction * unfilled = 0.
    return {"room_main": main, "room_interaction": interaction,
            "interaction_p": table.loc[ROOM_INTERACTION, "p_value"],
            "break_even_fill": 1 + main / interaction}


def leave_one_tour_out(dataset, dummies, ladder="history"):
    """Refit the explanatory model once per tour, leaving that tour out.

    Returns
    -------
    pandas.DataFrame
        One row per dropped tour (plus "none" for the full fit): its shows
        in the sample and the `room_effect` values. Fits that fail are kept
        with an error message instead of silently skipped.
    """
    _, blocks = sellout.EXPLANATORY[ladder]
    in_sample = sellout.ladder_rows(dataset, ladder)
    tours = dataset.loc[in_sample, "tour"].value_counts()

    rows = [{"dropped_tour": "none", "dropped_shows": 0,
             **room_effect(sellout.explanatory_model(dataset, dummies, ladder, blocks))}]
    for tour, shows in tours.items():
        keep = dataset["tour"] != tour
        try:
            effect = room_effect(sellout.explanatory_model(dataset[keep], dummies[keep], ladder, blocks))
        except (RuntimeError, np.linalg.LinAlgError) as error:
            effect = {"error": str(error)}
        rows.append({"dropped_tour": tour, "dropped_shows": shows, **effect})
    return pd.DataFrame(rows)


def log_leave_one_out(results):
    """Summarize the leave-one-tour-out refits in the log."""
    drops = results.iloc[1:]
    failed = drops["error"].notna() if "error" in drops else pd.Series(False, index=drops.index)
    # A refit can fail when dropping a tour leaves a year where every show
    # sold out (2020 and 2021 have few history tours). Reported, not patched.
    logger.info("Leave one tour out: %d refits, %d failed: %s", len(drops), failed.sum(),
                drops.loc[failed, "dropped_tour"].tolist())
    drops = drops[~failed]
    logger.info("Interaction p-value: max %.4f, share < 0.05: %.3f",
                drops["interaction_p"].max(), (drops["interaction_p"] < 0.05).mean())
    logger.info("Break-even fill rate: %.3f to %.3f (full fit %.3f)",
                drops["break_even_fill"].min(), drops["break_even_fill"].max(),
                results["break_even_fill"].iloc[0])
    most_influential = drops.assign(
        shift=(drops["room_interaction"] - results["room_interaction"].iloc[0]).abs()
    ).nlargest(5, "shift")
    logger.info("Most influential tours:\n%s", most_influential[
        ["dropped_tour", "dropped_shows", "room_main", "room_interaction",
         "interaction_p", "break_even_fill"]].round(4).to_string(index=False))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(dataset_path=DATASET_PATH):
    """Run the signal checks and the leave-one-tour-out check; save both."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    dummies = sellout.control_dummies(dataset)
    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)

    summary, room_97 = run_signal_checks(dataset, dummies)
    summary.to_csv(sellout.TABLES_DIR / "robustness_signal_checks.csv", index=False)
    logger.info("Signal checks:\n%s", summary.round(3).to_string(index=False))
    logger.info("Room effect, 97%% sellout definition: %s",
                {key: round(value, 4) for key, value in room_97.items()})

    results = leave_one_tour_out(dataset, sellout.control_dummies(dataset, explain=True))
    results.to_csv(sellout.TABLES_DIR / "room_leave_one_tour_out.csv", index=False)
    log_leave_one_out(results)
    return summary, results


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Every refit drops the same constant dummy; one note is enough.
    logging.getLogger(sellout.__name__).setLevel(logging.WARNING)
    run()


if __name__ == "__main__":
    main()
