"""Tests for normalizing artist names and splitting Billboard credits."""

import pandas as pd
import pytest

from concert_demand.clean.artist_names import (
    CreditMatcher,
    filter_redirect_aliases,
    known_tour_artists,
    normalize_name,
)


@pytest.mark.parametrize("raw, expected", [
    ("Beyoncé", "beyonce"),
    ("JAY-Z", "jayz"),
    ("Jay-Z", "jayz"),
    ("Earth, Wind & Fire", "earth wind and fire"),
    ("Florence + The Machine", "florence and the machine"),
    ("Ghost (Swedish band)", "ghost"),       # Wikipedia disambiguation tag
    ("Muse (band)", "muse"),
    ("  Post   Malone ", "post malone"),
    ("Panic! At The Disco", "panic at the disco"),
    ("The Weeknd", "the weeknd"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


KNOWN = ["Travis Scott", "Don Toliver", "Drake", "Future", "Jay-Z", "Beyoncé",
         "Earth, Wind & Fire", "Mumford & Sons", "Post Malone", "Lil Nas X",
         "Pink (singer)", "Florence + The Machine"]


@pytest.fixture
def matcher():
    return CreditMatcher(KNOWN, aliases={"Pink (singer)": ["P!nk"]})


@pytest.mark.parametrize("performer, expected", [
    # The Don Toliver case: a featured credit before he led anything
    ("Travis Scott Featuring Don Toliver",
     [("Travis Scott", "lead"), ("Don Toliver", "featured")]),
    ("Jay-Z & Beyonce", [("Jay-Z", "lead"), ("Beyoncé", "lead")]),
    ("Drake Featuring Future & Jay-Z",
     [("Drake", "lead"), ("Future", "featured"), ("Jay-Z", "featured")]),
    ("Drake Feat. Future", [("Drake", "lead"), ("Future", "featured")]),
    ("Post Malone With Drake", [("Post Malone", "lead"), ("Drake", "featured")]),
    ("Drake x Future", [("Drake", "lead"), ("Future", "lead")]),
    # Names containing separators must stay whole
    ("Earth, Wind & Fire", [("Earth, Wind & Fire", "lead")]),
    ("Mumford & Sons", [("Mumford & Sons", "lead")]),
    ("Lil Nas X Featuring Billy Ray Cyrus", [("Lil Nas X", "lead")]),
    ("Florence + The Machine", [("Florence + The Machine", "lead")]),
    # Alias for a spelling that differs from the Wikipedia title
    ("P!nk Featuring Nate Ruess", [("Pink (singer)", "lead")]),
    # Exact matching: a known name inside a longer name is not a match
    ("Drake Bell", []),
    ("Future Islands", []),
    ("Somebody Unknown", []),
])
def test_match_credits(matcher, performer, expected):
    assert matcher.match(performer) == expected


@pytest.mark.parametrize("performer, expected", [
    # A leading "The" is ignored on both sides
    ("Bruce Springsteen & The E Street Band", [("E Street Band", "lead")]),
    ("The Weeknd & Ariana Grande", [("Weeknd Test", "lead")]),
])
def test_match_ignores_leading_the(performer, expected):
    matcher = CreditMatcher(["E Street Band", "Weeknd Test"],
                            aliases={"Weeknd Test": ["The Weeknd"]})
    assert matcher.match(performer) == expected


def test_matcher_warns_and_keeps_first_when_two_names_collide(caplog):
    # "The Weeknd" and "the Weeknd" normalize identically. This used to
    # silently overwrite one with the other.
    matcher = CreditMatcher(["The Weeknd", "the Weeknd"])
    assert matcher.match("The Weeknd") == [("The Weeknd", "lead")]
    assert "collide" in caplog.text


def test_match_credits_does_not_repeat_an_artist(matcher):
    # Rare but real: an artist credited twice on one entry
    assert matcher.match("Drake Featuring Drake") == [("Drake", "lead")]


def test_known_tour_artists_skips_package_tours_and_splits_co_headliners():
    engagements = pd.DataFrame({
        "artist": ["Jay-Z", "Various Artists", "Def Leppard"],
        "co_headliners": ["Beyoncé", "", "Mötley Crüe; Poison"],
        "is_package_tour": [False, True, False],
    })
    assert known_tour_artists(engagements) == ["Beyoncé", "Def Leppard", "Jay-Z",
                                              "Mötley Crüe", "Poison"]


def test_redirect_aliases_catch_renamed_artists():
    # Lady A charted as "Lady Antebellum" until 2020
    matcher = CreditMatcher(["Lady A"], aliases={"Lady A": ["Lady Antebellum"]})
    assert matcher.match("Lady Antebellum") == [("Lady A", "lead")]
    assert matcher.match("Lady A") == [("Lady A", "lead")]


def test_real_names_beat_another_artists_alias():
    # If artist B's redirect list contains artist A's actual name, the
    # credit must still go to A, whatever order the names arrive in.
    matcher = CreditMatcher(["B Artist", "Future"], aliases={"B Artist": ["Future"]})
    assert matcher.match("Future") == [("Future", "lead")]


def test_matcher_records_which_alias_matched():
    matcher = CreditMatcher(["Lady A"], aliases={"Lady A": ["Lady Antebellum"]})
    matcher.match("Lady Antebellum Featuring Someone")
    assert matcher.alias_hits == {
        ("Lady A", "Lady Antebellum"): {"Lady Antebellum Featuring Someone"}}


def test_filter_redirect_aliases_keeps_real_former_names_only():
    known = ["Westlife", "Jennifer Lopez", "The Weeknd", "Bruce Springsteen", "E Street Band",
             "Lady A", "Paul Simon", "Kanye West", "The Chainsmokers"]
    redirects = {
        "Westlife": ["X (fragrance)"],                     # product: parenthetical
        "Jennifer Lopez": ["Live (perfume)", "Jenny Lopez", "J"],  # one-letter alias dropped
        "The Weeknd": ["Abel.", "Abel Tesfaye"],         # one-word alias dropped
        "Bruce Springsteen": ["Bruce Springsteen & the E Street Band"],  # contains another artist
        "Lady A": ["Lady Antebellum"],                     # real rename: kept
        "Paul Simon": ["Tico and the Triumphs"],           # stage name with "and": kept
        "Kanye West": ["Kanye"],                           # claimed by two artists
        "The Chainsmokers": ["Kanye"],
    }
    assert filter_redirect_aliases(redirects, known) == {
        "Jennifer Lopez": ["Jenny Lopez"],
        "Lady A": ["Lady Antebellum"],
        "Paul Simon": ["Tico and the Triumphs"],
        "The Weeknd": ["Abel Tesfaye"],
    }
