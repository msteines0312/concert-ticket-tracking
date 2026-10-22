"""Assign each artist a genre group, using Billboard's top-level chart genres.

Genre is a control in the models: production level is judged against what's
normal for the genre (pop shows almost always have dancers, rock shows
rarely do), and popularity signals may mean different things across genres.

The groups follow Billboard's chart families, the music industry's standard
split and the same source as the project's chart data:

    Pop, Rock/Alternative, R&B/Hip-Hop, Country, Latin, Dance/Electronic, Other

Each artist's genres come from the "genre" field of their Wikipedia
infobox. Infoboxes don't list genres in order of importance (Taylor Swift:
pop, country, folk, rock), so every listed genre is mapped to a group and
the artist gets the most common one. Ties go to the first-listed genre, and
close votes are flagged so a person can check them.

Usage
-----
    python -m concert_demand.clean.genres
"""

import json
import logging
from collections import Counter

import mwparserfromhell
import pandas as pd

from concert_demand.clean.artist_names import known_tour_artists
from concert_demand.ingest import wikipedia_tours
from concert_demand.paths import INTERIM_DIR, RAW_DIR

CACHE_PATH = RAW_DIR / "artist_pages" / "artist_wikitext.json"
ENGAGEMENTS_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
OUTPUT_PATH = INTERIM_DIR / "artist_genres.csv"

# Whole labels that would be misread as substrings: "dance" alone is dance
# music, but "dance-pop" is pop, so these only match the exact label.
EXACT_LABELS = {"dance": "Dance/Electronic", "disco": "Dance/Electronic"}

# Checked in order, first match wins. Order matters for compound genres:
# "latin pop" must hit Latin before Pop, "pop-rap" must hit R&B/Hip-Hop.
GENRE_RULES = [
    ("Latin", ["latin", "reggaeton", "bachata", "urbano", "ranchera", "merengue", "flamenco",
               "salsa", "cumbia", "regional mexican", "corrido", "banda", "telenovela",
               "bolero", "mariachi"]),
    ("R&B/Hip-Hop", ["hip-hop", "hip hop", "rap", "r&b", "rhythm and blues", "soul", "trap", "funk",
                     "new jack swing"]),
    ("Country", ["country", "americana", "bluegrass", "honky-tonk"]),
    ("Dance/Electronic", ["edm", "electronic", "house", "techno", "trance", "dubstep", "amapiano",
                          "future bass"]),
    ("Rock/Alternative", ["rock", "metal", "punk", "grunge", "indie", "emo", "new wave",
                          "neue deutsche", "shoegaze", "alternative", "ska"]),
    ("Pop", ["pop", "schlager", "easy listening", "a cappella", "opm", "adult contemporary"]),
]
GROUPS = [group for group, _ in GENRE_RULES] + ["Other"]

# Artists whose infobox has no genre field
MANUAL_GENRES = {"Hugh Jackman": "Other"}  # actor touring The Greatest Showman soundtrack

logger = logging.getLogger(__name__)


def genre_group(genre):
    """Map one Wikipedia genre label to a Billboard genre group.

    Parameters
    ----------
    genre : str
        e.g. "Southern hip-hop", "Latin pop", "Broadway".

    Returns
    -------
    str
        One of GROUPS. Labels matching no rule (Broadway, folk, classical
        crossover) are "Other".
    """
    label = genre.lower().strip()
    if label in EXACT_LABELS:
        return EXACT_LABELS[label]
    for group, keywords in GENRE_RULES:
        if any(keyword in label for keyword in keywords):
            return group
    return "Other"


def infobox_genres(wikitext):
    """List the genres in an article's infobox, in the order written.

    Returns
    -------
    list of str
        Empty when the infobox has no genre field.
    """
    for template in mwparserfromhell.parse(wikitext).filter_templates():
        name = str(template.name).strip().lower()
        if name.startswith("infobox") and template.has("genre"):
            value = mwparserfromhell.parse(str(template.get("genre").value))
            # Citations sit inside the field, and their links ("AllMusic",
            # "Rolling Stone") would otherwise be read as genres
            for ref in value.filter_tags(matches=lambda tag: str(tag.tag).lower() == "ref"):
                value.remove(ref)
            links = [str(link.text or link.title).strip() for link in value.filter_wikilinks()]
            plain = value.strip_code().strip()
            return [label for label in links if label] or ([plain] if plain else [])
    return []


def assign_group(genres):
    """Pick an artist's group by majority vote over their listed genres.

    Labels that match no group (Broadway, folk, jazz) only count when an
    artist has nothing else. Otherwise they outvote real groups: Lady Gaga's
    "dance; jazz" beat her single "Pop" in a first version.

    Parameters
    ----------
    genres : list of str

    Returns
    -------
    tuple of (str, bool)
        The group, and whether it needs a person to check it: an exact tie
        between groups, broken by the first-listed genre.
    """
    groups = [genre_group(genre) for genre in genres]
    groups = [group for group in groups if group != "Other"] or groups
    counts = Counter(groups).most_common()
    top_count = counts[0][1]
    tied = {group for group, count in counts if count == top_count}
    winner = next(group for group in groups if group in tied)  # ties: first listed
    return winner, len(tied) > 1


def fetch_artist_pages(session, artists, cache_path=CACHE_PATH):
    """Wikitext of every artist page, cached as one JSON file."""
    pages = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    missing = [artist for artist in artists if artist not in pages]
    batch_size = wikipedia_tours.WIKITEXT_BATCH_SIZE
    for start in range(0, len(missing), batch_size):
        pages.update(wikipedia_tours.fetch_wikitexts(session, missing[start:start + batch_size]))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def run(output_path=OUTPUT_PATH):
    """Assign a genre group to every tour artist and save a review table."""
    artists = known_tour_artists(pd.read_csv(ENGAGEMENTS_PATH))
    pages = fetch_artist_pages(wikipedia_tours.build_session(), artists)

    rows = []
    for artist in artists:
        genres = infobox_genres(pages[artist]["wikitext"]) if artist in pages else []
        if artist in MANUAL_GENRES:
            group, review = MANUAL_GENRES[artist], False
        elif genres:
            group, review = assign_group(genres)
        else:
            group, review = "Other", True
        rows.append({"artist": artist, "genre_group": group, "needs_review": review,
                     "infobox_genres": "; ".join(genres)})

    table = pd.DataFrame(rows)
    table.to_csv(output_path, index=False)
    logger.info("Genre groups: %s", table["genre_group"].value_counts().to_dict())
    logger.info("%d artists flagged for review (tie broken by first-listed genre, or no genre)",
                table["needs_review"].sum())
    return table


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
