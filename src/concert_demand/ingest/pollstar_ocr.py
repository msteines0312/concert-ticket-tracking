"""Read Pollstar's 2019 Top 200 Concert Grosses, a scanned PDF, with OCR.

The 2019 chart has no text layer, so each page is rendered to an image and
read with Tesseract. Pages have two columns of shows; Tesseract reads
straight across both, so each column is rendered and read separately.

Each show is four printed lines (the layout differs from 2022-23):

    05/21/19 Pink    Kid Cut Up        29,997  $5,527,014   <- start date, artist (+ support), tickets, gross
    05/22/19 Madison Square Garden     14,998               <- later dates, venue, capacity per show
    New York, NY                         100%               <- (more dates), city, % sold
    2 shows Live Nation          51.45 - 251.45             <- show count (multi-night only), promoter, prices

Large orange rank numbers sit at the edge of each column and sometimes leak
into the OCR text, so fields are found by pattern (a "$" amount, a "%", an
"N shows" count) rather than by position.

OCR misreads digits, so every row gets an internal consistency check:
Pollstar prints tickets, capacity per show, show count and % sold, and
tickets should be close to capacity x shows x % sold. Rows that fail are
dropped instead of guessed at.

Requires two command-line tools: pdftoppm (Poppler, also bundled with
MiKTeX) and Tesseract (https://github.com/UB-Mannheim/tesseract).
"""

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
from PIL import Image

logger = logging.getLogger(__name__)

DPI = 300
PAGE_WIDTH_PX = 2550    # letter-size page at 300 dpi
PAGE_HEIGHT_PX = 3300
# Each show's first line (date, artist, tickets, gross) is printed on a
# light gray band. Tesseract skipped those lines entirely on 4 of 5 pages
# until the image was turned pure black and white: pixels lighter than
# this become white (the band disappears), darker ones black (the text).
# 150 recovered all 22 first lines on a test page; 180 recovered none.
BINARIZE_THRESHOLD = 150
TESSERACT_DEFAULT = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")

# Tickets vs capacity x shows x % sold may differ by rounding: % sold is a
# whole number, so allow 1.5% plus a few tickets
CONSISTENCY_TOLERANCE = 0.015

START_PATTERN = re.compile(
    r"^(?P<start>\d\d/\d\d/\d\d)\W*(?P<artist_text>.+?)\s+(?P<tickets>\d{1,3}(?:,\d{3})+|\d{1,3})"
    r"\W*\$(?P<gross>[\d,]+)"
)
# Leading run of dates on a line: "05/22/19", "10/17,21-22", "01/26,30,2/1"
DATE_FRAGMENT = re.compile(r"^\d{1,2}/[\d/,\-]+")
CAPACITY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3})\s*\S{0,3}\s*$")
PERCENT_PATTERN = re.compile(r"(\d{1,3})%")
SHOWS_PATTERN = re.compile(r"^(\d+)\s+shows\b")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def find_tesseract():
    """Path to the Tesseract executable: on PATH, or the default Windows install."""
    found = shutil.which("tesseract")
    if found:
        return found
    if TESSERACT_DEFAULT.exists():
        return str(TESSERACT_DEFAULT)
    raise FileNotFoundError("Tesseract not found. Install it, e.g. `winget install UB-Mannheim.TesseractOCR`")


def ocr_pdf(pdf_path, n_pages):
    """OCR every page of the PDF, one column at a time.

    Returns
    -------
    str
        All columns' text, left column before right on each page.
    """
    tesseract = find_tesseract()
    half = PAGE_WIDTH_PX // 2
    texts = []
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, n_pages + 1):
            for column, x in [("left", 0), ("right", half)]:
                image_root = Path(tmp) / f"p{page}_{column}"
                subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", "-png", "-singlefile",
                                "-f", str(page), "-l", str(page),
                                "-x", str(x), "-y", "0", "-W", str(half), "-H", str(PAGE_HEIGHT_PX),
                                str(pdf_path), str(image_root)], check=True)
                image = Image.open(f"{image_root}.png").convert("L")
                image.point(lambda value: 255 if value > BINARIZE_THRESHOLD else 0).save(f"{image_root}.png")
                # --psm 6: treat the image as one block of text, which keeps each printed line together
                result = subprocess.run([tesseract, f"{image_root}.png", "stdout", "--psm", "6"],
                                        check=True, capture_output=True, text=True, encoding="utf-8")
                texts.append(result.stdout)
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _number(text):
    return int(text.replace(",", ""))


