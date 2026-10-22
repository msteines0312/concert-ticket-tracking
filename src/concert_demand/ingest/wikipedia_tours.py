"""Download Wikipedia concert tour pages and extract per-engagement attendance.

Pipeline for this source:
1. List every article in "Category:<year> concert tours" for the chosen years.
2. Fetch each page's wikitext (in batches of 50) and rendered HTML, caching
   both under data/raw/wikipedia_tours/ so re-runs are offline and fast.
3. Parse the tour tables (see concert_demand.clean.attendance) and attach
   the headlining artist from the infobox.
4. Write a source list with each article's URL and revision ID, which is
   the per-article attribution Wikipedia's CC BY-SA license asks for.

Why two endpoints instead of one: the first version used `action=parse`,
one expensive render per page. Wikitext now comes from `action=query` 50
titles at a time (with revision IDs for attribution), and HTML from the REST
endpoint, which serves pre-rendered pages. A page-by-page comparison on 99
tours confirmed both methods produce identical engagements.

Wikipedia requires a descriptive User-Agent with contact info (see
`build_session`). It defaults to this project's GitHub URL and can be
overridden with the WIKIMEDIA_CONTACT environment variable.

Usage
-----
    python -m concert_demand.ingest.wikipedia_tours --start-year 2015 --end-year 2025
"""

import argparse
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote

import mwparserfromhell
import pandas as pd
import requests
from lxml import html as lxml_html

from concert_demand.clean.attendance import (
    YEAR_PATTERN,
    clean_tour_table,
    collapse_engagements,
    standardize_columns,
    strip_footnotes,
)
from concert_demand.clean.countries import tag_countries
from concert_demand.clean.covid import assign_covid_era
from concert_demand.clean.shared_shows import merge_shared_shows
from concert_demand.paths import INTERIM_DIR, PROJECT_ROOT, RAW_DIR

API_URL = "https://en.wikipedia.org/w/api.php"
REST_HTML_URL = "https://en.wikipedia.org/w/rest.php/v1/page/{title}/html"
ARTICLE_URL = "https://en.wikipedia.org/wiki/{title}"
CACHE_DIR = RAW_DIR / "wikipedia_tours"
OUTPUT_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
# The source list is attribution metadata, not data: it lives in docs/ so it is
# published with the repo (CC BY-SA asks for a link to every reused article)
SOURCES_PATH = PROJECT_ROOT / "docs" / "wikipedia_sources.csv"
REDIRECTS_PATH = INTERIM_DIR / "artist_redirects.csv"

PROJECT_URL = "https://github.com/msteines0312/concert-ticket-tracking"

# Artist names the API can't resolve correctly on its own, checked by hand.
# "Pentagon" is unlinked plain text in the Prism World Tour infobox and
# would otherwise resolve to the geometry article.
TITLE_OVERRIDES = {
    "Pentagon": "Pentagon (South Korean band)",
    # Redirects to "Compilation album", which reads like a data error
    "Various Artists": "Various Artists",
}

# Infobox "artists" that are a brand, label, TV show or compilation fronting
# a multi-act package tour, not one artist whose popularity drives sales.
# Flagged so the model can exclude them.
PACKAGE_TOUR_ARTISTS = {"American Idol", "Honda Civic Tour", "Top Dawg Entertainment",
                        "Various Artists"}

WIKITEXT_BATCH_SIZE = 50  # API maximum for titles per query
# Identified bots get 200 requests/minute. 0.35 s between calls is about
# 170/minute, leaving headroom for response time variation.
REQUEST_PAUSE_SECONDS = 0.35
MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def build_session():
    """Create a requests session with a Wikimedia-compliant User-Agent.

    Wikimedia rate limits clients it can't identify to 10 requests per
    minute. A User-Agent with a full contact URL (scheme included) or email
    plus the HTTP library name qualifies for 200 per minute. The first
    version of this pipeline sent a bare "github.com/..." and was throttled
    to the 10/min tier. See mediawiki.org/wiki/Wikimedia_APIs/Rate_limits.
    """
    contact = os.environ.get("WIKIMEDIA_CONTACT", PROJECT_URL)
    session = requests.Session()
    session.headers["User-Agent"] = (
        f"ConcertDemandResearch/0.1 ({contact}) python-requests/{requests.__version__}"
    )
    return session


