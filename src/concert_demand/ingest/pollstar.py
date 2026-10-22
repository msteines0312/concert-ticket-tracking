"""Parse Pollstar's year-end Top Concert Grosses PDFs and check them against Wikipedia.

Pollstar is used only to validate the Wikipedia attendance figures. It is
an independent compilation of the same box office reports, so agreement
between the two is evidence the Wikipedia parser is reading tables
correctly. The data is copyrighted: raw rows stay in data/ (gitignored) and
only summary statistics are reported.

Each show in the PDF's text layer is four lines:

    06/09/22 Ed Sheeran  218,639 $18,242,198           <- start date, artist (+ support), tickets, gross
     06/12/22 Etihad Stadium, Manchester, UNITED KINGDOM   <- end date (multi-night runs only), venue
     4 shows FKP Scorpio Konzertproduktionen             <- show count (multi-night only), promoter
      CAP: 54,659 | 100% Sold | Tkt: 45.00 - 75.00 | ...  <- capacity per show, % sold, price range

Support acts are printed in a right-hand column, so their names run onto
the end of all four lines. That makes the artist / support split ambiguous
("Ed Sheeran Griff"), which is why matching to Wikipedia uses the start
date plus a prefix comparison of the artist name instead of an exact split.

Only the 2022 and 2023 Top 300 have a text layer. The 2019 Top 200 is a
scanned image with a different layout, read with OCR in pollstar_ocr.py.
It adds the only pre-COVID validation.

Usage
-----
    python -m concert_demand.ingest.pollstar            # use cached PDFs
    python -m concert_demand.ingest.pollstar --refresh  # re-download
"""

import argparse
import logging
import re
from difflib import SequenceMatcher

import pandas as pd
from pypdf import PdfReader

from concert_demand.clean.artist_names import normalize_name
from concert_demand.ingest import pollstar_ocr
from concert_demand.ingest.wikipedia_tours import OUTPUT_PATH as ENGAGEMENTS_PATH
from concert_demand.ingest.wikipedia_tours import build_session
from concert_demand.paths import INTERIM_DIR, RAW_DIR

# chart year -> PDF URL (citations in the README). The 2019 file moved from
# www.pollstar.com, which now returns an HTML page, to data.pollstar.com.
PDF_URLS = {
    2019: "https://data.pollstar.com/Chart/2019/12/Top200ConcertGrosses_793.pdf",
    2022: "https://data.pollstar.com/chart/2022/12/121222.top.300.concert.grosses_1027.pdf",
    2023: "https://data.pollstar.com/Chart/2024/01/121123_ye.top300.concert.grosses_digital_1040.pdf",
}
TEXT_LAYER_YEARS = [2022, 2023]
OCR_YEAR = 2019                  # scanned image, see pollstar_ocr.py
OCR_PAGES = 5

CACHE_DIR = RAW_DIR / "pollstar"
OUTPUT_PATH = INTERIM_DIR / "pollstar_grosses.csv"
MATCHES_PATH = INTERIM_DIR / "pollstar_matches.csv"

HEADER_PATTERN = re.compile(
    r"^(?P<start>\d\d/\d\d/\d\d) (?P<artist_text>.+?)\s+(?P<tickets>[\d,]+) \$(?P<gross>[\d,]+)\s*$"
)
END_DATE_PATTERN = re.compile(r"^\s*(?P<end>\d\d/\d\d/\d\d)\s")
SHOWS_PATTERN = re.compile(r"^\s*(?P<n>\d+) shows\b")
CAP_PATTERN = re.compile(
    r"CAP: (?P<cap>[\d,]+) \| (?P<pct>\d+)% Sold \| Tkt: (?P<tkt_min>[\d,.]+)(?: - (?P<tkt_max>[\d,.]+))?"
)

