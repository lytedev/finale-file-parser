from fractions import Fraction

import pytest

from finale_file_parser.enigma.document import Record
from finale_file_parser.enigma.music import (
    Duration,
    Entry,
    MalformedEntryError,
    Note,
    NoteValue,
    duration_from_edu,
    read_entry,
)

_Field = str | tuple[str, ...] | Record | tuple[Record, ...]


def _note(harm_lev: str, harm_alt: str = "0", **flags: str) -> Record:
    fields: dict[str, _Field] = {"harmLev": harm_lev, "harmAlt": harm_alt, "isValid": ""}
    fields.update(flags)
    return Record(tag="note", attrs={}, text="", fields=fields)


def _entry(dura: str, notes: tuple[Record, ...] = (), **extra: str) -> Record:
    fields: dict[str, _Field] = {
        "dura": dura,
        "numNotes": str(len(notes)),
        "isValid": "",
    }
    if notes:
        fields["note"] = notes if len(notes) > 1 else notes[0]
    fields.update(extra)
    return Record(tag="entry", attrs={"entnum": "1"}, text="", fields=fields)


def test_quarter_note_single_pitch() -> None:
    entry: Entry = read_entry(_entry("1024", (_note("0"),)))
    assert entry.entnum == 1
    assert entry.is_rest is False
    assert entry.duration.base is NoteValue.QUARTER
    assert entry.duration.dots == 0
    assert entry.duration.edu == 1024
    assert entry.duration.whole_notes == Fraction(1, 4)
    assert len(entry.notes) == 1
    assert entry.notes[0].harm_lev == 0
    assert entry.notes[0].harm_alt == 0


def test_dotted_quarter() -> None:
    d: Duration = read_entry(_entry("1536", (_note("1"),))).duration
    assert d.base is NoteValue.QUARTER
    assert d.dots == 1
    assert d.whole_notes == Fraction(3, 8)


def test_double_dotted_half() -> None:
    d = read_entry(_entry("3584", (_note("0"),))).duration  # 2048+1024+512
    assert d.base is NoteValue.HALF
    assert d.dots == 2


def test_rest_has_no_notes() -> None:
    entry = read_entry(_entry("1024"))
    assert entry.is_rest is True
    assert entry.notes == ()


def test_chord_multiple_notes() -> None:
    entry = read_entry(_entry("512", (_note("0"), _note("2"), _note("4"))))
    assert entry.is_rest is False
    assert [n.harm_lev for n in entry.notes] == [0, 2, 4]


def test_note_below_middle_c_octave_and_degree() -> None:
    # harm_lev = -1 is the diatonic step just below the tonic: degree 6, octave -1
    n: Note = read_entry(_entry("1024", (_note("-1"),))).notes[0]
    assert n.diatonic_step == 6
    assert n.octave_offset == -1
    # +7 is one octave up
    up = read_entry(_entry("1024", (_note("7"),))).notes[0]
    assert up.diatonic_step == 0
    assert up.octave_offset == 1


def test_alteration_sign() -> None:
    assert read_entry(_entry("1024", (_note("0", "1"),))).notes[0].harm_alt == 1
    assert read_entry(_entry("1024", (_note("0", "-1"),))).notes[0].harm_alt == -1


def test_tie_flags() -> None:
    n = read_entry(_entry("1024", (_note("0", tieStart="", tieEnd=""),))).notes[0]
    assert n.tie_start is True
    assert n.tie_end is True
    plain = read_entry(_entry("1024", (_note("0"),))).notes[0]
    assert plain.tie_start is False
    assert plain.tie_end is False


def test_whole_note_fraction() -> None:
    assert read_entry(_entry("4096", (_note("0"),))).duration.whole_notes == Fraction(1, 1)


def test_frozen() -> None:
    entry = read_entry(_entry("1024", (_note("0"),)))
    with pytest.raises((AttributeError, TypeError)):
        entry.is_rest = True  # type: ignore[misc]


def test_rejects_non_entry_record() -> None:
    with pytest.raises(MalformedEntryError, match="entry"):
        read_entry(Record(tag="note", attrs={}, text="", fields={}))


def test_rejects_non_integer_dura() -> None:
    with pytest.raises(MalformedEntryError):
        read_entry(_entry("notanumber"))


def test_rejects_a_dura_shorter_than_every_note_value() -> None:
    """Below a 1024th (4 EDU) MusicXML has no `<type>` to draw it with."""
    with pytest.raises(MalformedEntryError, match="shorter than any note value"):
        read_entry(_entry("3", (_note("0"),)))


