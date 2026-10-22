"""Download US consumer prices (CPI-U) to put ticket prices in constant dollars.

Matt's call: an artist's previous-tour price can come from any year
between 2009 and 2025, and prices rose about 46% over that stretch, so a
$100 ticket in 2014 is not the same as one in 2024. Prices are converted
to BASE_YEAR dollars with the CPI-U annual average.

Source: US Bureau of Labor Statistics, series CUUR0000SA0 (CPI for All
Urban Consumers, US city average, all items, not seasonally adjusted).
Public domain. The keyless v1 API returns at most 10 years per request,
so the range is fetched in chunks.

Known gap: BLS published no October 2025 value ("Data unavailable due to
the 2025 lapse in appropriations"). The 2025 average is taken over the 11
months that exist and flagged with months < 12. This is a workaround: if
BLS later publishes an official 2025 annual average, use that instead.

Usage
-----
    python -m concert_demand.ingest.cpi            # use cached file
    python -m concert_demand.ingest.cpi --refresh  # re-download
"""

import argparse
import json
import logging

import pandas as pd
import requests

from concert_demand.paths import INTERIM_DIR, RAW_DIR

SERIES_ID = "CUUR0000SA0"
API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
FIRST_YEAR = 2009          # earliest show in the engagements table
LAST_YEAR = 2025           # latest full year before the newest model show
BASE_YEAR = 2024           # latest year with all 12 months published
MAX_YEARS_PER_REQUEST = 10

CACHE_PATH = RAW_DIR / "cpi" / "cpi_u_monthly.json"
OUTPUT_PATH = INTERIM_DIR / "cpi_u_annual.csv"

logger = logging.getLogger(__name__)


def year_chunks(first_year, last_year, size=MAX_YEARS_PER_REQUEST):
    """Split an inclusive year range into chunks the v1 API accepts.

    Returns
    -------
    list of tuple of (int, int)
        Inclusive (start, end) pairs, e.g. 2012-2025 -> [(2012, 2021), (2022, 2025)].
    """
    return [(start, min(start + size - 1, last_year))
            for start in range(first_year, last_year + 1, size)]


def download_monthly(session, refresh=False):
    """Fetch monthly CPI-U records from BLS, cached as raw JSON.

    Returns
    -------
    list of dict
        BLS data records: year, period ("M01".."M12"), value, footnotes.
    """
    if CACHE_PATH.exists() and not refresh:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    records = []
    for start, end in year_chunks(FIRST_YEAR, LAST_YEAR):
        response = session.post(API_URL, timeout=60, json={
            "seriesid": [SERIES_ID], "startyear": str(start), "endyear": str(end)})
        response.raise_for_status()
        payload = response.json()
        # BLS reports errors inside a 200 response, so check the status field.
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS request failed: {payload.get('message')}")
        records.extend(payload["Results"]["series"][0]["data"])

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def parse_monthly(records):
    """Turn BLS records into one row per published month.

    Months BLS couldn't publish come back as "-" and are dropped rather
    than read as zero. Period "M13" (an annual average some series carry)
    is skipped so every year is averaged the same way.

    Returns
    -------
    pandas.DataFrame
        Columns: year, month, cpi_u.
    """
    rows = [{"year": int(record["year"]), "month": int(record["period"][1:]),
             "cpi_u": float(record["value"])}
            for record in records
            if record["period"] != "M13" and record["value"] != "-"]
    return pd.DataFrame(rows).sort_values(["year", "month"]).reset_index(drop=True)


def annual_averages(monthly):
    """Average CPI-U by year, keeping how many months went into each average.

    Returns
    -------
    pandas.DataFrame
        Columns: year, cpi_u, months.
    """
    annual = monthly.groupby("year")["cpi_u"].agg(cpi_u="mean", months="size").reset_index()
    for row in annual[annual["months"] < 12].itertuples():
        logger.warning("CPI-U %d averages only %d months", row.year, row.months)
    return annual


def to_constant_dollars(amounts, years, annual, base_year=BASE_YEAR):
    """Convert nominal dollars to `base_year` dollars.

    Parameters
    ----------
    amounts : pandas.Series
        Nominal dollar amounts.
    years : pandas.Series
        Year each amount was paid, aligned with `amounts`.
    annual : pandas.DataFrame
        Output of `annual_averages`.
    base_year : int

    Returns
    -------
    pandas.Series
        Constant-dollar amounts. Null where the year has no CPI value, so
        a missing year shows up instead of silently passing through unadjusted.
    """
    index = annual.set_index("year")["cpi_u"]
    factor = index[base_year] / years.map(index)
    return amounts * factor


def load_annual():
    """Read the saved annual CPI-U table."""
    return pd.read_csv(OUTPUT_PATH)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download from BLS")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with requests.Session() as session:
        records = download_monthly(session, refresh=args.refresh)
    annual = annual_averages(parse_monthly(records))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(OUTPUT_PATH, index=False)
    logger.info("Saved CPI-U %d-%d to %s", annual["year"].min(), annual["year"].max(), OUTPUT_PATH)


if __name__ == "__main__":
    main()