# A Wikipedia artist matches a Pollstar row when the start of the Pollstar
# artist text is at least this similar. Below 1.0 because pypdf drops
# accented characters: Wikipedia "Beyonce" vs Pollstar "Beyonc".
ARTIST_SIMILARITY = 0.85

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pdfs(session, refresh=False):
    """Download every year's PDF into the raw cache.

    Parameters
    ----------
    session : requests.Session
    refresh : bool
        Re-download even if a cached file exists.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for year, url in PDF_URLS.items():
        path = CACHE_DIR / f"pollstar_{year}.pdf"
        if path.exists() and not refresh:
            continue
        response = session.get(url, timeout=120)
        response.raise_for_status()
        # Pollstar answers moved files with an HTML page and status 200, so
        # check the file signature instead of trusting the status code.
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"{url} did not return a PDF")
        path.write_bytes(response.content)
        logger.info("Downloaded %s (%.1f MB)", path.name, len(response.content) / 1e6)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _to_number(text):
    """Turn "1,234.50" into 1234.5."""
    return float(text.replace(",", ""))


def parse_record(lines):
    """Parse one show's four text lines into a dict.

    Parameters
    ----------
    lines : list of str
        Header, venue, promoter and capacity lines, in that order.

    Returns
    -------
    dict or None
        None if the lines don't form a complete record.
    """
    header = HEADER_PATTERN.match(lines[0])
    cap = CAP_PATTERN.search(lines[3])
    if not header or not cap:
        return None

    end = END_DATE_PATTERN.match(lines[1])
    shows = SHOWS_PATTERN.match(lines[2])
    start_date = pd.to_datetime(header["start"], format="%m/%d/%y")
    venue_line = END_DATE_PATTERN.sub("", lines[1]).strip()
    ticket_min = _to_number(cap["tkt_min"])

    return {
        "start_date": start_date,
        "end_date": pd.to_datetime(end["end"], format="%m/%d/%y") if end else start_date,
        "artist_text": header["artist_text"].strip(),
        "venue_text": venue_line,
        "n_shows": int(shows["n"]) if shows else 1,
        "tickets_sold": int(_to_number(header["tickets"])),
        "gross_usd": _to_number(header["gross"]),
        "capacity_per_show": int(_to_number(cap["cap"])),
        "pct_sold": int(cap["pct"]),
        "ticket_min": ticket_min,
        "ticket_max": _to_number(cap["tkt_max"]) if cap["tkt_max"] else ticket_min,
    }


def parse_text(text, chart_year):
    """Parse a whole PDF's extracted text into one row per show.

    Parameters
    ----------
    text : str
        Text of every page joined with newlines.
    chart_year : int

    Returns
    -------
    pandas.DataFrame
        One row per show, in the order they appear in the text.
    """
    lines = text.splitlines()
    records = []
    for i, line in enumerate(lines):
        if HEADER_PATTERN.match(line):
            record = parse_record(lines[i:i + 4])
            if record is None:
                logger.warning("Unparsed record in %d: %r", chart_year, line)
                continue
            records.append({"chart_year": chart_year, **record})
    return pd.DataFrame(records)


def extract_text(path):
    """Return the text layer of every page in a PDF, joined with newlines."""
    return "\n".join(page.extract_text() for page in PdfReader(path).pages)


# ---------------------------------------------------------------------------
# Validate against Wikipedia
# ---------------------------------------------------------------------------

def _match_key(name):
    """Letters and digits only, so "Guns N' Roses" and "Guns N Roses" compare equal."""
    return normalize_name(name).replace(" ", "")


def artist_matches(wikipedia_artist, pollstar_text):
    """Check whether a Pollstar artist line starts with the Wikipedia artist.

    Parameters
    ----------
    wikipedia_artist : str
    pollstar_text : str
        Artist plus any support acts, e.g. "Ed Sheeran Griff".

    Returns
    -------
    bool
    """
    wiki_key = _match_key(wikipedia_artist)
    pollstar_prefix = _match_key(pollstar_text)[:len(wiki_key)]
    return SequenceMatcher(None, wiki_key, pollstar_prefix).ratio() >= ARTIST_SIMILARITY


def match_to_wikipedia(pollstar, engagements):
    """Roll Pollstar rows up to the Wikipedia engagement they fall inside.

    The two sources group nights differently. Wikipedia collapses a
    multi-night run into one engagement, while Pollstar sometimes reports
    each night as its own row (Guns N' Roses, Tottenham 2022) or splits a
    residency into chunks. So every Pollstar row whose dates fall inside an
    engagement's date range, by the same artist, is summed before comparing.

    Parameters
    ----------
    pollstar : pandas.DataFrame
        Output of `parse_text`.
    engagements : pandas.DataFrame
        Wikipedia engagements with artist, first_date, last_date, n_shows,
        tickets_sold, capacity, sold_out.

    Returns
    -------
    pandas.DataFrame
        One row per matched engagement with both sources' figures side by
        side. `complete` is True when Pollstar covers every night, which is
        the only case where totals are comparable.
    """
    wiki = engagements.dropna(subset=["artist", "first_date", "last_date", "tickets_sold"])
    pairs = []
    for row in pollstar.itertuples():
        in_range = wiki[(wiki["first_date"] <= row.start_date) & (wiki["last_date"] >= row.end_date)]
        for wiki_index, artist in in_range["artist"].items():
            if artist_matches(artist, row.artist_text):
                pairs.append({"wiki_index": wiki_index, "pollstar_index": row.Index})
    if not pairs:
        return pd.DataFrame()

    linked = pd.DataFrame(pairs).join(pollstar, on="pollstar_index")
    linked["capacity"] = linked["capacity_per_show"] * linked["n_shows"]
    # Pollstar rounds % sold to whole numbers, so "100% Sold" is its sellout label
    linked["sold_out"] = linked["pct_sold"] >= 100
    rolled = linked.groupby("wiki_index").agg(
        pollstar_rows=("pollstar_index", "size"),
        n_shows=("n_shows", "sum"),
        tickets_sold=("tickets_sold", "sum"),
        capacity=("capacity", "sum"),
        sold_out=("sold_out", "all"),
    )

    columns = ["artist", "first_date", "last_date", "n_shows", "tickets_sold", "capacity", "sold_out"]
    matches = wiki.loc[rolled.index, columns].join(rolled, lsuffix="_wiki", rsuffix="_pollstar")
    matches["complete"] = matches["n_shows_pollstar"] == matches["n_shows_wiki"]
    matches["tickets_diff_pct"] = (
        (matches["tickets_sold_wiki"] - matches["tickets_sold_pollstar"])
        / matches["tickets_sold_pollstar"]
    )
    return matches


def summarize_matches(matches, pollstar):
    """Summary statistics for the README. No individual Pollstar rows.

    Agreement is measured only on complete matches (Pollstar covers every
    night of the engagement), since a partial match compares a subset of
    nights to the whole run.

    Returns
    -------
    dict
    """
    complete = matches[matches["complete"]]
    abs_diff = complete["tickets_diff_pct"].abs()
    return {
        "pollstar_rows": len(pollstar),
        "pollstar_rows_matched": int(matches["pollstar_rows"].sum()),
        "engagements_matched": len(matches),
        "engagements_complete": len(complete),
        "tickets_exact": round(float((abs_diff == 0).mean()), 3),
        "tickets_within_1pct": round(float((abs_diff <= 0.01).mean()), 3),
        "median_abs_tickets_diff": round(float(abs_diff.median()), 4),
        "sold_out_agreement": round(float((complete["sold_out_wiki"] == complete["sold_out_pollstar"]).mean()), 3),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def load_ocr_year(refresh=False):
    """Parse the scanned 2019 chart, reusing cached OCR text unless refreshing.

    OCR takes a few minutes, so its raw text is saved next to the PDF.
    """
    text_path = CACHE_DIR / f"pollstar_{OCR_YEAR}_ocr.txt"
    if refresh or not text_path.exists():
        text_path.write_text(pollstar_ocr.ocr_pdf(CACHE_DIR / f"pollstar_{OCR_YEAR}.pdf", OCR_PAGES),
                             encoding="utf-8")
    shows, dropped = pollstar_ocr.parse_ocr_text(text_path.read_text(encoding="utf-8"), OCR_YEAR)
    logger.info("Pollstar %d: %d rows dropped as OCR misreads (failed the tickets check)",
                OCR_YEAR, dropped)
    return shows


def run(refresh=False):
    """Download, parse and validate. Returns the summary dict, overall and per year."""
    download_pdfs(build_session(), refresh=refresh)
    pollstar = pd.concat(
        [parse_text(extract_text(CACHE_DIR / f"pollstar_{year}.pdf"), year) for year in TEXT_LAYER_YEARS]
        + [load_ocr_year(refresh)],
        ignore_index=True,
    )
    for year, rows in pollstar.groupby("chart_year"):
        logger.info("Pollstar %d: %d shows parsed", year, len(rows))
    pollstar.to_csv(OUTPUT_PATH, index=False)

    engagements = pd.read_csv(ENGAGEMENTS_PATH, parse_dates=["first_date", "last_date"])
    matches = match_to_wikipedia(pollstar, engagements)
    matches.to_csv(MATCHES_PATH, index=False)
    summary = summarize_matches(matches, pollstar)
    logger.info("Validation summary, all years: %s", summary)
    # Per year, so the pre-COVID check (2019) can be compared with 2022-23
    for year, rows in pollstar.groupby("chart_year"):
        year_matches = match_to_wikipedia(rows, engagements)
        logger.info("Validation summary, %d: %s", year, summarize_matches(year_matches, rows))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refresh", action="store_true", help="re-download the PDFs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
