"""Build the modeling dataset: one row per show, with transforms, history and splits.

Every design choice here was Matt's call (Phase 2 planning, 2026-10-21):

Splits. Shows on one tour are near-copies of each other, so whole tours are
assigned to one side by the tour's first show in the sample:
- train: tours starting before 2019
- test_2019: tours starting 2019-01-01 up to the COVID shutdown
- holdout_post: tours starting after the shutdown ended (2022-25 in practice)
Tours that started before the shutdown and kept playing after it stay in
their pre-COVID split, but their post-shutdown shows are excluded, so train
and test are purely pre-COVID. Tours that started during the shutdown are
excluded too. Excluded shows stay in the file for the COVID comparison.

Signals. Chart points get a charted yes/no flag plus log(1 + points), since
40% of shows had no Hot 100 entry in the window. Pageviews are logged: a
jump from 1K to 2K views a day should count more than 30K to 31K.

History. For the harder baseline, each show gets the billed artist's most
recent other tour, worldwide, using only shows that ended before this show's
cutoff (six months before the show), so nothing is known that a buyer
couldn't have known at booking. The tour needs at least
MIN_PREV_TOUR_SHOWS finished shows, otherwise the one before it is used.
Without that floor, "most recent" picked tours that had barely started at
the cutoff (Bad Bunny's El Ultimo Tour del Mundo, 1 show in) or a small side
tour running alongside the main one (Ed Sheeran's - Tour), and pages that
list only one box score row (Future Hndrxx Tour). Both sellout rate and mean
fill rate are kept, since a 96%-full show and a 60%-full show are both "not
sold out". The previous tour's average ticket price is converted to
constant dollars, because same-show price leaks the outcome (sellouts push
it up) but the previous tour's price was set before this show went on sale.
The previous tour's typical room (median capacity per show) is kept so the
models can ask whether moving an act into a bigger room than last time hurts.

Usage
-----
    python -m concert_demand.models.dataset
"""

import logging
import sqlite3

import numpy as np
import pandas as pd

from concert_demand.clean.covid import SHUTDOWN_END, SHUTDOWN_START
from concert_demand.ingest.cpi import BASE_YEAR, load_annual, to_constant_dollars
from concert_demand.load_db import DB_PATH
from concert_demand.paths import PROCESSED_DIR

TRAIN_END = pd.Timestamp("2019-01-01")   # tours starting before this train the model
MIN_PREV_TOUR_SHOWS = 5                  # Matt: fewer finished shows is too noisy to use
CHARTS = ["hot100", "billboard200"]
PRICE_COLUMN = f"prev_tour_price_{BASE_YEAR}usd"

OUTPUT_PATH = PROCESSED_DIR / "model_dataset.csv"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal transforms
# ---------------------------------------------------------------------------

def add_signal_transforms(shows):
    """Add the encoded signals and controls the models use.

    Parameters
    ----------
    shows : pandas.DataFrame
        Needs <chart>_lead_points_52w for each chart, pageviews_mean_52w,
        pageviews_en_mean_52w and capacity_per_show.

    Returns
    -------
    pandas.DataFrame
        A copy with <chart>_charted_52w (0/1), log_<chart>_points_52w,
        log_pageviews_52w, log_pageviews_en_52w and log_capacity_per_show.
    """
    out = shows.copy()
    for chart in CHARTS:
        # No chart entries in the window means zero points, not unknown.
        points = out[f"{chart}_lead_points_52w"].fillna(0)
        out[f"{chart}_charted_52w"] = (points > 0).astype(int)
        out[f"log_{chart}_points_52w"] = np.log1p(points)
    out["log_pageviews_52w"] = np.log1p(out["pageviews_mean_52w"])
    out["log_pageviews_en_52w"] = np.log1p(out["pageviews_en_mean_52w"])
    out["log_capacity_per_show"] = np.log(out["capacity_per_show"])
    return out


# ---------------------------------------------------------------------------
# Previous-tour history
# ---------------------------------------------------------------------------

def usable_history(engagements, cpi_annual):
    """Keep engagements that can describe an artist's past tour.

    Drops rows the main analysis also distrusts (festivals, suspect
    capacity, conflicting sources), rows without dates or a sellout value,
    and shutdown-era shows, which were drive-ins and test events. Adds
    revenue in constant dollars.

    Parameters
    ----------
    engagements : pandas.DataFrame
        The engagements table, with first_date and last_date parsed.
    cpi_annual : pandas.DataFrame
        Annual CPI-U (year, cpi_u), from concert_demand.ingest.cpi.

    Returns
    -------
    pandas.DataFrame
    """
    keep = (engagements["artist"].notna()
            & engagements["first_date"].notna()
            & engagements["last_date"].notna()
            & engagements["sold_out"].notna()
            & (engagements["is_festival"] == 0)
            & (engagements["suspect_capacity"] == 0)
            & (engagements["conflicting_sources"] == 0)
            & (engagements["covid_era"] != "during"))
    history = engagements[keep].copy()
    history["revenue_real"] = to_constant_dollars(
        history["revenue_usd"], history["first_date"].dt.year, cpi_annual)
    return history


