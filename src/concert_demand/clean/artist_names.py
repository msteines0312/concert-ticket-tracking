"""Normalize artist names and match Billboard chart credits to tour artists.

Billboard credits combine artists in one string ("Drake Featuring Future &
Young Thug"), while tour artists come from Wikipedia titles ("Ghost (Swedish
band)"). Matching them takes three steps:

1. Tokenize both sides the same way: lowercase, strip accents, "&" and "+"
   become "and", punctuation is dropped ("JAY-Z" -> "jayz").
2. Protect known names that contain a separator word ("Earth, Wind & Fire",
   "Lil Nas X") by locking them into one token before splitting.
3. Split the credit at separators and match each piece exactly. Everything
   before "featuring" / "feat" / "ft" / "with" is a lead credit, everything
   after is featured. "and", "x" and commas join artists with the same role.

Matching whole pieces exactly, instead of searching for names inside the
string, keeps "Drake" from matching "Drake Bell".

Usage
-----
    python -m concert_demand.clean.artist_names
"""

import logging
import re
import unicodedata

import pandas as pd

from concert_demand.paths import INTERIM_DIR

ENGAGEMENTS_PATH = INTERIM_DIR / "wikipedia_engagements.csv"
CHARTS_PATH = INTERIM_DIR / "billboard_charts.csv"
OUTPUT_PATH = INTERIM_DIR / "chart_credits.csv"
UNMATCHED_PATH = INTERIM_DIR / "unmatched_tour_artists.csv"
REDIRECTS_PATH = INTERIM_DIR / "artist_redirects.csv"
ALIAS_REPORT_PATH = INTERIM_DIR / "alias_matches.csv"

# Separator token -> what it does to the role of the credits that follow
SEPARATORS = {
    ",": "same", "and": "same", "x": "same",
    "featuring": "featured", "feat": "featured", "ft": "featured", "with": "featured",
}

# Wikipedia title -> spellings Billboard uses that normalization can't bridge.
# Built from the unmatched-artist report; each entry was checked by hand
# against the artist's Wikipedia page and the chart archive.
ALIASES = {
    "Pink (singer)": ["P!nk"],
    # Stage name "Marina and the Diamonds" until 2019, then "MARINA"
    "Marina Diamandis": ["Marina And The Diamonds", "MARINA"],
    # Renamed from Lady Antebellum in 2020; charted under the old name 2008-2020
    "Lady A": ["Lady Antebellum"],
    # Credited as "Janet" 1997-2016 (328 chart rows, e.g. "Together Again")
    "Janet Jackson": ["Janet"],
    # Legal name since 2021; credited as "Ye" in 2026 (25 chart rows)
    "Kanye West": ["Ye"],
    # Released "Face The Music" (1994) as NKOTB (25 chart rows, 1992-1994)
    "New Kids on the Block": ["NKOTB"],
    # Stylized "Ke$ha" early in her career (458 chart rows, e.g. "3OH!3 Featuring Ke$ha")
    "Kesha": ["Ke$ha"],
}

# Trailing Wikipedia disambiguation tag: "Muse (band)", "Ghost (Swedish band)"
DISAMBIGUATION_PATTERN = re.compile(r"\s*\([^)]*\)\s*$")

logger = logging.getLogger(__name__)


