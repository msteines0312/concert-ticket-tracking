"""Download Wikipedia concert tour pages and extract per-engagement attendance.

Pipeline for this source:
1. List every article in "Category:<year> concert tours" for the chosen years.
2. Fetch each page's rendered HTML and wikitext through the MediaWiki API,
   caching the response under data/raw/wikipedia_tours/ so re-runs are
   offline and fast.
3. Parse the tour tables (see concert_demand.clean.attendance) and attach
   the headlining artist from the infobox.

Wikipedia content is CC BY-SA. The API asks clients to send a descriptive
User-Agent with contact info, which is read from the WIKIMEDIA_CONTACT
environment variable so no personal details are hardcoded in the repo.

Usage
-----
    python -m concert_demand.ingest.wikipedia_tours --start-year 2015 --end-year 2025
"""

import argparse
import io
import json
import logging
import os
import re
import time
from urllib.parse import quote

import pandas as pd
import requests

from concert_demand.clean.attendance import (
    clean_tour_table,
    collapse_engagements,
    standardize_columns,
)
from concert_demand.paths import INTERIM_DIR, RAW_DIR

API_URL = "https://en.wikipedia.org/w/api.php"
CACHE_DIR = RAW_DIR / "wikipedia_tours"
OUTPUT_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
REQUEST_PAUSE_SECONDS = 0.5  # pause after every API call to stay under rate limits
MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# "| artist = [[Ed Sheeran]]" in the concert tour infobox
ARTIST_PARAM_PATTERN = re.compile(r"^\s*\|\s*artist\s*=\s*(.*)$", re.MULTILINE | re.IGNORECASE)
# [[Target]] or [[Target|Label]] -> Target
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)[^\]]*\]\]")
MARKUP_PATTERN = re.compile(r"<[^>]+>|\{\{[^}]*\}\}|'{2,}")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Network + cache
# ---------------------------------------------------------------------------

def build_session():
    """Create a requests session with a Wikimedia-compliant User-Agent."""
    contact = os.environ.get("WIKIMEDIA_CONTACT", "no contact provided")
    session = requests.Session()
    session.headers["User-Agent"] = f"concert-demand-research/0.1 ({contact})"
    return session


def get_json(session, params):
    """Call the MediaWiki API, retrying on rate limits and server errors.

    On a retryable status the wait comes from the server's Retry-After
    header when present, otherwise exponential backoff (2, 4, 8, ... s).

    Parameters
    ----------
    session : requests.Session
    params : dict
        Query parameters for the API.

    Returns
    -------
    dict
        Parsed JSON response.
    """
    for attempt in range(MAX_RETRIES):
        response = session.get(API_URL, params=params, timeout=30)
        if response.status_code not in RETRYABLE_STATUS:
            response.raise_for_status()
            time.sleep(REQUEST_PAUSE_SECONDS)
            return response.json()
        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
        logger.warning("HTTP %d, retrying in %d s", response.status_code, wait)
        time.sleep(wait)
    response.raise_for_status()  # out of retries: surface the last error


def fetch_category_titles(session, year):
    """List article titles in "Category:<year> concert tours".

    Parameters
    ----------
    session : requests.Session
    year : int

    Returns
    -------
    list of str
    """
    titles = []
    params = {
        "action": "query", "list": "categorymembers", "format": "json",
        "cmtitle": f"Category:{year} concert tours", "cmnamespace": 0, "cmlimit": 500,
    }
    while True:
        payload = get_json(session, params)
        titles += [member["title"] for member in payload["query"]["categorymembers"]]
        if "continue" not in payload:
            return titles
        params.update(payload["continue"])  # follow pagination


