"""Tests for the Wikipedia pageviews ingest (no network calls)."""

import pandas as pd
import pytest
import requests

from concert_demand.ingest import pageviews
from concert_demand.ingest.pageviews import combine_artist_views, fetch_daily_views, parse_views


def _payload(rows):
    """Shape of a Wikimedia pageviews API response."""
    return {"items": [{"timestamp": f"{day.replace('-', '')}00", "views": views}
                      for day, views in rows]}


def test_parse_views_returns_dated_series():
    views = parse_views(_payload([("2016-01-01", 120), ("2016-01-02", 95)]))
    assert views.index.tolist() == [pd.Timestamp("2016-01-01"), pd.Timestamp("2016-01-02")]
    assert views.tolist() == [120, 95]


def test_parse_views_handles_empty_response():
    assert parse_views({"items": []}).empty


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(pageviews.wikipedia_tours.time, "sleep", lambda seconds: None)


def test_fetch_daily_views_treats_404_as_no_views(tmp_path):
    # The API returns 404 for a title with no recorded views (common for redirects)
    session = FakeSession([FakeResponse(404)])
    assert fetch_daily_views(session, "Some Redirect", cache_dir=tmp_path).empty


def test_fetch_daily_views_uses_cache_on_second_call(tmp_path):
    session = FakeSession([FakeResponse(200, _payload([("2016-01-01", 5)]))])
    first = fetch_daily_views(session, "Lady A", cache_dir=tmp_path)
    second = fetch_daily_views(session, "Lady A", cache_dir=tmp_path)
    assert len(session.urls) == 1
    assert first.equals(second)


def test_fetch_daily_views_encodes_title_and_filters_to_human_readers(tmp_path):
    session = FakeSession([FakeResponse(200, _payload([]))])
    fetch_daily_views(session, "AC/DC", cache_dir=tmp_path)
    assert "/user/AC%2FDC/daily/" in session.urls[0]  # agent=user excludes bots and crawlers


def test_combine_artist_views_adds_former_titles():
    # Before the 2020 rename, Lady A's views were recorded under the old title
    canonical = pd.Series([0, 0, 900], index=pd.to_datetime(["2020-05-01", "2020-06-01", "2020-07-01"]))
    old_title = pd.Series([1000, 950, 40], index=pd.to_datetime(["2020-05-01", "2020-06-01", "2020-07-01"]))
    combined = combine_artist_views("Lady A", canonical, [old_title])
    assert combined["views_total"].tolist() == [1000, 950, 940]
    assert combined["views_canonical"].tolist() == [0, 0, 900]
    assert set(combined["artist"]) == {"Lady A"}


def test_combine_artist_views_aligns_series_with_different_dates():
    canonical = pd.Series([10], index=pd.to_datetime(["2020-01-02"]))
    redirect = pd.Series([3], index=pd.to_datetime(["2020-01-01"]))
    combined = combine_artist_views("X", canonical, [redirect]).set_index("date")
    assert combined.loc["2020-01-01", "views_total"] == 3
    assert combined.loc["2020-01-01", "views_canonical"] == 0
    assert combined.loc["2020-01-02", "views_total"] == 10
