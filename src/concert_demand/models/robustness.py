"""Robustness checks for the Phase 2 models.

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

import numpy as np
import pandas as pd

from concert_demand.models import sellout
from concert_demand.models.dataset import OUTPUT_PATH as DATASET_PATH

ROOM_MAIN, ROOM_INTERACTION = sellout.NATURAL_UNITS

logger = logging.getLogger(__name__)


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


def run(dataset_path=DATASET_PATH):
    """Run the leave-one-tour-out check and save it."""
    dataset = sellout.add_model_columns(pd.read_csv(dataset_path))
    dummies = sellout.control_dummies(dataset)
    results = leave_one_tour_out(dataset, dummies)

    sellout.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(sellout.TABLES_DIR / "room_leave_one_tour_out.csv", index=False)

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
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Every refit drops the same constant dummy; one note is enough.
    logging.getLogger(sellout.__name__).setLevel(logging.WARNING)
    run()


if __name__ == "__main__":
    main()
