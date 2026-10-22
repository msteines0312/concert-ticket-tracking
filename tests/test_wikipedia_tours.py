"""Tests for the Wikipedia tour page ingest (no network calls)."""

import json

import pandas as pd
import pytest
import requests

from concert_demand.ingest import wikipedia_tours
from concert_demand.ingest.wikipedia_tours import (
    build_source_list,
    fetch_redirects,
    extract_artists,
    fetch_pages,
    fetch_wikitexts,
    get_json,
    parse_tour_page,
    resolve_titles,
)


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


def infobox(body):
    """Wrap infobox parameters the way they appear on a real tour page."""
    return "{{Infobox concert tour\n" + body + "}}"


@pytest.mark.parametrize("wikitext, expected", [
    (infobox("| artist = [[Olivia Rodrigo]]\n| album = Guts\n"), ["Olivia Rodrigo"]),
    # Piped link: the link target is the page title, the label is display text
    (infobox("| artist     = [[Ghost (Swedish band)|Ghost]]\n"), ["Ghost (Swedish band)"]),
    # Co-headliners
    (infobox("| artist = [[Jay-Z]] and [[Beyoncé]]\n"), ["Jay-Z", "Beyoncé"]),
    (infobox("| artist = {{hlist|[[Def Leppard]]|[[Mötley Crüe]]}}\n"),
     ["Def Leppard", "Mötley Crüe"]),
    # Unlinked plain text
    (infobox("| artist = Billy Joel\n"), ["Billy Joel"]),
    (infobox("| album = None\n"), []),
    ("No infobox on this page", []),
    # Whole infobox on one line (Evolve World Tour, Runaway Tour, 4:44 Tour)
    ("{{Infobox concert|concert_tour_name=|image=x.jpg|border=yes|artist=[[Imagine Dragons]]"
     "|type=World|location={{Flatlist|\n*Asia\n*Europe}}}}", ["Imagine Dragons"]),
    # Artist field far down the infobox, after nested templates
    ("{{Infobox concert|image=a.jpg|start_date={{Start date|df=yes|2016|2|29}}"
     "|artist=[[Adele]]|album=''[[25 (Adele album)|25]]''}}", ["Adele"]),
    # An "artist" parameter in some other template must be ignored
    ("{{Quote box|artist=[[Somebody Else]]}}\n{{Infobox concert tour\n| artist = [[Muse (band)|Muse]]\n}}",
     ["Muse (band)"]),
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
            "wikitext": infobox("| artist = [[Olivia Rodrigo]]\n")}
    eng = parse_tour_page(page)

    assert len(eng) == 2
    assert set(eng["artist"]) == {"Olivia Rodrigo"}
    sydney = eng[eng["city"] == "Sydney"].iloc[0]
    assert sydney["n_shows"] == 2
    assert sydney["last_date"] == pd.Timestamp("2024-10-19")


def test_parse_tour_page_without_attendance_table_returns_empty():
    page = {"title": "Some Tour", "html": "<table><tr><th>Date</th></tr><tr><td>x</td></tr></table>",
            "wikitext": infobox("| artist = [[Someone]]\n")}
    assert parse_tour_page(page).empty


# ---------------------------------------------------------------------------
# Batched wikitext + cache
# ---------------------------------------------------------------------------

def _query_payload():
    """A batched query response with one normalized title and one redirect."""
    return {"query": {
        "normalized": [{"from": "guts World Tour", "to": "Guts World Tour"}],
        "redirects": [{"from": "Divide Tour", "to": "÷ Tour"}],
        "pages": [
            {"title": "Guts World Tour",
             "revisions": [{"revid": 111, "slots": {"main": {"content": "| artist = [[Olivia Rodrigo]]"}}}]},
            {"title": "÷ Tour",
             "revisions": [{"revid": 222, "slots": {"main": {"content": "| artist = [[Ed Sheeran]]"}}}]},
            {"title": "Deleted Tour", "missing": True},
        ],
    }}


def test_fetch_wikitexts_maps_results_back_to_requested_titles(recorded_sleeps):
    session = FakeSession([FakeResponse(200, payload=_query_payload())])
    results = fetch_wikitexts(session, ["guts World Tour", "Divide Tour", "Deleted Tour"])

    assert set(results) == {"guts World Tour", "Divide Tour"}  # missing page dropped
    assert results["Divide Tour"]["title"] == "÷ Tour"  # followed the redirect
    assert results["Divide Tour"]["revid"] == 222


def test_fetch_pages_skips_network_for_cached_titles(tmp_path, recorded_sleeps):
    cached = {"title": "Guts World Tour", "revid": 111, "retrieved_at": "2026-10-21T00:00:00+00:00",
              "html": PAGE_HTML, "wikitext": "| artist = [[Olivia Rodrigo]]"}
    (tmp_path / "Guts%20World%20Tour.json").write_text(json.dumps(cached), encoding="utf-8")

    session = FakeSession([])  # any network call would fail on an empty queue
    pages = fetch_pages(session, ["Guts World Tour"], cache_dir=tmp_path)
    assert session.calls == 0
    assert pages[0]["revid"] == 111


def test_build_source_list_only_includes_articles_that_produced_data():
    pages = [
        {"title": "Guts World Tour", "revid": 111, "retrieved_at": "2026-10-21"},
        {"title": "Some Tour Without Attendance", "revid": 333, "retrieved_at": "2026-10-21"},
    ]
    sources = build_source_list(pages, used_titles={"Guts World Tour"})
    assert list(sources["title"]) == ["Guts World Tour"]
    assert sources.iloc[0]["url"] == "https://en.wikipedia.org/wiki/Guts_World_Tour"
    assert sources.iloc[0]["permalink"].endswith("oldid=111")


def test_parse_tour_page_reads_year_from_table_caption():
    html = """
    <table class="wikitable"><caption>List of 2016 concerts<sup>[13]</sup></caption>
    <tr><th>Date</th><th>City</th><th>Venue</th><th>Attendance</th></tr>
    <tr><td>13 April</td><td>Fresno</td><td>Save Mart Center</td><td>11,976 / 11,976</td></tr>
    </table>"""
    page = {"title": "One on One (tour)", "html": html, "wikitext": infobox("|artist=[[Paul McCartney]]")}
    eng = parse_tour_page(page)
    assert eng.loc[0, "first_date"] == pd.Timestamp("2016-04-13")
    assert eng.loc[0, "artist"] == "Paul McCartney"


# ---------------------------------------------------------------------------
# Canonical artist titles
# ---------------------------------------------------------------------------

def test_resolve_titles_follows_redirects_normalization_and_overrides(recorded_sleeps):
    session = FakeSession([FakeResponse(200, payload={"query": {
        "normalized": [{"from": "the Weeknd", "to": "The Weeknd"}],
        "redirects": [{"from": "Sam Smith (singer)", "to": "Sam Smith"}],
        "pages": [{"title": "The Weeknd"}, {"title": "Sam Smith"}, {"title": "Adele"}],
    }})])
    resolved = resolve_titles(session, ["the Weeknd", "Sam Smith (singer)", "Adele", "Pentagon"],
                              overrides={"Pentagon": "Pentagon (South Korean band)"})
    assert resolved == {
        "the Weeknd": "The Weeknd",
        "Sam Smith (singer)": "Sam Smith",
        "Adele": "Adele",
        "Pentagon": "Pentagon (South Korean band)",  # manual override, no API call needed
    }


def test_fetch_redirects_follows_continuation(recorded_sleeps):
    session = FakeSession([
        FakeResponse(200, payload={
            "continue": {"rdcontinue": "123", "continue": "||"},
            "query": {"pages": [{"title": "Lady A", "redirects": [{"title": "Lady Antebellum"}]}]}}),
        FakeResponse(200, payload={
            "query": {"pages": [{"title": "Lady A", "redirects": [{"title": "Lady A (band)"}]},
                                {"title": "Adele"}]}}),
    ])
    redirects = fetch_redirects(session, ["Lady A", "Adele"])
    assert redirects == {"Lady A": ["Lady Antebellum", "Lady A (band)"]}
