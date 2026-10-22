"""Right-sizing score: did the room move fit how the artist's last tour sold?

Matt's design (2026-10-21): the score is built from the one finding that
survived the robustness checks. Doubling the room raises the odds of a
sellout after a tour that was 100% full and lowers them after one that
wasn't; the break-even is about 95% full, and it held when any single tour
was left out and under the 97% sellout definition.

Per show with a previous tour:
- upsize_odds_multiplier: how growing the room changed the odds of a
  sellout compared with booking the same size room as last time, from the
  upsizing terms of the history-sample explanatory model. Below 1 means
  the move hurt. A smaller room gets 1.0: growing and shrinking are
  modeled separately (noise review), and shrinking showed no effect.
- upsized_past_rule: the room grew and the previous tour was less full
  than the break-even, i.e. the buyer upsized against the 95% rule.

The model behind the score is fit on these same shows, so the score
describes past bookings. It is not a tested forecast: the room terms did
not improve predictions on held-out tours.

Usage
-----
    python -m concert_demand.models.right_sizing
"""

import logging
import sqlite3

import numpy as np
import pandas as pd

from concert_demand.load_db import DB_PATH
from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH
from concert_demand.models.robustness import room_effect

logger = logging.getLogger(__name__)


def score_shows(dataset, effect):
    """Apply the fitted room effect to every show with a previous tour.

    Parameters
    ----------
    dataset : pandas.DataFrame
        Model columns (room_up, log2_room_ratio, prev_tour_fill_rate).
    effect : dict
        Output of robustness.room_effect.

    Returns
    -------
    pandas.DataFrame
        One row per scored show.
    """
    scored = dataset[dataset["log2_room_ratio"].notna() & dataset["prev_tour_fill_rate"].notna()]
    unfilled = 1 - scored["prev_tour_fill_rate"]
    log_odds = scored["room_up"] * (effect["room_main"] + effect["room_interaction"] * unfilled)
    return pd.DataFrame({
        "engagement_id": scored["engagement_id"], "artist": scored["artist"],
        "tour": scored["tour"], "first_date": scored["first_date"], "split": scored["split"],
        "room_ratio": 2 ** scored["log2_room_ratio"],
        "prev_tour": scored["prev_tour"], "prev_tour_fill_rate": scored["prev_tour_fill_rate"],
        "upsize_odds_multiplier": np.exp(log_odds),
        "upsized_past_rule": ((scored["log2_room_ratio"] > 0)
                              & (scored["prev_tour_fill_rate"] < effect["break_even_fill"])).astype(int),
        "sold_out": scored["sold_out"], "fill_rate": scored["fill_rate"],
    })


def summarize_tours(scores):
    """One row per tour: typical room move, how the last tour sold, and the outcome."""
    return (scores.groupby(["artist", "tour"])
            .agg(shows=("engagement_id", "size"), prev_tour=("prev_tour", "first"),
                 median_room_ratio=("room_ratio", "median"),
                 prev_tour_fill_rate=("prev_tour_fill_rate", "first"),
                 median_odds_multiplier=("upsize_odds_multiplier", "median"),
                 share_upsized_past_rule=("upsized_past_rule", "mean"),
                 sellout_rate=("sold_out", "mean"), mean_fill_rate=("fill_rate", "mean"))
            .reset_index()
            .sort_values("median_odds_multiplier"))


def save_room_effect(effect, tables_dir=sellout.TABLES_DIR):
    """Save the room terms and break-even so the dashboard reads them instead of a typed number.

    Returns
    -------
    pathlib.Path
        The CSV written (one row).
    """
    columns = ["room_main", "room_interaction", "interaction_p", "break_even_fill"]
    path = tables_dir / "room_effect.csv"
    pd.DataFrame([effect])[columns].to_csv(path, index=False)
    return path


def run(dataset_path=DATASET_PATH, db_path=DB_PATH):
    """Score every show, summarize by tour, and save both (CSV + database for the dashboard)."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    dummies = sellout.control_dummies(dataset, explain=True)
    ladder, blocks = sellout.EXPLANATORY["history"]
    effect = room_effect(sellout.explanatory_model(dataset, dummies, ladder, blocks))

    scores = score_shows(dataset, effect)
    tours = summarize_tours(scores)
    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    scores.to_csv(sellout.TABLES_DIR / "right_sizing_shows.csv", index=False)
    tours.to_csv(sellout.TABLES_DIR / "right_sizing_tours.csv", index=False)
    save_room_effect(effect)
    with sqlite3.connect(db_path) as connection:
        scores.to_sql("right_sizing_shows", connection, if_exists="replace", index=False)
        tours.to_sql("right_sizing_tours", connection, if_exists="replace", index=False)

    flagged = scores.groupby("upsized_past_rule").agg(
        shows=("engagement_id", "size"), tours=("tour", "nunique"),
        sellout_rate=("sold_out", "mean"), mean_fill=("fill_rate", "mean"))
    logger.info("Break-even fill %.3f. Shows by flag:\n%s", effect["break_even_fill"],
                flagged.round(3).to_string())
    logger.info("Riskiest tours:\n%s", tours.head(8).round(3).to_string(index=False))
    return scores, tours


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