def last_show_date(start, follow_lines):
    """Last night of a run, from the dates printed at the start of later lines.

    Dates are compressed: "10/17,21-22" means Oct 17, 21 and 22, and a new
    month is written as month/day mid-list ("01/26,30,2/1" ends on Feb 1).
    So the tokens are read in order, carrying the current month forward.

    Parameters
    ----------
    start : pandas.Timestamp
    follow_lines : list of str
        The lines after the first one.

    Returns
    -------
    pandas.Timestamp
        `start` when no later dates are printed. A run from late December
        into January rolls into the next year.
    """
    month, year, end = start.month, start.year, start
    for line in follow_lines:
        fragment = DATE_FRAGMENT.match(line.strip())
        if not fragment:
            continue
        for token in fragment.group(0).strip(",-").split(","):
            last = token.split("-")[-1]             # "21-22" -> "22"
            parts = [part for part in last.split("/") if part]
            if len(parts) >= 2:                     # "2/1" or "05/22/19": month changes
                month, day = int(parts[0]), int(parts[1])
            elif parts:
                day = int(parts[0])
            else:
                continue
            candidate = pd.Timestamp(year=year, month=month, day=day)
            if candidate < start - pd.Timedelta(days=31):   # wrapped past December
                year += 1
                candidate = candidate.replace(year=year)
            end = max(end, candidate)
    return end


def parse_record(lines):
    """Parse one show's lines (the start line plus what follows) into a dict, or None."""
    start = START_PATTERN.match(lines[0].strip())
    if not start:
        return None
    rest = lines[1:4]
    capacity = next((CAPACITY_PATTERN.search(line) for line in rest[:1]
                     if CAPACITY_PATTERN.search(line)), None)
    percent = next((PERCENT_PATTERN.search(line) for line in rest if PERCENT_PATTERN.search(line)), None)
    shows = next((SHOWS_PATTERN.match(line.strip()) for line in rest
                  if SHOWS_PATTERN.match(line.strip())), None)
    if capacity is None or percent is None:
        return None
    start_date = pd.to_datetime(start["start"], format="%m/%d/%y")
    return {
        "start_date": start_date,
        "end_date": last_show_date(start_date, rest),
        "artist_text": start["artist_text"].strip(" |_-\u2014"),
        "venue_text": rest[0].strip(),
        "n_shows": int(shows.group(1)) if shows else 1,
        "tickets_sold": _number(start["tickets"]),
        "gross_usd": float(_number(start["gross"])),
        "capacity_per_show": _number(capacity.group(1)),
        "pct_sold": int(percent.group(1)),
    }


def is_consistent(record, tolerance=CONSISTENCY_TOLERANCE):
    """True if tickets match capacity x shows x % sold, within rounding."""
    expected = record["capacity_per_show"] * record["n_shows"] * record["pct_sold"] / 100
    return abs(record["tickets_sold"] - expected) <= tolerance * expected + 5


def parse_ocr_text(text, chart_year):
    """Parse OCR text into one row per show, dropping rows that fail the consistency check.

    Returns
    -------
    tuple of (pandas.DataFrame, int)
        Parsed shows, and how many candidate rows were dropped as misreads.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    records, dropped = [], 0
    for i, line in enumerate(lines):
        if not START_PATTERN.match(line.strip()):
            continue
        record = parse_record(lines[i:i + 4])
        if record is None or not is_consistent(record):
            dropped += 1
            continue
        records.append({"chart_year": chart_year, **record})
    return pd.DataFrame(records), dropped
