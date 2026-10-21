"""Download and validate Billboard Hot 100 and Billboard 200 chart history.

Source: utdata/rwd-billboard-data, an MIT-licensed archive that scrapes both
charts weekly (Hot 100 from 1958, Billboard 200 from 1967). The chart data
itself belongs to Billboard. The archive's README notes minor data errors
and some missing weeks, so every load runs `check_chart` and logs what it
finds instead of assuming the data is complete.

The archive's latest commit ID is saved with the download so results can
cite the exact version used.

Usage
-----
    python -m concert_demand.ingest.billboard_charts            # use cached files
    python -m concert_demand.ingest.billboard_charts --refresh  # re-download
"""

import argparse
import json
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from concert_demand.paths import INTERIM_DIR, RAW_DIR

REPO = "utdata/rwd-billboard-data"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{{commit}}/data-out/{{filename}}"
LATEST_COMMIT_URL = f"https://api.github.com/repos/{REPO}/commits/main"

# chart key -> (file in the archive, entries per week)
CHARTS = {
    "hot100": ("hot-100-current.csv", 100),
    "billboard200": ("billboard-200-current.csv", 200),
}

CACHE_DIR = RAW_DIR / "billboard"
METADATA_PATH = CACHE_DIR / "source.json"
OUTPUT_PATH = INTERIM_DIR / "billboard_charts.csv"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def latest_commit(session):
    """Return the archive's latest commit ID and date on the main branch."""
    response = session.get(LATEST_COMMIT_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload["sha"], payload["commit"]["committer"]["date"]


def download_charts(session, refresh=False):
    """Download both chart files, pinned to one archive commit.

    Downloading by commit ID (not "main") guarantees both files come from
    the same snapshot even if the archive updates mid-download.

    Parameters
    ----------
    session : requests.Session
    refresh : bool
        Re-download even if cached files exist.

    Returns
    -------
    dict
        Source metadata: commit, commit_date, downloaded_at, files.
    """
    files_present = all((CACHE_DIR / filename).exists() for filename, _ in CHARTS.values())
    if files_present and METADATA_PATH.exists() and not refresh:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    commit, commit_date = latest_commit(session)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, _ in CHARTS.values():
        response = session.get(RAW_URL.format(commit=commit, filename=filename), timeout=120)
        response.raise_for_status()
        (CACHE_DIR / filename).write_bytes(response.content)
        logger.info("Downloaded %s (%.1f MB)", filename, len(response.content) / 1e6)

    metadata = {
        "repo": f"https://github.com/{REPO}",
        "commit": commit,
        "commit_date": commit_date,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [filename for filename, _ in CHARTS.values()],
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


# ---------------------------------------------------------------------------
# Load + validate
# ---------------------------------------------------------------------------

def load_chart(path, chart):
    """Read one archive CSV into the project's standard chart format.

    Parameters
    ----------
    path : pathlib.Path
    chart : str
        Chart key, e.g. "hot100".

    Returns
    -------
    pandas.DataFrame
        Columns: chart, chart_week, rank, title, performer, last_week,
        peak_pos, wks_on_chart. last_week is null for new entries and
        re-entries (the archive uses both 0 and NA for that). Rows repeated
        verbatim in the archive are dropped. Two different titles sharing a
        rank are kept, since old print charts did list ties.
    """
    raw = pd.read_csv(path, na_values=["NA"], keep_default_na=True).drop_duplicates()
    last_week = raw["last_week"].astype("Int64")
    return pd.DataFrame({
        "chart": chart,
        "chart_week": pd.to_datetime(raw["chart_week"]).astype("datetime64[ns]"),
        "rank": raw["current_week"].astype(int),
        "title": raw["title"],
        "performer": raw["performer"],
        "last_week": last_week.mask(last_week == 0),
        "peak_pos": raw["peak_pos"].astype(int),
        "wks_on_chart": raw["wks_on_chart"].astype(int),
    })


def check_chart(chart, chart_size):
    """Find gaps and errors in one chart's weekly history.

    Parameters
    ----------
    chart : pandas.DataFrame
        Output of `load_chart` for a single chart.
    chart_size : int
        Entries expected per week (100 or 200).

    Returns
    -------
    dict
        missing_weeks: estimated dates of weeks absent from the history.
        incomplete_weeks: weeks without exactly `chart_size` entries.
        duplicate_ranks: count of repeated (week, rank) pairs.

    Notes
    -----
    Missing weeks are found from gaps between consecutive chart dates, not
    by comparing against a fixed weekly calendar. Billboard has changed the
    weekday its charts are dated on (Monday to Saturday for the Hot 100),
    so a fixed calendar would flag every week after the switch as missing.
    A gap of 14+ days means at least one week is missing.
    """
    weeks = chart["chart_week"].drop_duplicates().sort_values().reset_index(drop=True)
    missing = []
    for previous, current in zip(weeks[:-1], weeks[1:]):
        gap_weeks = round((current - previous).days / 7)
        missing += [previous + pd.Timedelta(weeks=k) for k in range(1, gap_weeks)]

    entries_per_week = chart.groupby("chart_week").size()
    return {
        "missing_weeks": missing,
        "incomplete_weeks": sorted(entries_per_week[entries_per_week != chart_size].index),
        "duplicate_ranks": int(chart.duplicated(["chart_week", "rank"]).sum()),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(refresh=False, output_path=OUTPUT_PATH):
    """Download (if needed), validate and combine both charts.

    Returns
    -------
    pandas.DataFrame
        Both charts stacked, also written to `output_path` as CSV.
    """
    metadata = download_charts(requests.Session(), refresh=refresh)
    logger.info("Archive commit %s (%s)", metadata["commit"][:7], metadata["commit_date"])

    charts = []
    for chart_key, (filename, chart_size) in CHARTS.items():
        chart = load_chart(CACHE_DIR / filename, chart_key)
        report = check_chart(chart, chart_size)
        logger.info("%s: %d rows, %s to %s", chart_key, len(chart),
                    chart["chart_week"].min().date(), chart["chart_week"].max().date())
        # Known issues in the archive are logged, not fixed: they're small,
        # and silently patching them would hide where the data is thin.
        logger.info("%s: %d missing weeks %s, %d incomplete weeks, %d duplicate ranks",
                    chart_key, len(report["missing_weeks"]),
                    [str(w.date()) for w in report["missing_weeks"][:5]],
                    len(report["incomplete_weeks"]), report["duplicate_ranks"])
        charts.append(chart)

    combined = pd.concat(charts, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    logger.info("Saved %d chart entries to %s", len(combined), output_path)
    return combined


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refresh", action="store_true", help="re-download the archive")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
