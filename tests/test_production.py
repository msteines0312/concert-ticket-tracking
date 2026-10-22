"""Tests for set length and production evidence from tour articles.

Each set-list case copies a format found in real articles while building
the counter (made-up song names).
"""

from concert_demand.clean.production import production_evidence, set_list_length


def _article(set_list_body, heading="==Set list=="):
    return f"Intro text.\n\n{heading}\n{set_list_body}\n\n==Tour dates==\nTable here.\n"


def test_counts_a_plain_numbered_list():
    assert set_list_length(_article('# "One"\n# "Two"\n# "Three"')) == 3


def test_skips_notes_and_leg_subheadings_before_the_list():
    body = ('This set list is from the concert in Philadelphia.<ref>x</ref>\n'
            '===North America leg 1===\n{{div col}}\n# "One"\n# "Two"')
    assert set_list_length(_article(body)) == 2


def test_stops_at_the_next_leg_so_two_lists_are_not_added():
    body = '===Leg 1===\n# "One"\n# "Two"\n===Leg 2===\n# "Three"\n# "Four"\n# "Five"'
    assert set_list_length(_article(body)) == 2


def test_counts_acts_with_bold_headers_and_italic_interludes_as_one_set():
    body = ("'''Act I'''\n# \"One\"\n# \"Two\"\n'''Act II'''\n''\"Intro\" {{small|(interlude)}}''\n"
            '#<li value=3>"Three"')
    assert set_list_length(_article(body)) == 3


def test_ignores_rotating_songs_encore_labels_and_empty_entries():
    body = '# "One"\n#*"Rotated in some nights"\n#\n#;Encore\n# "Two"'
    assert set_list_length(_article(body)) == 2


def test_stops_when_a_collapsed_box_closes():
    body = ('{{hidden|header=South America|content={{div col}}\n# "One"\n# "Two"\n'
            '{{Div col end}}|headercss=background: #ccccff\n# "Three"')
    assert set_list_length(_article(body)) == 2


def test_stops_at_a_bold_caption_for_the_next_set_list():
    body = "# \"One\"\n# \"Two\"\n'''Setlist for Europe (leg 2)'''\n# \"Three\""
    assert set_list_length(_article(body)) == 2


def test_finds_headings_that_do_not_start_with_set_list():
    assert set_list_length(_article('# "One"\n# "Two"', heading="==Standard set list ==")) == 2


def test_no_set_list_section_is_missing():
    assert set_list_length("Intro.\n==Tour dates==\nTable.") is None


def test_production_evidence_reads_stage_sections_and_drops_citations():
    wikitext = ("Lead.\n\n==Stage==\nThe show featured a catwalk and twelve dancers."
                "<ref>{{cite web|title=Review}}</ref>\n\n==Tour dates==\nTable.\n")
    evidence, has_section = production_evidence(wikitext)
    assert has_section
    assert "twelve dancers" in evidence
    assert "cite web" not in evidence
