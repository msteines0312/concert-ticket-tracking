"""Tests for mapping Wikipedia infobox genres to Billboard genre groups."""

import pytest

from concert_demand.clean.genres import assign_group, genre_group, infobox_genres


@pytest.mark.parametrize("label, group", [
    ("Latin pop", "Latin"),              # Latin is checked before Pop
    ("Pop rap", "R&B/Hip-Hop"),          # rap before pop
    ("Alternative R&B", "R&B/Hip-Hop"),  # R&B before alternative
    ("Southern hip-hop", "R&B/Hip-Hop"),
    ("Pop rock", "Rock/Alternative"),
    ("Dance-pop", "Pop"),                # only the exact label "dance" is Dance/Electronic
    ("Dance", "Dance/Electronic"),
    ("K-pop", "Pop"),
    ("Honky-tonk", "Country"),
    ("Broadway", "Other"),
])
def test_genre_group(label, group):
    assert genre_group(label) == group


def test_assign_group_takes_the_majority_not_the_first_label():
    assert assign_group(["Country", "pop", "pop rock", "dance-pop"]) == ("Pop", False)


def test_assign_group_ignores_unmatched_labels_when_a_real_group_exists():
    # "jazz" and "world" match no group and must not outvote Pop
    assert assign_group(["Pop", "jazz", "world"]) == ("Pop", False)


def test_assign_group_breaks_ties_by_first_listed_and_flags_them():
    assert assign_group(["Rock", "pop"]) == ("Rock/Alternative", True)


def test_infobox_genres_reads_links_and_skips_citations():
    wikitext = """{{Infobox musical artist
| name = Example
| genre = {{hlist|[[Pop music|Pop]]|[[Rhythm and blues|R&B]]<ref>{{cite web|work=[[AllMusic]]}}</ref>}}
| years_active = 2010-present
}}"""
    assert infobox_genres(wikitext) == ["Pop", "R&B"]


def test_infobox_genres_is_empty_without_a_genre_field():
    assert infobox_genres("{{Infobox person\n| name = Example\n}}") == []