def fetch_page(session, title, cache_dir=CACHE_DIR):
    """Fetch a page's rendered HTML and wikitext, using the local cache first.

    Parameters
    ----------
    session : requests.Session
    title : str
    cache_dir : pathlib.Path

    Returns
    -------
    dict
        Keys: title, html, wikitext.
    """
    cache_path = cache_dir / f"{quote(title, safe='')}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    parsed = get_json(session, {
        "action": "parse", "page": title, "prop": "text|wikitext",
        "format": "json", "formatversion": 2, "redirects": 1,
    })["parse"]
    page = {"title": parsed["title"], "html": parsed["text"], "wikitext": parsed["wikitext"]}

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(page), encoding="utf-8")
    return page


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_artists(wikitext):
    """Read the headlining artist(s) from a concert tour infobox.

    Linked names return the link target (the artist's Wikipedia title),
    which is also the key for the pageviews API.

    Parameters
    ----------
    wikitext : str

    Returns
    -------
    list of str
        Artist titles in listed order. Empty if the infobox has no artist.
    """
    match = ARTIST_PARAM_PATTERN.search(wikitext)
    if not match:
        return []
    value = match.group(1)
    linked = [target.strip() for target in WIKILINK_PATTERN.findall(value)]
    if linked:
        return linked
    plain = MARKUP_PATTERN.sub("", value).strip()
    return [plain] if plain else []


def _is_tour_table(table):
    """True if a read_html table looks like a show listing, not an infobox."""
    columns = set(standardize_columns(table)[0].columns)
    return "attendance" in columns and bool(columns & {"venue", "city"})


def parse_tour_page(page):
    """Extract engagements from one cached tour page.

    Parameters
    ----------
    page : dict
        Output of `fetch_page`.

    Returns
    -------
    pandas.DataFrame
        One row per engagement (see `collapse_engagements`) plus artist,
        co_headliners and n_headliners. Empty if the page has no usable table.
    """
    try:
        # Pin the lxml parser. With the default flavor, a page with no match
        # silently falls back to bs4/html5lib, which raises ImportError when
        # those aren't installed and could parse differently when they are.
        tables = pd.read_html(io.StringIO(page["html"]), match="Attendance", flavor="lxml")
    except ValueError:  # read_html raises ValueError when no table matches
        return pd.DataFrame()

    shows = [clean_tour_table(t, tour=page["title"]) for t in tables if _is_tour_table(t)]
    if not shows:
        return pd.DataFrame()
    engagements = collapse_engagements(pd.concat(shows, ignore_index=True))

    # Co-headline tours keep the first-listed artist as primary. The full
    # list is stored so these rows can be excluded or checked in analysis.
    artists = extract_artists(page["wikitext"])
    engagements.insert(0, "artist", artists[0] if artists else pd.NA)
    engagements["co_headliners"] = "; ".join(artists[1:])
    engagements["n_headliners"] = len(artists)
    return engagements


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(start_year, end_year, output_path=OUTPUT_PATH):
    """Fetch, parse and save engagements for every tour in the year range.

    Returns
    -------
    pandas.DataFrame
        All engagements, also written to `output_path` as CSV.
    """
    session = build_session()
    titles = []
    for year in range(start_year, end_year + 1):
        year_titles = fetch_category_titles(session, year)
        logger.info("%d: %d tour pages", year, len(year_titles))
        titles += year_titles
    titles = list(dict.fromkeys(titles))  # tours spanning years appear twice

    frames = []
    for i, title in enumerate(titles, start=1):
        try:
            frames.append(parse_tour_page(fetch_page(session, title)))
        except (requests.RequestException, KeyError) as error:
            # One bad page shouldn't stop the run. Log it and keep going.
            logger.warning("Skipping %r: %s", title, error)
        if i % 100 == 0:
            logger.info("Parsed %d / %d pages", i, len(titles))

    engagements = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    engagements.to_csv(output_path, index=False)
    logger.info("Saved %d engagements from %d tours to %s",
                len(engagements), engagements["tour"].nunique(), output_path)
    return engagements


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(args.start_year, args.end_year)


if __name__ == "__main__":
    main()
