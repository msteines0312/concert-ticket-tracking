"""Create the SQL analysis views (sql/analysis_views.sql) in the database.

Run after the feature build and features.one_hit, since views read
show_features and one_hit_shows.

Usage
-----
    python -m concert_demand.analysis_views
"""

import logging
import sqlite3

from concert_demand.load_db import DB_PATH
from concert_demand.paths import PROJECT_ROOT

VIEWS_PATH = PROJECT_ROOT / "sql" / "analysis_views.sql"
VIEW_NAMES = [
    "model_sample",
    "artist_venue_fit", "extra_nights", "demand_per_seat",                     # right-sizing
    "tour_summary", "engagement_history", "city_revisits",                     # booking history
    "sellout_by_signal_decile", "within_artist_pageviews", "one_hit_case_study",  # signal diagnostics
]

logger = logging.getLogger(__name__)


def create_views(connection, views_path=VIEWS_PATH):
    """Drop and recreate every analysis view, then query each one once.

    SQLite only checks a view's SQL when it is queried, not when it is
    created, so a typo would otherwise surface later in a notebook. Running
    a COUNT on each view makes errors show up here.

    Returns
    -------
    dict
        View name -> row count.
    """
    connection.executescript(views_path.read_text(encoding="utf-8"))
    return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in VIEW_NAMES}


def run(db_path=DB_PATH):
    with sqlite3.connect(db_path) as connection:
        for name, rows in create_views(connection).items():
            logger.info("%-26s %6d rows", name, rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
