"""Tests for parsing OCR text from the scanned 2019 Pollstar chart.

Pollstar data is copyrighted, so every row here is made up. The layout and
the kinds of noise (stray "|" and "_" after dates, rank digits) copy what
Tesseract returns for the real pages.
"""

import pandas as pd
import pytest

from concert_demand.ingest.pollstar_ocr import is_consistent, last_show_date, parse_ocr_text

OCR_TEXT = """\
Artist Tickets Sold
Date Facility/Promoter Support Capacity Gross
05/21/19 The Example Band Opener One 20,000 $2,000,000
05/22/19 Big Arena Opener Two 10,000
Springfield, IL 100%
2 shows Live Promoter 45.00 - 150.00
09/17/19 | Solo Singer 1,800 \u2014 $300,000
Small Theater 2,000
Testville, NY 90%
Some Promoter 50.00 - 750.00
07/05/19 Misread Act 67,836 $6,512,990
07/06/19 Big Field 43,491
Boulder, CO. 17%
2 shows AEG Presents 60.50 - 150.50
"""


def test_parse_ocr_text_reads_records_and_strips_noise():
    shows, _ = parse_ocr_text(OCR_TEXT, chart_year=2019)
    first, second = shows.iloc[0], shows.iloc[1]
    assert first["artist_text"] == "The Example Band Opener One"
    assert (first["n_shows"], first["tickets_sold"], first["capacity_per_show"]) == (2, 20_000, 10_000)
    assert first["end_date"] == pd.Timestamp("2019-05-22")
    assert second["artist_text"] == "Solo Singer"           # leading "|" removed
    assert (second["n_shows"], second["pct_sold"]) == (1, 90)
    assert second["end_date"] == second["start_date"]


def test_parse_ocr_text_drops_rows_that_fail_the_tickets_check():
    # OCR read 77% as 17%: 2 x 43,491 x 17% is nowhere near 67,836 tickets
    shows, dropped = parse_ocr_text(OCR_TEXT, chart_year=2019)
    assert len(shows) == 2
    assert dropped == 1
    assert "Misread Act" not in shows["artist_text"].tolist()


def test_is_consistent_allows_rounding_of_percent_sold():
    # 99% is rounded: 10,000 x 2 x 99% = 19,800, real tickets 19,870
    assert is_consistent({"capacity_per_show": 10_000, "n_shows": 2, "pct_sold": 99, "tickets_sold": 19_870})
    assert not is_consistent({"capacity_per_show": 10_000, "n_shows": 2, "pct_sold": 99, "tickets_sold": 15_000})


@pytest.mark.parametrize("start, lines, expected", [
    ("2019-10-16", ["10/17,21-22 Theater 3,319", "10/24-26,28 Chicago, IL 100%"], "2019-10-28"),
    ("2019-01-25", ["01/26,30,2/1 Colosseum 4,298", "02/02,08-09 Las Vegas, NV 77%"], "2019-02-09"),
    ("2018-12-28", ["12/30-31 Arena 5,353", "01/02 Las Vegas, NV 100%"], "2019-01-02"),
    ("2019-03-30", ["Stadium 55,255", "Atlanta, GA 100%"], "2019-03-30"),
])
def test_last_show_date_reads_compressed_date_lists(start, lines, expected):
    assert last_show_date(pd.Timestamp(start), lines) == pd.Timestamp(expected)
