"""Write the dashboard CSVs that Power BI loads.

Reads the database and the model stage's tables, and writes six small CSVs
to data/dashboard/. They are committed (Matt, 2026-10-22) so the Power BI
template opens without running the pipeline. Everything in them is either
Wikipedia-derived (CC BY-SA) or an aggregate of Billboard chart points.

Usage
-----
    python -m concert_demand.dashboard
"""

import logging
import sqlite3

import pandas as pd

from concert_demand.dashboard.buckets import FLAG_THRESHOLD
from concert_demand.dashboard.tables import (
    build_artists,
    build_chart_quarters,
    build_shows,
    build_tours,
)
from concert_demand.ingest.cpi import load_annual
from concert_demand.load_db import DB_PATH
from concert_demand.models.dataset import usable_history
from concert_demand.models.sellout import TABLES_DIR
from concert_demand.paths import DASHBOARD_DIR

logger = logging.getLogger(__name__)

MODEL_OUTPUTS = ["room_effect.csv", "sellout_ladders.csv"]


def read_model_outputs(tables_dir):
    """Load the model stage's tables, failing with a clear message if it hasn't run.

    Parameters
    ----------
    tables_dir : pathlib.Path
        reports/tables, written by `python -m concert_demand.models`.

    Returns
    -------
    dict of str to pandas.DataFrame
        Keyed by file name.
    """
    missing = [name for name in MODEL_OUTPUTS if not (tables_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing {', '.join(missing)} in {tables_dir}. "
                                "Run `python -m concert_demand.models` first.")
    return {name: pd.read_csv(tables_dir / name) for name in MODEL_OUTPUTS}


def chart_test_table(ladders):
    """Test AUC with controls only vs. controls + charts, per test set (page 1 chart panel).

    Parameters
    ----------
    ladders : pandas.DataFrame
        sellout_ladders.csv from the model stage.

    Returns
    -------
    pandas.DataFrame
        test_split, step, auc, auc_low, auc_high, test_tours.
    """
    rows = ladders[(ladders["ladder"] == "charts_first")
                   & ladders["step"].isin(["controls", "controls+charts"])]
    return rows[["test_split", "step", "auc", "auc_low", "auc_high", "test_tours"]].reset_index(drop=True)


def headline_table(room_effect, tours, shows):
    """One row of numbers quoted on page 1, so none of them are typed by hand.

    The comparison group is shows that had a previous tour but whose tour is
    not flagged, the same comparison the right-sizing score reports.

    Parameters
    ----------
    room_effect : pandas.DataFrame
        room_effect.csv (one row, with break_even_fill).
    tours, shows : pandas.DataFrame
        Outputs of build_tours and build_shows.

    Returns
    -------
    pandas.DataFrame
        One row: break_even_fill, flag_threshold, flagged_tours, flagged_shows,
        flagged_sellout_rate, other_sellout_rate.
    """
    flagged_keys = tours.loc[tours["is_flagged"], "tour_key"]
    scored = shows[shows["upsized_past_rule"].notna()]
    flagged = scored["tour_key"].isin(flagged_keys)
    return pd.DataFrame([{
        "break_even_fill": room_effect["break_even_fill"].iloc[0],
        "flag_threshold": FLAG_THRESHOLD,
        "flagged_tours": len(flagged_keys),
        "flagged_shows": int(flagged.sum()),
        "flagged_sellout_rate": scored.loc[flagged, "sold_out"].mean(),
        "other_sellout_rate": scored.loc[~flagged, "sold_out"].mean(),
    }])


def read_database(db_path):
    """Read the pipeline tables the dashboard is built from.

    Parameters
    ----------
    db_path : pathlib.Path
        The SQLite database.

    Returns
    -------
    dict of str to pandas.DataFrame
        history is every usable engagement worldwide, filtered by the same rules
        the model uses to describe an artist's previous tour.
    """
    queries = {
        "model_dataset": "SELECT * FROM model_dataset",
        "right_sizing_shows": "SELECT * FROM right_sizing_shows",
        "right_sizing_tours": "SELECT * FROM right_sizing_tours",
        "artists": "SELECT artist, genre_group FROM artists",
        "chart_credits": "SELECT chart, chart_week, rank, artist, role FROM chart_credits",
    }
    with sqlite3.connect(db_path) as connection:
        tables = {name: pd.read_sql(query, connection) for name, query in queries.items()}
        engagements = pd.read_sql("SELECT * FROM engagements", connection,
                                  parse_dates=["first_date", "last_date"])
    history = usable_history(engagements, load_annual())
    history["first_date"] = history["first_date"].dt.date
    tables["history"] = history
    return tables


def run(db_path=DB_PATH, tables_dir=TABLES_DIR, out_dir=DASHBOARD_DIR):
    """Build every dashboard table and write it to out_dir as CSV.

    Returns
    -------
    dict of str to pandas.DataFrame
        The tables written, keyed by file stem.
    """
    model_outputs = read_model_outputs(tables_dir)
    db = read_database(db_path)

    shows = build_shows(db["model_dataset"], db["right_sizing_shows"])
    tours = build_tours(db["history"], db["right_sizing_tours"], db["model_dataset"])
    artists = build_artists(tours, db["artists"])
    tables = {
        "artists": artists,
        "tours": tours,
        "shows": shows,
        "chart_quarters": build_chart_quarters(db["chart_credits"], artists),
        "chart_test": chart_test_table(model_outputs["sellout_ladders.csv"]),
        "headline": headline_table(model_outputs["room_effect.csv"], tours, shows),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(out_dir / f"{name}.csv", index=False)
        logger.info("%s: %d rows", name, len(table))
    logger.info("Headline:\n%s", tables["headline"].round(3).to_string(index=False))
    return tables


def main():
    """Command-line entry point: export with the default paths."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