def _tokens(text):
    """Split a name or credit into normalized tokens, keeping commas as tokens."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = DISAMBIGUATION_PATTERN.sub("", text).lower()
    text = text.replace("&", " and ").replace("+", " and ").replace(",", " , ")
    text = re.sub(r"[^a-z0-9,\s]", "", text)  # "feat." -> "feat", "jay-z" -> "jayz"
    return text.split()


def _key(tokens):
    """Comparison key: tokens without commas or a leading "the".

    Billboard credits "Bruce Springsteen & The E Street Band" while the
    band's Wikipedia title is "E Street Band", so "the" is ignored.
    """
    words = [token for token in tokens if token != ","]
    if words[:1] == ["the"] and len(words) > 1:
        words = words[1:]
    return " ".join(words)


def normalize_name(name):
    """Normalize an artist name for comparison.

    Parameters
    ----------
    name : str

    Returns
    -------
    str
        Lowercase ASCII words separated by single spaces, e.g.
        "Earth, Wind & Fire" -> "earth wind and fire".
    """
    return " ".join(token for token in _tokens(name) if token != ",")


class CreditMatcher:
    """Match Billboard performer strings to a fixed list of known artists.

    Parameters
    ----------
    known_artists : iterable of str
        Canonical names to look for (here, Wikipedia titles of tour artists).
    aliases : dict, optional
        Canonical name -> list of alternate spellings.
    """

    def __init__(self, known_artists, aliases=None):
        self.lookup = {}       # normalized spelling -> canonical name
        self.alias_keys = {}   # normalized alias spelling -> the alias as written
        self.protected = []    # (token tuple, canonical name, spelling) for names with separators
        self.alias_hits = {}   # (canonical name, alias) -> performer strings it matched

        # Real names are registered before any alias, so one artist's
        # redirect can never take over another artist's actual name.
        for name in known_artists:
            self._register(name, name)
        for name, alternates in (aliases or {}).items():
            for alias in alternates:
                if self._register(alias, name):
                    self.alias_keys[_key(_tokens(alias))] = alias
        # Longest first, so a longer protected name wins over one it contains
        self.protected.sort(key=lambda item: len(item[0]), reverse=True)

    def _register(self, spelling, name):
        """Add one spelling for a canonical name. Returns False on a collision."""
        tokens = tuple(_tokens(spelling))
        key = _key(tokens)
        if not key:
            return False
        existing = self.lookup.get(key)
        if existing is not None:
            if existing != name:
                # Two different artists normalize the same way. Keep the
                # first and say so, rather than silently overwriting.
                logger.warning("Names collide on %r: keeping %r, ignoring %r",
                               key, existing, name)
            return False
        self.lookup[key] = name
        if any(token in SEPARATORS for token in tokens):
            self.protected.append((tokens, name, spelling))
        return True

    def _protect(self, tokens):
        """Replace protected names in a token list with single locked tokens."""
        locked = {}
        for index, (name_tokens, name, spelling) in enumerate(self.protected):
            size = len(name_tokens)
            position = 0
            while position <= len(tokens) - size:
                if tuple(tokens[position:position + size]) == name_tokens:
                    placeholder = f"<{index}>"
                    locked[placeholder] = (name, spelling)
                    tokens = tokens[:position] + [placeholder] + tokens[position + size:]
                position += 1
        return tokens, locked

    def match(self, performer):
        """Find known artists in a performer credit and label each one's role.

        Parameters
        ----------
        performer : str
            Billboard performer string, e.g. "Travis Scott Featuring Don Toliver".

        Returns
        -------
        list of (str, str)
            (canonical name, "lead" or "featured") in credit order. Unknown
            artists are skipped and each artist appears at most once.
        """
        tokens, locked = self._protect(_tokens(performer))

        credits, segment, role = [], [], "lead"

        def flush(segment, role):
            piece = " ".join(segment)
            if piece in locked:
                name, spelling = locked[piece]
            else:
                key = _key(segment)
                name, spelling = self.lookup.get(key), self.alias_keys.get(key)
            if name and name not in [existing for existing, _ in credits]:
                credits.append((name, role))
                if spelling is not None and spelling != name:
                    self.alias_hits.setdefault((name, spelling), set()).add(performer)

        for token in tokens:
            if token in SEPARATORS:
                flush(segment, role)
                segment = []
                if SEPARATORS[token] == "featured":
                    role = "featured"
            else:
                segment.append(token)
        flush(segment, role)
        return credits


def known_tour_artists(engagements):
    """All headliners and co-headliners named in the tour data.

    Package tours are left out: their "artist" is a brand or compilation
    ("Various Artists"), and matching it would pull in every compilation
    album on the Billboard 200.
    """
    engagements = engagements[~engagements["is_package_tour"]]
    names = set(engagements["artist"].dropna())
    for co_headliners in engagements["co_headliners"].dropna():
        names.update(name.strip() for name in co_headliners.split(";") if name.strip())
    return sorted(names)


def filter_redirect_aliases(redirects, known_artists):
    """Keep only redirects that look like an artist's former or alternate name.

    Wikipedia redirects to an artist page include former names (useful:
    "Lady Antebellum" -> Lady A) but also songs, albums and products
    ("X (fragrance)" -> Westlife), which would match unrelated chart credits.
    An audit of the first unfiltered run found both kinds, so four rules:

    1. Drop redirects with a parenthetical tag: songs, albums, perfumes and
       EPs always have one, while real former names are plain redirects.
    2. Drop one-character names and separator words ("x" would split credits).
    3. Drop aliases that contain another known artist, so joint credits like
       "Bruce Springsteen & the E Street Band" still split into both artists.
    4. Drop aliases claimed by more than one artist, since they're ambiguous.
    5. Drop one-word aliases. A single word is easily someone else's name
       ("Abel." matched the duo "Kane & Abel", not The Weeknd), so one-word
       aliases like "Janet" go in ALIASES only after a manual check.

    Parameters
    ----------
    redirects : dict
        Artist -> list of redirect titles.
    known_artists : list of str

    Returns
    -------
    dict
        Artist -> list of kept aliases. Artists with none are omitted.
    """
    known_keys = {_key(_tokens(name)) for name in known_artists}

    def contains_other_artist(alias, artist):
        own_key = _key(_tokens(artist))
        segment, segments = [], []
        for token in _tokens(alias):
            if token in SEPARATORS:
                segments.append(segment)
                segment = []
            else:
                segment.append(token)
        segments.append(segment)
        return any(_key(s) in known_keys and _key(s) != own_key for s in segments if s)

    candidates = {}
    for artist, titles in redirects.items():
        for alias in titles:
            key = _key(_tokens(alias))
            if DISAMBIGUATION_PATTERN.search(alias):          # rule 1
                continue
            if len(key) <= 1 or key in SEPARATORS:            # rule 2
                continue
            if len(key.split()) < 2:                          # rule 5
                continue
            if contains_other_artist(alias, artist):          # rule 3
                continue
            candidates.setdefault(key, set()).add(artist)
            candidates.setdefault(("alias", key, artist), alias)

    kept = {}
    for artist, titles in redirects.items():
        for alias in titles:
            key = _key(_tokens(alias))
            owners = candidates.get(key)
            if owners == {artist} and candidates.get(("alias", key, artist)) == alias:  # rule 4
                kept.setdefault(artist, []).append(alias)
    return kept


def load_aliases(artists):
    """Combine hand-checked aliases with filtered Wikipedia redirects (former names).

    Parameters
    ----------
    artists : list of str
        Canonical tour artist titles.

    Returns
    -------
    dict
        Artist -> list of alternate spellings.
    """
    aliases = {artist: list(ALIASES.get(artist, [])) for artist in artists}
    if REDIRECTS_PATH.exists():
        redirect_table = pd.read_csv(REDIRECTS_PATH)
        redirects = (redirect_table[redirect_table["artist"].isin(artists)]
                     .groupby("artist")["redirect"].apply(list).to_dict())
        for artist, kept in filter_redirect_aliases(redirects, artists).items():
            aliases[artist].extend(kept)
    return aliases


def run():
    """Match every chart entry to tour artists and save credits plus review reports."""
    engagements = pd.read_csv(ENGAGEMENTS_PATH)
    charts = pd.read_csv(CHARTS_PATH, parse_dates=["chart_week"])
    artists = known_tour_artists(engagements)
    matcher = CreditMatcher(artists, aliases=load_aliases(artists))

    # ~977K chart rows but far fewer distinct credit strings: match each once
    credits_by_performer = {p: matcher.match(p) for p in charts["performer"].dropna().unique()}
    rows = [
        {**entry, "artist": name, "role": role}
        for entry in charts.to_dict("records")
        for name, role in credits_by_performer.get(entry["performer"], [])
    ]
    credits = pd.DataFrame(rows)
    credits.to_csv(OUTPUT_PATH, index=False)

    matched = set(credits["artist"])
    unmatched = pd.DataFrame({"artist": [a for a in artists if a not in matched]})
    unmatched["normalized"] = unmatched["artist"].map(normalize_name)
    unmatched.to_csv(UNMATCHED_PATH, index=False)

    # Every match made through an alias, with how many chart rows it added,
    # so redirect-based matches can be reviewed by hand
    rows_per_performer = charts["performer"].value_counts()
    alias_report = pd.DataFrame([
        {"artist": artist, "alias": alias,
         "chart_rows": int(rows_per_performer[list(performers)].sum()),
         "example_credits": " | ".join(sorted(performers)[:3])}
        for (artist, alias), performers in sorted(matcher.alias_hits.items())
    ])
    alias_report.to_csv(ALIAS_REPORT_PATH, index=False)
    logger.info("%d alias matches (see %s)", len(alias_report), ALIAS_REPORT_PATH.name)

    logger.info("%d tour artists, %d found on a chart, %d not found (see %s)",
                len(artists), len(matched), len(unmatched), UNMATCHED_PATH.name)
    logger.info("Saved %d credits (%d lead, %d featured) to %s", len(credits),
                (credits["role"] == "lead").sum(), (credits["role"] == "featured").sum(),
                OUTPUT_PATH)
    return credits


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
