"""Download daily Wikipedia pageviews for every tour artist.

Pageviews are the main non-chart popularity signal: they cover every
artist, charting or not, daily from July 2015 (when the API's data starts).

Name changes matter here. The API counts views under the title a reader
actually requested, so before Lady Antebellum became Lady A in 2020, the
band's views were recorded under the old title. Each artist's total is
therefore the current title plus every redirect pointing to it: all
traffic that landed on the artist's article. Unlike chart matching, this
is safe for nearly every redirect, because a redirect always leads to the
artist's own page. The exception is a redirect from a page about a work or
a list ("Drake discography", "List of U2 concert tours"). Those were
separate articles for years before being merged into the artist page, so
adding their history would put an artificial jump in the series on the
day of the merge. They're excluded. The current-title-only count is kept
as a separate column for robustness checks.

Pageview data is released under CC0 by the Wikimedia Foundation. Only
human readers are counted (agent=user), which excludes bots and crawlers.

Usage
-----
    python -m concert_demand.ingest.pageviews
"""

import argparse
import hashlib
import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote

import pandas as pd
import requests

from concert_demand.ingest import wikipedia_tours
from concert_demand.paths import INTERIM_DIR, RAW_DIR

API_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           "en.wikipedia.org/all-access/user/{title}/daily/{start}/{end}")
FIRST_DAY = date(2015, 7, 1)  # earliest date the pageviews API has data for

CACHE_DIR = RAW_DIR / "pageviews"
ENGAGEMENTS_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
REDIRECTS_PATH = INTERIM_DIR / "artist_redirects.csv"
OUTPUT_PATH = INTERIM_DIR / "pageviews_daily.csv"

# Redirects from pages about works or lists, not alternate names for the artist
WORK_TITLE_PATTERN = re.compile(
    r"discography|videography|filmography|^List of |^Legacy of "
    r"|\((?:[^)]*\s)?(?:album|EP|song|single|mixtape|tour|film|documentary|TV series|book)\)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def is_work_title(title):
    """True if a redirect title names a work or list rather than the artist.

    Parameters
    ----------
    title : str

    Returns
    -------
    bool
    """
    return bool(WORK_TITLE_PATTERN.search(title))


def _cache_path(title, cache_dir):
    """Cache file for one title.

    Windows file names ignore case, so "The Weeknd" and "the Weeknd" would
    share a file. A short hash of the exact title keeps them apart.
    """
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return cache_dir / f"{quote(title, safe='')[:120]}_{digest}.json"


def parse_views(payload):
    """Turn an API response into a daily view-count series.

    Parameters
    ----------
    payload : dict
        JSON from the per-article endpoint.

    Returns
    -------
    pandas.Series
        Views indexed by date. Empty if the response has no items.
    """
    items = payload.get("items", [])
    if not items:
        return pd.Series(dtype="int64")
    dates = pd.to_datetime([item["timestamp"][:8] for item in items], format="%Y%m%d")
    return pd.Series([item["views"] for item in items], index=dates, dtype="int64")


def fetch_daily_views(session, title, cache_dir=CACHE_DIR, end=None):
    """Daily human pageviews for one title, from cache when available.

    Parameters
    ----------
    session : requests.Session
    title : str
    cache_dir : pathlib.Path
    end : datetime.date, optional
        Last day to request. Defaults to yesterday.

    Returns
    -------
    pandas.Series
        Views by date. Empty for titles with no recorded views.
    """
    path = _cache_path(title, cache_dir)
    if path.exists():
        return parse_views(json.loads(path.read_text(encoding="utf-8")))

    end = end or date.today() - timedelta(days=1)
    url = API_URL.format(title=quote(title.replace(" ", "_"), safe=""),
                         start=FIRST_DAY.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    try:
        payload = wikipedia_tours.get_with_retry(session, url).json()
    except requests.HTTPError as error:
        # 404 means "no views recorded", which is common for redirects
        if error.response is None or error.response.status_code != 404:
            raise
        payload = {"items": []}

    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"title": title, **payload}), encoding="utf-8")
    return parse_views(payload)


def combine_artist_views(artist, canonical_views, redirect_views, days=None):
    """Add an artist's redirect traffic to their current title's views.

    Parameters
    ----------
    artist : str
    canonical_views : pandas.Series
        Daily views of the current title.
    redirect_views : list of pandas.Series
        Daily views of each redirect (former names, alternate spellings).
    days : pandas.DatetimeIndex, optional
        Every date to include. The API omits days with no views, so passing
        the full calendar turns those gaps into explicit zeros. Defaults to
        the dates seen in any series.

    Returns
    -------
    pandas.DataFrame
        Columns: artist, date, views_total, views_canonical. Dates missing
        from a series count as zero views.
    """
    series = [canonical_views, *redirect_views]
    all_dates = days if days is not None else sorted(set().union(*(s.index for s in series)))
    aligned = [s.reindex(all_dates, fill_value=0) for s in series]
    return pd.DataFrame({
        "artist": artist,
        "date": all_dates,
        "views_total": sum(aligned).astype("int64").to_numpy(),
        "views_canonical": aligned[0].astype("int64").to_numpy(),
    })


def tour_artists(engagements):
    """Headliners and co-headliners, excluding package tours (brands, not artists)."""
    engagements = engagements[~engagements["is_package_tour"]]
    names = set(engagements["artist"].dropna())
    for cell in engagements["co_headliners"].dropna():
        names.update(name.strip() for name in cell.split(";") if name.strip())
    return sorted(names)


def run(output_path=OUTPUT_PATH):
    """Fetch, combine and save daily pageviews for every tour artist."""
    session = wikipedia_tours.build_session()
    artists = tour_artists(pd.read_csv(ENGAGEMENTS_PATH))
    redirects = pd.read_csv(REDIRECTS_PATH)
    work_titles = redirects["redirect"].map(is_work_title)
    logger.info("Skipping %d redirects from pages about works or lists", work_titles.sum())
    redirects = redirects[~work_titles].groupby("artist")["redirect"].apply(list).to_dict()
    # Same calendar for every artist, so a day with no views is a 0, not a gap
    days = pd.date_range(FIRST_DAY, date.today() - timedelta(days=1))
    total_titles = len(artists) + sum(len(redirects.get(a, [])) for a in artists)
    logger.info("%d artists, %d titles including redirects", len(artists), total_titles)

    frames, fetched = [], 0
    for artist in artists:
        canonical = fetch_daily_views(session, artist)
        redirect_series = [fetch_daily_views(session, r) for r in redirects.get(artist, [])]
        frames.append(combine_artist_views(artist, canonical, redirect_series, days=days))
        fetched += 1 + len(redirect_series)
        logger.info("%d / %d titles", fetched, total_titles)

    daily = pd.concat(frames, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output_path, index=False)
    share = daily["views_canonical"].sum() / daily["views_total"].sum()
    logger.info("Saved %d artist-days to %s (%.1f%% of views on current titles)",
                len(daily), output_path, share * 100)
    return daily


def main():
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
