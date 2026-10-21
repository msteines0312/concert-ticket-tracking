"""Tests for the Wikipedia tour page ingest (no network calls)."""

import pandas as pd
import pytest
import requests

from concert_demand.ingest import wikipedia_tours
from concert_demand.ingest.wikipedia_tours import extract_artists, get_json, parse_tour_page


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns queued responses in order and records each call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """Replace time.sleep so tests run instantly, and record the waits."""
    sleeps = []
    monkeypatch.setattr(wikipedia_tours.time, "sleep", sleeps.append)
    return sleeps


def test_get_json_retries_after_rate_limit(recorded_sleeps):
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, payload={"ok": True}),
    ])
    assert get_json(session, {}) == {"ok": True}
    assert session.calls == 2
    assert recorded_sleeps[0] == 7  # honored the server's Retry-After


def test_get_json_gives_up_after_max_retries(recorded_sleeps):
    session = FakeSession([FakeResponse(503)] * wikipedia_tours.MAX_RETRIES)
    with pytest.raises(requests.HTTPError):
        get_json(session, {})
    assert recorded_sleeps == [2, 4, 8, 16, 32]  # exponential backoff


def test_get_json_does_not_retry_client_errors(recorded_sleeps):
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(requests.HTTPError):
        get_json(session, {})
    assert session.calls == 1


@pytest.mark.parametrize("wikitext, expected", [
    ("{{Infobox concert tour\n| artist = [[Olivia Rodrigo]]\n| album = Guts\n}}",
     ["Olivia Rodrigo"]),
    # Piped link: the link target is the page title, the label is display text
    ("| artist     = [[Ghost (Swedish band)|Ghost]]\n", ["Ghost (Swedish band)"]),
    # Co-headliners
    ("| artist = [[Jay-Z]] and [[Beyoncé]]\n", ["Jay-Z", "Beyoncé"]),
    ("| artist = {{hlist|[[Def Leppard]]|[[Mötley Crüe]]}}\n", ["Def Leppard", "Mötley Crüe"]),
    # Unlinked plain text
    ("| artist = Billy Joel\n", ["Billy Joel"]),
    ("{{Infobox concert tour\n| album = None\n}}", []),
])
def test_extract_artists(wikitext, expected):
    assert extract_artists(wikitext) == expected


# A trimmed version of a real tour page: an infobox that mentions
# attendance, plus a tour table where a 2-night run uses merged cells.
PAGE_HTML = """
<table class="infobox"><tr><th>Attendance</th><td>1.6 million</td></tr></table>
<table class="wikitable">
<tr><th>Date (2024)</th><th>City</th><th>Country</th><th>Venue</th>
    <th>Attendance</th><th>Revenue</th></tr>
<tr><td>October 18</td><td rowspan="2">Sydney</td><td rowspan="2">Australia</td>
    <td rowspan="2">Qudos Bank Arena</td><td rowspan="2">24,000 / 24,000</td>
    <td rowspan="2">$2,500,000</td></tr>
<tr><td>October 19</td></tr>
<tr><td>October 25</td><td>Brisbane</td><td>Australia</td><td>Brisbane Ent. Centre</td>
    <td>9,800 / 11,000</td><td>$900,000</td></tr>
<tr><td>Total</td><td>Total</td><td>Total</td><td>Total</td>
    <td>33,800 / 35,000</td><td>$3,400,000</td></tr>
</table>
"""


def test_parse_tour_page_end_to_end():
    page = {"title": "Guts World Tour", "html": PAGE_HTML,
            "wikitext": "| artist = [[Olivia Rodrigo]]\n"}
    eng = parse_tour_page(page)

    assert len(eng) == 2
    assert set(eng["artist"]) == {"Olivia Rodrigo"}
    sydney = eng[eng["city"] == "Sydney"].iloc[0]
    assert sydney["n_shows"] == 2
    assert sydney["last_date"] == pd.Timestamp("2024-10-19")


def test_parse_tour_page_without_attendance_table_returns_empty():
    page = {"title": "Some Tour", "html": "<table><tr><th>Date</th></tr><tr><td>x</td></tr></table>",
            "wikitext": "| artist = [[Someone]]\n"}
    assert parse_tour_page(page).empty
