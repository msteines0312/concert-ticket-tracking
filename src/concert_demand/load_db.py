"""Load the cleaned CSVs into one SQLite database.

The database is the hand-off point between the Python pipeline and
everything downstream: the SQL analysis layer, the feature build and the
Power BI dashboard. It is rebuilt from scratch on every run (schema.sql
drops and recreates each table), so it never drifts from the CSVs.

Foreign keys are enforced during the load, so a credit or pageview row for
an artist missing from the tour data fails loudly instead of loading as an
orphan.

Usage
-----
    python -m concert_demand.load_db
"""

import logging
import sqlite3

import pandas as pd

from concert_demand.clean.artist_names import known_tour_artists
from concert_demand.ingest.wikipedia_tours import SOURCES_PATH
from concert_demand.paths import INTERIM_DIR, PROCESSED_DIR, PROJECT_ROOT

SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
DB_PATH = PROCESSED_DIR / "concert_demand.db"

BOOLEAN_COLUMNS = ["over_capacity", "sold_out", "is_festival", "suspect_capacity",
                   "is_package_tour", "in_us_canada", "is_puerto_rico", "conflicting_sources"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shape each CSV to its table
# ---------------------------------------------------------------------------

def build_artists(engagements):
    """One row per headliner or co-headliner, with role flags.

    Parameters
    ----------
    engagements : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        Columns: artist, headlines_tour, is_package_tour.
    """
    package = set(engagements.loc[engagements["is_package_tour"], "artist"].dropna())
    headliners = set(engagements["artist"].dropna())
    names = sorted(set(known_tour_artists(engagements)) | package)
    return pd.DataFrame({
        "artist": names,
        "headlines_tour": [int(name in headliners) for name in names],
        "is_package_tour": [int(name in package) for name in names],
    })


def prepare_engagements(engagements):
    """Add a surrogate key and convert booleans to 0/1.

    A surrogate key is needed because no natural key is unique: 57 rows
    without a show date share artist, tour and venue with another row.
    """
    table = engagements.copy()
    table.insert(0, "engagement_id", range(1, len(table) + 1))
    table[BOOLEAN_COLUMNS] = table[BOOLEAN_COLUMNS].astype(int)
    return table


def prepare_spotify(credits):
    """Rename Spotify columns to match the chart_credits naming."""
    return credits.rename(columns={"artist": "performer", "tour_artist": "artist"})[
        ["chart", "region", "date", "rank", "title", "performer", "streams", "artist", "role"]
    ]


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def create_schema(connection, schema_path=SCHEMA_PATH):
    """Drop and recreate every table and view from schema.sql."""
    connection.executescript(schema_path.read_text(encoding="utf-8"))


def insert(connection, table, frame):
    """Append a DataFrame to an existing table (the schema defines the types)."""
    frame.to_sql(table, connection, if_exists="append", index=False, chunksize=50_000)
    logger.info("%-16s %9d rows", table, len(frame))


def check_counts(connection, expected):
    """Confirm every table holds exactly the rows that were inserted.

    Parameters
    ----------
    connection : sqlite3.Connection
    expected : dict
        Table name -> expected row count.
    """
    for table, count in expected.items():
        loaded = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if loaded != count:
            raise ValueError(f"{table}: loaded {loaded} rows, expected {count}")


def run(db_path=DB_PATH, interim_dir=INTERIM_DIR, sources_path=SOURCES_PATH):
    """Rebuild the database from the interim CSVs and the published source list.

    Returns
    -------
    pathlib.Path
        Path to the database file.
    """
    engagements = pd.read_csv(interim_dir / "wikipedia_engagements.csv")
    sources = pd.read_csv(sources_path).rename(columns={"title": "tour"})
    genres = pd.read_csv(interim_dir / "artist_genres.csv", usecols=["artist", "genre_group"])
    tables = {
        "artists": build_artists(engagements).merge(genres, on="artist", how="left"),
        "tour_sources": sources,
        "engagements": prepare_engagements(engagements),
        "chart_credits": pd.read_csv(interim_dir / "chart_credits.csv"),
        "pageviews_daily": pd.read_csv(interim_dir / "pageviews_daily.csv"),
        "spotify_credits": prepare_spotify(pd.read_csv(interim_dir / "spotify_credits.csv")),
    }

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        create_schema(connection)
        # Insert order follows the foreign keys: parents before children
        for table, frame in tables.items():
            insert(connection, table, frame)
        check_counts(connection, {table: len(frame) for table, frame in tables.items()})
    logger.info("Database written to %s", db_path)
    return db_path


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