def get_with_retry(session, url, params=None):
    """GET a URL, retrying on rate limits and server errors.

    On a retryable status the wait comes from the server's Retry-After
    header when present, otherwise exponential backoff (2, 4, 8, ... s).

    Parameters
    ----------
    session : requests.Session
    url : str
    params : dict, optional

    Returns
    -------
    requests.Response
        A successful response.
    """
    for attempt in range(MAX_RETRIES):
        response = session.get(url, params=params, timeout=30)
        if response.status_code not in RETRYABLE_STATUS:
            response.raise_for_status()
            time.sleep(REQUEST_PAUSE_SECONDS)
            return response
        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
        logger.warning("HTTP %d, retrying in %d s", response.status_code, wait)
        time.sleep(wait)
    response.raise_for_status()  # out of retries: surface the last error


def get_json(session, params, api_url=API_URL):
    """Call the MediaWiki Action API (English Wikipedia by default) and return the parsed JSON."""
    return get_with_retry(session, api_url, params).json()


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


def fetch_wikitexts(session, titles):
    """Fetch wikitext and revision IDs for up to 50 titles in one request.

    Parameters
    ----------
    session : requests.Session
    titles : list of str
        At most WIKITEXT_BATCH_SIZE titles.

    Returns
    -------
    dict
        Requested title -> {"title", "revid", "wikitext"}, where "title" is
        the resolved title after redirects. Missing pages are left out.
    """
    payload = get_json(session, {
        "action": "query", "prop": "revisions", "rvprop": "ids|content",
        "rvslots": "main", "titles": "|".join(titles), "redirects": 1,
        "format": "json", "formatversion": 2,
    })
    query = payload["query"]

    # The API may rename a title twice: normalization ("foo" -> "Foo"),
    # then a redirect. Follow both so results map back to what we asked for.
    renames = {item["from"]: item["to"] for item in query.get("normalized", [])}
    renames.update({item["from"]: item["to"] for item in query.get("redirects", [])})

    pages = {}
    for page in query["pages"]:
        if "revisions" in page:
            revision = page["revisions"][0]
            pages[page["title"]] = {
                "title": page["title"],
                "revid": revision["revid"],
                "wikitext": revision["slots"]["main"]["content"],
            }

    results = {}
    for requested in titles:
        resolved = requested
        while resolved in renames:
            resolved = renames[resolved]
        if resolved in pages:
            results[requested] = pages[resolved]
    return results


def resolve_titles(session, names, overrides=TITLE_OVERRIDES):
    """Map artist names to their canonical Wikipedia titles.

    Tour pages link the same artist in different ways ("the Weeknd" vs
    "The Weeknd", "Sam Smith (singer)" vs "Sam Smith"). Asking the API to
    resolve each name gives one title per artist, which also matches the
    title the pageviews API expects.

    Parameters
    ----------
    session : requests.Session
    names : list of str
    overrides : dict
        Hand-checked corrections applied instead of the API.

    Returns
    -------
    dict
        Name -> canonical title. Names the API doesn't recognize map to
        themselves.
    """
    resolved = {name: overrides[name] for name in names if name in overrides}
    to_query = [name for name in names if name not in overrides]

    for start in range(0, len(to_query), WIKITEXT_BATCH_SIZE):
        batch = to_query[start:start + WIKITEXT_BATCH_SIZE]
        query = get_json(session, {
            "action": "query", "titles": "|".join(batch), "redirects": 1,
            "format": "json", "formatversion": 2,
        })["query"]
        renames = {item["from"]: item["to"] for item in query.get("normalized", [])}
        renames.update({item["from"]: item["to"] for item in query.get("redirects", [])})
        for name in batch:
            title = name
            while title in renames:  # normalization, then redirect
                title = renames[title]
            resolved[name] = title
    return resolved


def fetch_redirects(session, titles, api_url=API_URL):
    """List the redirect titles that point at each artist page.

    When an artist changes their name, Wikipedia keeps the old name as a
    redirect ("Lady Antebellum" -> "Lady A"). Chart entries from before the
    change use the old name, so these redirects become candidate aliases.

    Parameters
    ----------
    session : requests.Session
    titles : list of str
        Canonical artist titles.
    api_url : str
        Action API of the wiki to query. Spanish Wikipedia's is used for
        Spanish pageviews.

    Returns
    -------
    dict
        Title -> list of redirect titles. Titles with none are omitted.
    """
    redirects = {}
    for start in range(0, len(titles), WIKITEXT_BATCH_SIZE):
        params = {
            "action": "query", "prop": "redirects", "rdlimit": "max", "rdnamespace": 0,
            "titles": "|".join(titles[start:start + WIKITEXT_BATCH_SIZE]),
            "format": "json", "formatversion": 2,
        }
        while True:
            payload = get_json(session, params, api_url)
            for page in payload["query"]["pages"]:
                for redirect in page.get("redirects", []):
                    redirects.setdefault(page["title"], []).append(redirect["title"])
            if "continue" not in payload:
                break
            params.update(payload["continue"])  # long redirect lists span pages
    return redirects