def test_rejects_a_zero_dura() -> None:
    """An entry that sounds for no time is a grace note, which says so by flag."""
    with pytest.raises(MalformedEntryError, match="out of range"):
        read_entry(_entry("0", (_note("0"),)))


def test_rejects_numnotes_disagreeing_with_note_count() -> None:
    # One note record, but numNotes claims five.
    bad = Record(
        tag="entry",
        attrs={"entnum": "1"},
        text="",
        fields={"dura": "1024", "numNotes": "5", "isValid": "", "note": _note("0")},
    )
    with pytest.raises(MalformedEntryError, match="numNotes"):
        read_entry(bad)


def test_rejects_non_integer_harmlev() -> None:
    with pytest.raises(MalformedEntryError):
        read_entry(_entry("1024", (_note("x"),)))


def test_a_dotted_whole_decodes() -> None:
    """4096 + 2048. It was rejected for being larger than a whole note, but the
    limit belongs on the base value, not on the total: every dotted note exceeds
    its own base."""
    duration = duration_from_edu(6144)
    assert (duration.base, duration.dots) == (NoteValue.WHOLE, 1)


def test_a_breve_decodes() -> None:
    """Two whole notes, and ordinary notation in early music -- the corpus
    document that needed it is a Renaissance motet."""
    duration = duration_from_edu(8192)
    assert (duration.base, duration.dots) == (NoteValue.BREVE, 0)


def test_a_dotted_breve_decodes() -> None:
    duration = duration_from_edu(12288)
    assert (duration.base, duration.dots) == (NoteValue.BREVE, 1)


def test_a_longa_is_still_refused() -> None:
    """No corpus document carries one, so nothing checks a guess at it."""
    with pytest.raises(MalformedEntryError):
        duration_from_edu(16384)


@pytest.mark.parametrize(
    ("stored_edu", "drawn_base", "drawn_dots", "drawn_edu"),
    [
        (576, NoteValue.EIGHTH, 0, 512),
        (85, NoteValue.SIXTY_FOURTH, 0, 64),
        (704, NoteValue.EIGHTH, 0, 512),
        (3328, NoteValue.HALF, 1, 3072),
        (1000, NoteValue.EIGHTH, 4, 992),
        (9000, NoteValue.BREVE, 0, 8192),
    ],
)
def test_a_length_between_note_values_draws_its_leading_run_of_bits_and_keeps_its_length(
    stored_edu: int, drawn_base: NoteValue, drawn_dots: int, drawn_edu: int
) -> None:
    """The highest set bit is the note value and each set bit directly below it a dot.

    Finale stores such lengths (576 = 512 + 64 is an eighth plus a 64th's worth
    of time) and draws the note value they begin with; the stored length must
    survive untouched, since it is what the entry is timed by.
    """
    duration = duration_from_edu(stored_edu)
    assert (duration.base, duration.dots) == (drawn_base, drawn_dots), (
        f"{stored_edu} EDU must draw as {drawn_base.name} with {drawn_dots} dot(s), "
        f"but drew as {duration.base.name} with {duration.dots}"
    )
    assert duration.notated_edu == drawn_edu, (
        f"the drawn value of {stored_edu} EDU is {drawn_edu} EDU, not {duration.notated_edu}"
    )
    assert duration.edu == stored_edu, (
        f"the stored length {stored_edu} must be kept for timing, but became {duration.edu}"
    )
    assert not duration.is_notated_exactly, (
        f"{stored_edu} EDU is not a dotted note value, so it cannot be notated exactly"
    )


@pytest.mark.parametrize("stored_edu", [32, 1024, 1536, 3584, 6144, 8192, 12288])
def test_every_dotted_note_value_is_notated_exactly(stored_edu: int) -> None:
    duration = duration_from_edu(stored_edu)
    assert duration.is_notated_exactly, (
        f"{stored_edu} EDU is a dotted note value and must draw as itself, "
        f"but drew as {duration.notated_edu} EDU"
    )


@pytest.mark.parametrize(
    ("stored_edu", "drawn_base"),
    [
        (16, NoteValue.TWO_FIFTY_SIXTH),
        (8, NoteValue.FIVE_TWELFTH),
        (4, NoteValue.ONE_THOUSAND_TWENTY_FOURTH),
    ],
)
def test_note_values_reach_down_to_the_shortest_musicxml_type(
    stored_edu: int, drawn_base: NoteValue
) -> None:
    """Hidden 16- and 8-EDU rests pad hidden 85-EDU runs to the barline in real files."""
    duration = duration_from_edu(stored_edu)
    assert duration.base is drawn_base, (
        f"{stored_edu} EDU must decode as {drawn_base.name}, but decoded as {duration.base.name}"
    )
