"""Tests for building the SQLite database from small interim CSVs."""

import sqlite3

import pandas as pd
import pytest

from concert_demand.load_db import build_artists, run


def _engagement(**overrides):
    row = {"artist": "Artist A", "tour": "Tour A", "venue": "Arena", "city": "Chicago",
           "country": "United States", "country_raw": "United States", "first_date": "2018-05-01",
           "last_date": "2018-05-01", "n_shows": 1, "tickets_sold": 900, "capacity": 1000,
           "revenue_usd": 50000.0, "over_capacity": False, "sold_out": False, "fill_rate": 0.9,
           "capacity_per_show": 1000.0, "is_festival": False, "suspect_capacity": False,
           "co_headliners": None, "n_headliners": 1, "is_package_tour": False,
           "country_source": "page", "in_us_canada": True, "is_puerto_rico": False,
           "conflicting_sources": False, "covid_era": "pre"}
    return {**row, **overrides}


@pytest.fixture
def interim_dir(tmp_path):
    """Minimal versions of every CSV the loader reads."""
    engagements = pd.DataFrame([
        _engagement(co_headliners="Artist B", n_headliners=2),
        _engagement(first_date="2018-06-01", last_date="2018-06-01", in_us_canada=False,
                    country="Germany", country_raw="Germany"),
        _engagement(first_date="2018-07-01", last_date="2018-07-01", is_festival=True),
    ])
    engagements.to_csv(tmp_path / "wikipedia_engagements.csv", index=False)
    pd.DataFrame([{"title": "Tour A", "url": "u", "revid": 1, "permalink": "p",
                   "retrieved_at": "2026-10-21"}]).to_csv(tmp_path / "wikipedia_sources.csv", index=False)
    pd.DataFrame([{"chart": "hot100", "chart_week": "2018-01-06", "rank": 5, "title": "Song",
                   "performer": "Artist B Featuring Artist A", "last_week": None, "peak_pos": 5,
                   "wks_on_chart": 1, "artist": "Artist A", "role": "featured"}]
                 ).to_csv(tmp_path / "chart_credits.csv", index=False)
    pd.DataFrame([{"artist": "Artist B", "date": "2018-01-01", "views_total": 10,
                   "views_canonical": 8}]).to_csv(tmp_path / "pageviews_daily.csv", index=False)
    pd.DataFrame([{"title": "Song", "rank": 3, "date": "2018-01-01", "artist": "Artist A",
                   "region": "United States", "chart": "top200", "streams": 100000,
                   "tour_artist": "Artist A", "role": "lead"}]
                 ).to_csv(tmp_path / "spotify_credits.csv", index=False)
    return tmp_path


def test_build_artists_includes_co_headliners():
    artists = build_artists(pd.DataFrame([_engagement(co_headliners="Artist B")]))
    assert artists.to_dict("records") == [
        {"artist": "Artist A", "headlines_tour": 1, "is_package_tour": 0},
        {"artist": "Artist B", "headlines_tour": 0, "is_package_tour": 0},
    ]


def test_run_loads_every_table_with_integer_flags(interim_dir, tmp_path):
    db_path = run(db_path=tmp_path / "test.db", interim_dir=interim_dir)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM engagements").fetchone()[0] == 3
        assert connection.execute("SELECT typeof(sold_out) FROM engagements").fetchone()[0] == "integer"
        streams = connection.execute("SELECT performer, artist FROM spotify_credits").fetchone()
        assert streams == ("Artist A", "Artist A")


def test_model_ready_view_drops_flagged_and_non_us_rows(interim_dir, tmp_path):
    db_path = run(db_path=tmp_path / "test.db", interim_dir=interim_dir)
    with sqlite3.connect(db_path) as connection:
        dates = connection.execute("SELECT first_date FROM model_ready_engagements").fetchall()
    assert dates == [("2018-05-01",)]  # Germany and the festival row are excluded


def test_run_rejects_credits_for_unknown_artists(interim_dir, tmp_path):
    credits = pd.read_csv(interim_dir / "chart_credits.csv").assign(artist="Nobody")
    credits.to_csv(interim_dir / "chart_credits.csv", index=False)
    # pandas wraps the sqlite3 error in its own DatabaseError
    with pytest.raises(pd.errors.DatabaseError) as error:
        run(db_path=tmp_path / "test.db", interim_dir=interim_dir)
    assert isinstance(error.value.__cause__, sqlite3.IntegrityError)


def test_run_rebuilds_instead_of_appending(interim_dir, tmp_path):
    db_path = tmp_path / "test.db"
    run(db_path=db_path, interim_dir=interim_dir)
    run(db_path=db_path, interim_dir=interim_dir)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM engagements").fetchone()[0] == 3
