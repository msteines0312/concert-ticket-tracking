"""Extract production evidence and set length from each tour's Wikipedia article.

Matt's idea: does the type of show affect demand? His rubric has three tiers:

    Standard   A band with instruments and lights, the typical rock set in a
               smaller venue.
    Enhanced   Production beyond that: dancers (one ingredient, not a tier
               of its own), large set pieces, B-stages, pyrotechnics,
               costume changes.
    Themed     A show built around a concept: a story, acts or eras (the
               Eras Tour, Renaissance), on top of enhanced production.

Tours whose article doesn't describe the show are "Not described" and
treated as missing: no mention of dancers doesn't mean there were none.

Claude labels each tour from the evidence this module extracts, and Matt
hand-checks a random sample against the same evidence, so both judge the
same text. Production level is compared against genre norms in the model
(pop shows nearly always have dancers; rock shows rarely do).

Set length is the number of songs in the first set list in the article,
a separate, objective measure of how much show fans get.

Usage
-----
    python -m concert_demand.clean.production
"""

import json
import logging
import re
import sqlite3

import mwparserfromhell
import pandas as pd

from concert_demand.ingest.wikipedia_tours import CACHE_DIR, _cache_path
from concert_demand.load_db import DB_PATH
from concert_demand.paths import INTERIM_DIR

EVIDENCE_PATH = INTERIM_DIR / "production_evidence.csv"

# "Set list", "Typical setlist", "Standard set list ", "Tour set list". Not
# anchored to the end of the line: some headings carry trailing markup.
SET_LIST_HEADING = re.compile(r"^(=+)[^=\n]*\bset ?lists?\b[^=\n]*=+", re.IGNORECASE | re.MULTILINE)
ANY_HEADING = re.compile(r"^(=+)[^=\n]+=+", re.MULTILINE)
PRODUCTION_HEADING = re.compile(
    r"stage|production|staging|concert synopsis|synopsis|show|design|visual|development|concept",
    re.IGNORECASE)
# Words that signal a sentence describes the show itself
PRODUCTION_WORDS = re.compile(
    r"dancer|choreograph|stage|set piece|pyrotechnic|flames|fireworks|costume|catwalk|runway"
    r"|b-stage|\bacts?\b|segment|\beras?\b|theme|themed|narrative|storyline|concept|props?\b"
    r"|aerial|hydraulic|lift|screen|LED|lighting|lights|acoustic|stripped",
    re.IGNORECASE)
# Workaround, not a fix: a few articles use set-list formats the counter
# doesn't handle (Renaissance's comes from a credits list). Rather than
# parse every format, counts outside this range are kept but flagged as
# suspect so Phase 2 can leave them out deliberately.
PLAUSIBLE_SET_LENGTH = (10, 50)
SECTION_WORD_LIMIT = 150
MAX_SENTENCES = 6

logger = logging.getLogger(__name__)


def set_list_length(wikitext):
    """Songs in the article's first set list, or None if it has none.

    Looks inside the "Set list" section (up to the next heading of the same
    or higher level) for the first numbered line ("# Song"); leg
    subheadings, notes and layout templates before it are skipped. From
    there it counts numbered lines, stepping over act headers (";Act I"),
    blank lines and layout templates ("{{div col end}}"), so a show split
    into acts counts as one set. Any other line, such as a subheading for
    the next leg, ends the count, so a second set list isn't added in.
    """
    heading = SET_LIST_HEADING.search(wikitext)
    if not heading:
        return None
    level = len(heading.group(1))
    section = wikitext[heading.end():]
    for later in ANY_HEADING.finditer(section):
        if len(later.group(1)) <= level:
            section = section[:later.start()]
            break

    count, started = 0, False
    for line in section.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped.startswith("#"):
            entry = stripped[1:].strip()
            # "#*" lists songs that rotated in on some nights, "#;" is an
            # encore label and a bare "#" is empty: none is a song in the set
            if entry and not entry.startswith(("*", ";", ":")):
                count += 1
            started = True
        elif not started:
            continue
        elif lowered.startswith(("{{div col end", "{{hidden", "}}", "|")):
            break   # the first list's box closes; anything after is another set list
        elif stripped.startswith("''") and re.search(r"set ?list", lowered):
            break   # a bold caption for the next set list ("Setlist for Europe, leg 2")
        elif stripped == "" or stripped.startswith((";", ":", "''", "{{", "<")):
            continue   # act headers (";Act I", bold), italic interludes, templates, comments
        else:
            break
    return count or None


def _plain(wikicode):
    """Readable text: templates, references and markup removed."""
    for ref in wikicode.filter_tags(matches=lambda tag: str(tag.tag).lower() == "ref"):
        try:
            wikicode.remove(ref)
        except ValueError:      # already removed along with a parent
            pass
    return re.sub(r"\s+", " ", wikicode.strip_code()).strip()


def production_evidence(wikitext):
    """Text describing the show: production sections first, then matching sentences.

    Returns
    -------
    tuple of (str, bool)
        The evidence (at most a few hundred words), and whether the article
        has a section about the stage or production.
    """
    parsed = mwparserfromhell.parse(wikitext)
    pieces, has_section = [], False
    for section in parsed.get_sections(levels=[2, 3], include_lead=False):
        headings = section.filter_headings()
        title = str(headings[0].title).strip() if headings else ""
        if PRODUCTION_HEADING.search(title) and not re.search(r"set ?list|tour dates|box", title, re.I):
            has_section = True
            body = _plain(mwparserfromhell.parse(str(section).split("\n", 1)[-1]))
            words = body.split()
            pieces.append(f"[{title}] " + " ".join(words[:SECTION_WORD_LIMIT]))

    seen = " ".join(pieces)
    sentences = re.split(r"(?<=[.!?])\s+", _plain(mwparserfromhell.parse(wikitext)))
    extra = [s for s in sentences if PRODUCTION_WORDS.search(s) and s not in seen and len(s) < 400]
    pieces += extra[:MAX_SENTENCES]
    return " | ".join(pieces), has_section


def model_sample_tours(db_path=DB_PATH):
    """Tours with at least one show in the modeling sample."""
    with sqlite3.connect(db_path) as connection:
        return sorted(row[0] for row in connection.execute(
            "SELECT DISTINCT tour FROM model_sample"))


def run(output_path=EVIDENCE_PATH):
    """Write evidence and set length for every tour in the model sample."""
    rows = []
    for tour in model_sample_tours():
        page = json.loads(_cache_path(tour, CACHE_DIR).read_text(encoding="utf-8"))
        evidence, has_section = production_evidence(page["wikitext"])
        rows.append({"tour": tour, "set_list_songs": set_list_length(page["wikitext"]),
                     "has_production_section": has_section, "evidence": evidence})
    table = pd.DataFrame(rows)
    low, high = PLAUSIBLE_SET_LENGTH
    songs = table["set_list_songs"]
    table["set_list_suspect"] = songs.notna() & ((songs < low) | (songs > high))
    logger.info("%d set lengths flagged as suspect (outside %d-%d songs)",
                table["set_list_suspect"].sum(), low, high)
    table.to_csv(output_path, index=False)
    logger.info("%d tours: %d with a set list, %d with a production section",
                len(table), table["set_list_songs"].notna().sum(), table["has_production_section"].sum())
    return table


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