def summarize_tour(tour_shows):
    """Sellout rate, fill rate, typical room and average real price over one tour's shows.

    Price is total revenue over total tickets (so big engagements weigh
    more), using only rows that report both. The typical room is the
    median capacity per show, so a few stadium dates on an arena tour
    don't make the act look like a stadium act (Matt's pick).

    Returns
    -------
    dict
        prev_tour_shows, prev_tour_sellout_rate, prev_tour_fill_rate,
        prev_tour_room, and the price column.
    """
    priced = tour_shows[tour_shows["revenue_real"].notna() & (tour_shows["tickets_sold"] > 0)]
    price = (priced["revenue_real"].sum() / priced["tickets_sold"].sum()
             if len(priced) else np.nan)
    return {"prev_tour_shows": len(tour_shows),
            "prev_tour_sellout_rate": tour_shows["sold_out"].mean(),
            "prev_tour_fill_rate": tour_shows["fill_rate"].mean(),
            "prev_tour_room": tour_shows["capacity_per_show"].median(),
            PRICE_COLUMN: price}


def previous_tour_history(shows, history, min_shows=MIN_PREV_TOUR_SHOWS):
    """Describe each show's previous tour, as known at the show's cutoff.

    The previous tour is the billed artist's other tour whose latest show
    before the cutoff is the most recent, among tours with at least
    `min_shows` shows finished by then. Only shows that ended before the
    cutoff count, so a tour still running at booking time is summarized
    by its shows so far.

    Parameters
    ----------
    shows : pandas.DataFrame
        engagement_id, artist, tour, cutoff_date.
    history : pandas.DataFrame
        Output of `usable_history`.
    min_shows : int
        Fewest finished shows a tour needs to count as the previous tour.

    Returns
    -------
    pandas.DataFrame
        One row per show: engagement_id, prev_tour (null with no history),
        prev_tour_shows, prev_tour_sellout_rate, prev_tour_fill_rate and
        the price column.
    """
    empty = {"prev_tour": None, **summarize_tour(history.iloc[0:0])}
    empty["prev_tour_shows"] = 0
    by_artist = dict(tuple(history.groupby("artist")))

    rows = []
    for show in shows.itertuples():
        past = by_artist.get(show.artist)
        row = {"engagement_id": show.engagement_id, **empty}
        if past is not None:
            earlier = past[(past["tour"] != show.tour) & (past["last_date"] < show.cutoff_date)]
            tours = earlier.groupby("tour")["last_date"].agg(["max", "size"])
            tours = tours[tours["size"] >= min_shows]
            if not tours.empty:
                # sort_index makes ties between tours resolve the same way every run
                latest = tours["max"].sort_index().idxmax()
                row.update(prev_tour=latest, **summarize_tour(earlier[earlier["tour"] == latest]))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

def assign_split(shows):
    """Assign each show to train, test_2019, holdout_post or excluded.

    Parameters
    ----------
    shows : pandas.DataFrame
        tour, first_date (parsed) and covid_era.

    Returns
    -------
    pandas.Series
        Split label per show, aligned with `shows`.
    """
    tour_start = shows.groupby("tour")["first_date"].transform("min")
    split = pd.Series(np.select(
        [tour_start < TRAIN_END, tour_start < SHUTDOWN_START, tour_start >= SHUTDOWN_END],
        ["train", "test_2019", "holdout_post"], default="excluded"), index=shows.index)
    # Pre-COVID tours that resumed after the shutdown keep their split, but
    # those later shows leave it, so the pre-COVID splits stay pre-COVID.
    straddler = split.isin(["train", "test_2019"]) & (shows["covid_era"] != "pre")
    split[straddler] = "excluded"
    return split


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def load_inputs(connection):
    """Read the model sample (with genre, production and cutoff) and all engagements."""
    shows = pd.read_sql(
        "SELECT s.*, f.cutoff_date, a.genre_group, p.production_level, "
        "p.set_list_songs, p.set_list_suspect "
        "FROM model_sample AS s "
        "JOIN show_features AS f USING (engagement_id) "
        "LEFT JOIN artists AS a ON a.artist = s.artist "
        "LEFT JOIN tour_production AS p ON p.tour = s.tour",
        connection, parse_dates=["first_date", "last_date", "cutoff_date"])
    engagements = pd.read_sql("SELECT * FROM engagements", connection,
                              parse_dates=["first_date", "last_date"])
    return shows, engagements


def build_model_dataset(shows, engagements, cpi_annual):
    """Combine transforms, previous-tour history and split labels.

    Returns
    -------
    pandas.DataFrame
        One row per model-sample show.
    """
    dataset = add_signal_transforms(shows)
    history = previous_tour_history(dataset, usable_history(engagements, cpi_annual))
    dataset = dataset.merge(history, on="engagement_id", how="left", validate="one_to_one")
    dataset["has_prev_tour"] = dataset["prev_tour"].notna().astype(int)
    # Matt's room-change idea: this room vs. the previous tour's typical
    # room. log2, so 1 = twice the size, -1 = half.
    dataset["log2_room_ratio"] = np.log2(dataset["capacity_per_show"] / dataset["prev_tour_room"])
    dataset["split"] = assign_split(dataset)
    return dataset


def log_summary(dataset):
    """Log shows, tours, artists and sellout rate per split."""
    summary = dataset.groupby("split").agg(
        shows=("engagement_id", "size"), tours=("tour", "nunique"),
        artists=("artist", "nunique"), sellout_rate=("sold_out", "mean"),
        with_prev_tour=("has_prev_tour", "mean"))
    logger.info("Model dataset by split:\n%s", summary.round(3).to_string())


def run(db_path=DB_PATH):
    """Build the modeling dataset and save it to the database and CSV."""
    with sqlite3.connect(db_path) as connection:
        shows, engagements = load_inputs(connection)
        dataset = build_model_dataset(shows, engagements, load_annual())
        dataset.to_sql("model_dataset", connection, if_exists="replace", index=False)
    dataset.to_csv(OUTPUT_PATH, index=False)
    log_summary(dataset)
    return dataset


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
