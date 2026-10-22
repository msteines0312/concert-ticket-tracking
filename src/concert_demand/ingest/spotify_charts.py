"""Load Spotify Top 200 and Viral 50 charts for the US and Canada.

Source: "Spotify Charts" by Dhruvil Dave on Kaggle, an archive of every
Top 200 and Viral 50 chart Spotify published from 2017 to the end of 2021
(Open Database License; song contents remain with their original authors).
Download it with the Kaggle CLI, which needs a free Kaggle API token:

    kaggle datasets download dhruvildave/spotify-charts -p data/raw/spotify

Two signals come from it, used in the 2017-2021 streaming sub-analysis:
- Top 200: daily stream counts, actual play volume rather than a rank.
- Viral 50: built from sudden sharing and discovery, not total plays, so it
  is the closest available stand-in for TikTok-style virality.

Spotify lists lead artists in the artist column but puts featured artists
in the song title ("Chantaje (feat. Maluma)"). `spotify_credit` rebuilds a
Billboard-style credit so both chart sources go through the same
CreditMatcher, with the same lead/featured roles and renamed-artist aliases.

Usage
-----
    python -m concert_demand.ingest.spotify_charts
"""

import logging
import re
import zipfile

import pandas as pd

from concert_demand.clean.artist_names import CreditMatcher, known_tour_artists, load_aliases
from concert_demand.paths import INTERIM_DIR, RAW_DIR

ZIP_PATH = RAW_DIR / "spotify" / "spotify-charts.zip"
ENGAGEMENTS_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
CHARTS_OUTPUT_PATH = INTERIM_DIR / "spotify_charts.csv"
CREDITS_OUTPUT_PATH = INTERIM_DIR / "spotify_credits.csv"

REGIONS = ["United States", "Canada"]
CHART_SIZES = {"top200": 200, "viral50": 50}
COLUMNS = ["title", "rank", "date", "artist", "region", "chart", "streams"]

# "(feat. X)", "[feat. X]", "(with X)", "(ft. X)", "(featuring X)", "(w/ X)".
# Parentheses or brackets are required: a bare "with" is part of a song title.
FEATURE_PATTERN = re.compile(
    r"[(\[]\s*(?:feat\.?|ft\.?|featuring|with|w/)\s*([^)\]]+)[)\]]", re.IGNORECASE)

logger = logging.getLogger(__name__)


def spotify_credit(artist, title):
    """Build a Billboard-style credit string from Spotify's artist and title.

    Parameters
    ----------
    artist : str
        Spotify's artist column (lead artists, comma-separated).
    title : str
        Song title, which may name featured artists.

    Returns
    -------
    str
        e.g. "Shakira Featuring Maluma" for artist "Shakira" and title
        "Chantaje (feat. Maluma)". Just the artist if nobody is featured.
    """
    featured = [match.strip() for match in FEATURE_PATTERN.findall(str(title))]
    if not featured:
        return artist
    return f"{artist} Featuring {' & '.join(featured)}"


def load_regions(zip_path=ZIP_PATH, regions=REGIONS, chunksize=1_000_000):
    """Read chart rows for the given regions straight from the Kaggle zip.

    The unzipped file is 3.5 GB, so it's streamed in chunks and filtered as
    it's read instead of being extracted or loaded whole.

    Parameters
    ----------
    zip_path : pathlib.Path
    regions : list of str
    chunksize : int

    Returns
    -------
    pandas.DataFrame
        Columns: title, rank, date, artist, region, chart, streams. Streams
        are missing for Viral 50, which doesn't publish them.
    """
    kept = []
    with zipfile.ZipFile(zip_path) as archive, archive.open("charts.csv") as csv_file:
        for chunk in pd.read_csv(csv_file, usecols=COLUMNS, chunksize=chunksize):
            kept.append(chunk[chunk["region"].isin(regions)])
    charts = pd.concat(kept, ignore_index=True)[COLUMNS]
    charts["date"] = pd.to_datetime(charts["date"]).astype("datetime64[ns]")
    charts["streams"] = charts["streams"].astype("Int64")
    return charts


def check_charts(charts, chart_sizes=CHART_SIZES):
    """Find missing days and short charts for each region and chart type.

    Parameters
    ----------
    charts : pandas.DataFrame
        Output of `load_regions`.
    chart_sizes : dict
        Chart type -> entries expected per day.

    Returns
    -------
    dict
        (region, chart) -> {"missing_days": list of dates between the first
        and last day with no chart, "short_days": count of days with fewer
        entries than expected}.
    """
    report = {}
    for (region, chart), group in charts.groupby(["region", "chart"]):
        days = group["date"].drop_duplicates()
        expected = pd.date_range(days.min(), days.max(), freq="D")
        per_day = group.groupby("date").size()
        report[(region, chart)] = {
            "missing_days": sorted(set(expected) - set(days)),
            "short_days": int((per_day < chart_sizes.get(chart, 0)).sum()),
        }
    return report


def match_credits(charts, matcher):
    """Attach tour artists and lead/featured roles to each chart row.

    Returns
    -------
    pandas.DataFrame
        One row per (chart entry, matched tour artist).
    """
    credit_strings = [spotify_credit(a, t) for a, t in zip(charts["artist"], charts["title"])]
    matches_by_credit = {credit: matcher.match(credit) for credit in set(credit_strings)}
    rows = [
        {**entry, "tour_artist": name, "role": role}
        for entry, credit in zip(charts.to_dict("records"), credit_strings)
        for name, role in matches_by_credit[credit]
    ]
    return pd.DataFrame(rows)


def run():
    """Filter to US and Canada, check coverage, and match credits to tour artists."""
    charts = load_regions()
    charts.to_csv(CHARTS_OUTPUT_PATH, index=False)
    logger.info("Saved %d US + Canada chart rows (%s to %s) to %s", len(charts),
                charts["date"].min().date(), charts["date"].max().date(), CHARTS_OUTPUT_PATH)

    for (region, chart), result in check_charts(charts).items():
        logger.info("%s %s: %d missing days %s, %d short days", region, chart,
                    len(result["missing_days"]),
                    [str(d.date()) for d in result["missing_days"][:5]], result["short_days"])

    artists = known_tour_artists(pd.read_csv(ENGAGEMENTS_PATH))
    matcher = CreditMatcher(artists, aliases=load_aliases(artists))
    credits = match_credits(charts, matcher)
    credits.to_csv(CREDITS_OUTPUT_PATH, index=False)
    logger.info("%d of %d tour artists appear on Spotify US/CA charts; saved %d credits "
                "(%d lead, %d featured) to %s", credits["tour_artist"].nunique(), len(artists),
                len(credits), (credits["role"] == "lead").sum(),
                (credits["role"] == "featured").sum(), CREDITS_OUTPUT_PATH)
    return credits


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
