"""Tests for the Spotify charts ingest (no network calls)."""

import zipfile

import pandas as pd
import pytest

from concert_demand.clean.artist_names import CreditMatcher
from concert_demand.ingest.spotify_charts import check_charts, load_regions, spotify_credit


@pytest.mark.parametrize("artist, title, expected", [
    ("Shakira", "Chantaje (feat. Maluma)", "Shakira Featuring Maluma"),
    ("Post Malone", "Sunflower (with Swae Lee)", "Post Malone Featuring Swae Lee"),
    ("Drake", "Toosie Slide", "Drake"),
    ("J Balvin, Pharrell Williams, BIA, Sky", "Safari", "J Balvin, Pharrell Williams, BIA, Sky"),
    ("Travis Scott", "Can't Say [feat. Don Toliver]", "Travis Scott Featuring Don Toliver"),
    ("Calvin Harris", "Slide (feat. Frank Ocean & Migos)", "Calvin Harris Featuring Frank Ocean & Migos"),
    ("Kanye West", "Ultralight Beam (ft. Chance the Rapper)", "Kanye West Featuring Chance the Rapper"),
    ("Mac Miller", "Ladders - Live (w/ Thundercat)", "Mac Miller Featuring Thundercat"),
    # "with" outside parentheses is part of the song title, not a credit
    ("Lewis Capaldi", "Before You Go - with Strings", "Lewis Capaldi"),
])
def test_spotify_credit(artist, title, expected):
    assert spotify_credit(artist, title) == expected


def test_spotify_credit_flows_through_billboard_matcher():
    # Same matcher as Billboard: roles, protected comma names, aliases all apply
    matcher = CreditMatcher(["Travis Scott", "Don Toliver", "Tyler, the Creator", "Kali Uchis"])
    assert matcher.match(spotify_credit("Travis Scott", "Can't Say (feat. Don Toliver)")) == [
        ("Travis Scott", "lead"), ("Don Toliver", "featured")]
    assert matcher.match(spotify_credit("Tyler, The Creator", "See You Again (feat. Kali Uchis)")) == [
        ("Tyler, the Creator", "lead"), ("Kali Uchis", "featured")]


CSV_TEXT = """title,rank,date,artist,url,region,chart,trend,streams
Song A,1,2017-01-01,Drake,u1,United States,top200,SAME_POSITION,1000
Song B,2,2017-01-01,Future,u2,United States,top200,MOVE_UP,900
Song C,1,2017-01-01,Shakira,u3,Argentina,top200,MOVE_UP,800
Song D,1,2017-01-01,Drake,u4,Canada,viral50,NEW_ENTRY,
Song E,1,2017-01-03,Drake,u5,United States,top200,SAME_POSITION,1100
Song F,2,2017-01-03,Future,u6,United States,top200,MOVE_UP,950
"""


@pytest.fixture
def charts_zip(tmp_path):
    path = tmp_path / "spotify-charts.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("charts.csv", CSV_TEXT)
    return path


def test_load_regions_keeps_only_requested_regions(charts_zip):
    charts = load_regions(charts_zip, regions=["United States", "Canada"], chunksize=2)
    assert set(charts["region"]) == {"United States", "Canada"}
    assert len(charts) == 5
    assert charts["date"].dtype == "datetime64[ns]"
    assert "url" not in charts.columns  # dropped to keep the file small


def test_load_regions_keeps_viral_streams_missing(charts_zip):
    charts = load_regions(charts_zip, regions=["Canada"])
    assert charts["streams"].isna().all()  # Viral 50 has no stream counts


def test_check_charts_finds_missing_days_and_short_charts(charts_zip):
    charts = load_regions(charts_zip, regions=["United States"])
    report = check_charts(charts, chart_sizes={"top200": 2})
    key = ("United States", "top200")
    assert report[key]["missing_days"] == [pd.Timestamp("2017-01-02")]
    assert report[key]["short_days"] == 0