def fetch_html(session, title):
    """Fetch a page's rendered HTML from the REST endpoint."""
    url = REST_HTML_URL.format(title=quote(title.replace(" ", "_"), safe=""))
    return get_with_retry(session, url).text


def _cache_path(title, cache_dir):
    return cache_dir / f"{quote(title, safe='')}.json"


def fetch_pages(session, titles, cache_dir=CACHE_DIR):
    """Return every page's HTML, wikitext and revision, downloading only cache misses.

    Parameters
    ----------
    session : requests.Session
    titles : list of str
    cache_dir : pathlib.Path

    Returns
    -------
    list of dict
        One dict per page found: title, revid, retrieved_at, html, wikitext.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    missing = [t for t in titles if not _cache_path(t, cache_dir).exists()]
    logger.info("%d pages cached, %d to download", len(titles) - len(missing), len(missing))

    for start in range(0, len(missing), WIKITEXT_BATCH_SIZE):
        batch = missing[start:start + WIKITEXT_BATCH_SIZE]
        for requested, page in fetch_wikitexts(session, batch).items():
            try:
                html = fetch_html(session, page["title"])
            except requests.RequestException as error:
                # One bad page shouldn't stop the run. It stays uncached,
                # so the next run retries it.
                logger.warning("Skipping %r: %s", page["title"], error)
                continue
            record = {**page, "html": html,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            _cache_path(requested, cache_dir).write_text(json.dumps(record), encoding="utf-8")
        logger.info("Downloaded %d / %d", min(start + WIKITEXT_BATCH_SIZE, len(missing)),
                    len(missing))

    pages = []
    for title in titles:
        path = _cache_path(title, cache_dir)
        if path.exists():
            pages.append(json.loads(path.read_text(encoding="utf-8")))
    return pages


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_artists(wikitext):
    """Read the headlining artist(s) from a concert tour infobox.

    Uses mwparserfromhell, a real wikitext parser, because infoboxes nest
    templates inside templates and are sometimes written on a single line,
    which a regex can't split reliably. Linked names return the link target
    (the artist's Wikipedia title), which is also the key for the pageviews API.

    Parameters
    ----------
    wikitext : str

    Returns
    -------
    list of str
        Artist titles in listed order. Empty if there is no infobox or it
        has no artist.
    """
    for template in mwparserfromhell.parse(wikitext).filter_templates():
        if not str(template.name).strip().lower().startswith("infobox"):
            continue
        if not template.has("artist"):
            return []
        value = template.get("artist").value
        linked = [str(link.title).strip() for link in value.filter_wikilinks()]
        if linked:
            return linked
        plain = value.strip_code().strip()
        return [plain] if plain else []
    return []


def _is_tour_table(table):
    """True if a read_html table looks like a show listing, not an infobox."""
    columns = set(standardize_columns(table)[0].columns)
    return "attendance" in columns and bool(columns & {"venue", "city"})


def _caption_year(table_element):
    """Year named in a table's caption, if exactly one is ("List of 2016 concerts").

    A caption naming two years ("2016–2017 concerts") can't say which year
    a given row belongs to, so it returns None rather than guess.
    """
    caption = table_element.find("caption")
    if caption is None:
        return None
    years = set(YEAR_PATTERN.findall(strip_footnotes(caption.text_content())))
    return int(years.pop()) if len(years) == 1 else None


def _attendance_tables(page_html):
    """Yield (table, caption_year) for every table that mentions Attendance.

    pandas.read_html drops <caption> elements, so each table is located with
    lxml first to keep its caption, then handed to read_html on its own.
    """
    root = lxml_html.fromstring(page_html)
    for element in root.iter("table"):
        if "Attendance" not in element.text_content():
            continue
        table_html = lxml_html.tostring(element, encoding="unicode")
        # Pin the lxml parser. With the default flavor, a failed match
        # silently falls back to bs4/html5lib, which raises ImportError when
        # those aren't installed and could parse differently when they are.
        try:
            table = pd.read_html(io.StringIO(table_html), flavor="lxml")[0]
        except ValueError:  # read_html raises ValueError when it finds no table
            continue
        yield table, _caption_year(element)


def parse_tour_page(page):
    """Extract engagements from one cached tour page.

    Parameters
    ----------
    page : dict
        A page record with title, html and wikitext.

    Returns
    -------
    pandas.DataFrame
        One row per engagement (see `collapse_engagements`) plus artist,
        co_headliners and n_headliners. Empty if the page has no usable table.
    """
    shows = [
        clean_tour_table(table, tour=page["title"], fallback_year=caption_year)
        for table, caption_year in _attendance_tables(page["html"])
        if _is_tour_table(table)
    ]
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


def canonicalize_artists(session, engagements):
    """Replace artist and co-headliner names with canonical titles and flag package tours.

    Parameters
    ----------
    session : requests.Session
    engagements : pandas.DataFrame
        Output of `parse_tour_page` for all tours.

    Returns
    -------
    pandas.DataFrame
        Same rows with artist and co_headliners resolved, plus
        is_package_tour.
    """
    def split(cell):
        return [name.strip() for name in str(cell).split(";") if name.strip()]

    co_headliners = engagements["co_headliners"].fillna("")
    names = set(engagements["artist"].dropna())
    names.update(name for cell in co_headliners for name in split(cell))
    titles = resolve_titles(session, sorted(names))

    engagements = engagements.copy()
    engagements["artist"] = engagements["artist"].map(titles, na_action="ignore")
    engagements["co_headliners"] = co_headliners.map(
        lambda cell: "; ".join(titles.get(name, name) for name in split(cell)))
    engagements["is_package_tour"] = engagements["artist"].isin(PACKAGE_TOUR_ARTISTS)

    renamed = {name: title for name, title in titles.items() if name != title}
    logger.info("Resolved %d artist names, %d renamed: %s", len(titles), len(renamed), renamed)
    return engagements


def build_source_list(pages, used_titles):
    """List the articles that contributed data, for CC BY-SA attribution.

    Parameters
    ----------
    pages : list of dict
        Page records from `fetch_pages`.
    used_titles : set of str
        Titles that produced at least one engagement.

    Returns
    -------
    pandas.DataFrame
        Columns: title, url, revid, permalink, retrieved_at.
    """
    rows = [{
        "title": page["title"],
        "url": ARTICLE_URL.format(title=quote(page["title"].replace(" ", "_"))),
        "revid": page["revid"],
        # A permalink pins the exact revision the figures were read from
        "permalink": f"https://en.wikipedia.org/w/index.php?oldid={page['revid']}",
        "retrieved_at": page["retrieved_at"],
    } for page in pages if page["title"] in used_titles]
    return pd.DataFrame(rows).drop_duplicates("title").sort_values("title")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(start_year, end_year, output_path=OUTPUT_PATH, sources_path=SOURCES_PATH):
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

    pages = fetch_pages(session, titles)
    frames = [parse_tour_page(page) for page in pages]
    engagements = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    # Redirects can make two category entries resolve to the same article
    engagements = engagements.drop_duplicates()
    engagements = canonicalize_artists(session, engagements)
    # Needs every tour's rows at once: blanks are filled from cities and
    # neighboring shows, so this can't run page by page
    engagements = tag_countries(engagements)
    filled = engagements["country_source"].isin(["city_lookup", "tour_neighbors"]).sum()
    logger.info("Filled %d blank countries, %d still blank",
                filled, engagements["country"].isna().sum())
    engagements = merge_shared_shows(engagements)
    engagements["covid_era"] = assign_covid_era(engagements["first_date"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    engagements.to_csv(output_path, index=False)
    sources = build_source_list(pages, set(engagements["tour"]))
    sources.to_csv(sources_path, index=False)

    # Former names and alternate spellings, used as aliases when matching charts
    artists = sorted(set(engagements["artist"].dropna()) | {
        name.strip() for cell in engagements["co_headliners"] for name in str(cell).split(";")
        if name.strip()})
    redirects = fetch_redirects(session, artists)
    pd.DataFrame([{"artist": artist, "redirect": redirect}
                  for artist, names in redirects.items() for redirect in names]
                 ).to_csv(REDIRECTS_PATH, index=False)
    logger.info("Saved %d redirects for %d artists to %s",
                sum(map(len, redirects.values())), len(redirects), REDIRECTS_PATH)
    logger.info("Saved %d engagements from %d tours to %s",
                len(engagements), engagements["tour"].nunique(), output_path)
    logger.info("Saved %d source articles to %s", len(sources), sources_path)
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
