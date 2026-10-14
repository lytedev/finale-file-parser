"""Typed musical values over generic EnigmaXML entry/note records.

`read_entry` turns one `entry` Record into an `Entry`: its written duration, whether
it is a rest, and its notes. Pitch is the key-relative Enigma encoding (harmLev /
harmAlt) — spelling absolute pitches needs the key and is a separate slice. See
docs/superpowers/specs/2026-07-23-typed-entries-design.md and docs/eeppd.txt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import cast

from finale_file_parser.enigma.document import Record
from finale_file_parser.errors import FinaleFileError

_WHOLE_EDU = 4096
_LONGEST_EDU = 8192
"""The longest base note value read: a breve."""

_MAX_DURATION_EDU = 2 * _LONGEST_EDU - 1
"""Refuse anything a breve cannot reach even fully dotted -- a longa and beyond."""
_DIATONIC_STEPS = 7


class MalformedEntryError(FinaleFileError):
    """An entry/note record could not be read as typed music."""


class NoteValue(Enum):
    """A base written note value, in EDU (a whole note is 4096).

    A breve -- two whole notes -- is ordinary notation in early music and one
    corpus document uses it. Nothing longer is listed: a longa would be the next
    value up and no corpus document carries one, so there is nothing to check a
    guess at it against.

    The short end stops at the 1024th, the shortest MusicXML `<type>`. The
    256th and 512th are not ornament: NinSheetMusic documents pad runs of hidden
    85-EDU playback notes out to the barline with hidden 16- and 8-EDU rests
    (48 x 85 + 16 = 4096, a 4/4 bar).
    """

    BREVE = 8192
    WHOLE = 4096
    HALF = 2048
    QUARTER = 1024
    EIGHTH = 512
    SIXTEENTH = 256
    THIRTY_SECOND = 128
    SIXTY_FOURTH = 64
    ONE_TWENTY_EIGHTH = 32
    TWO_FIFTY_SIXTH = 16
    FIVE_TWELFTH = 8
    ONE_THOUSAND_TWENTY_FOURTH = 4


@dataclass(frozen=True)
class Duration:
    """A written duration: a base note value plus augmentation dots.

    `edu` is the length Finale stores and times the entry by. `base` and `dots`
    are what Finale *draws*, and for almost every entry the two agree. They part
    where a file stores a length no dotted note value equals -- see
    `duration_from_edu` -- and then `notated_edu` is the drawn value and `edu`
    the timed one.
    """

    edu: int
    base: NoteValue
    dots: int

    @property
    def whole_notes(self) -> Fraction:
        """The duration as a fraction of a whole note (edu / 4096)."""
        return Fraction(self.edu, _WHOLE_EDU)

    @property
    def notated_edu(self) -> int:
        """The EDU of the drawn note value: `base` plus each dot's half of the last."""
        return sum(self.base.value >> dot for dot in range(self.dots + 1))

    @property
    def is_notated_exactly(self) -> bool:
        """Whether the drawn note value is exactly the stored length."""
        return self.notated_edu == self.edu


@dataclass(frozen=True)
class Note:
    """One pitch. Encoding is relative to the key; not spelled here."""

    harm_lev: int
    """Diatonic displacement from the key's tonic (tonic at middle C = 0, +7 = one octave)."""

    harm_alt: int
    """Alteration relative to the key: 0 natural, +1 sharp, -1 flat. Not the shown accidental."""

    tie_start: bool
    tie_end: bool

    @property
    def diatonic_step(self) -> int:
        """Scale degree from the tonic, 0..6 (key-relative; not a letter name)."""
        return self.harm_lev % _DIATONIC_STEPS

    @property
    def octave_offset(self) -> int:
        """Octaves from the middle-C tonic octave (floor division; negative below)."""
        return self.harm_lev // _DIATONIC_STEPS


@dataclass(frozen=True)
class Entry:
    """A musical event: a note, chord, or rest."""

    entnum: int
    duration: Duration
    is_rest: bool
    notes: tuple[Note, ...]


def read_entry(record: Record) -> Entry:
    """Read one `entry` Record as a typed `Entry`.

    Raises:
        MalformedEntryError: the record is not a well-formed entry.
    """
    if record.tag != "entry":
        raise MalformedEntryError(f"expected an <entry> record, got <{record.tag}>")
    entnum = _int(record.attrs.get("entnum"), "entnum")
    duration = _duration(record)
    notes = _notes(record)
    num_notes = _int(_scalar(record, "numNotes"), "numNotes")
    if num_notes != len(notes):
        raise MalformedEntryError(
            f"numNotes={num_notes} disagrees with {len(notes)} note record(s)"
        )
    return Entry(entnum=entnum, duration=duration, is_rest=num_notes == 0, notes=notes)


def duration_from_edu(edu: int) -> Duration:
    """Decode a written duration in EDU into a base note value plus dots.

    Shared by the `.musx` and `.mus` readers: both formats store the same EDU
    quantity, so the decode belongs in one place rather than being reimplemented
    per container.

    **The base is the highest set bit, and each dot is a further set bit directly
    below it.** For an ordinary dotted value that is simply its decode. For a
    length no dotted note value equals -- Finale stores whatever a MIDI import,
    *Change Note Durations* or a hand-edited entry leaves behind -- the bits
    below the first clear one are not drawn: 576 (512 + 64) draws as an eighth,
    85 (64 + 16 + 4 + 1) as a 64th, 3328 (2048 + 1024 + 256) as a dotted half.
    `Duration.edu` keeps the stored length, so timing is not rounded.

    The rule is the musx object model's `calcDurationInfoFromEdu`,
    https://github.com/rpatters1/musx-object-model/blob/deda69c1a8622c4268000f8c3e8df460ddef41a8/src/musx/dom/Entries.cpp#L173-L194
    -- the one reading of such durations this project can point to. Refusing
    them instead stopped eight NinSheetMusic documents at their first such
    entry.
    """
    # The limit belongs on the base value, not on the total: every dotted note
    # exceeds its own base, so testing the total rejected a dotted whole (6144)
    # for being "larger than a whole note".
    if edu <= 0 or edu > _MAX_DURATION_EDU:
        raise MalformedEntryError(f"dura {edu} is out of range")
    base_edu = 1 << (edu.bit_length() - 1)
    dots = 0
    while (base_edu >> (dots + 1)) & edu:
        dots += 1
    try:
        base = NoteValue(base_edu)
    except ValueError as exc:
        raise MalformedEntryError(f"dura {edu} is shorter than any note value") from exc
    return Duration(edu=edu, base=base, dots=dots)


def _duration(record: Record) -> Duration:
    return duration_from_edu(_int(_scalar(record, "dura"), "dura"))


def _notes(record: Record) -> tuple[Note, ...]:
    raw = record.fields.get("note")
    records: tuple[Record, ...]
    if raw is None:
        records = ()
    elif isinstance(raw, Record):
        records = (raw,)
    elif isinstance(raw, tuple) and all(isinstance(r, Record) for r in raw):
        records = cast(tuple[Record, ...], raw)
    else:
        raise MalformedEntryError("note field is not record(s)")
    return tuple(_note(r) for r in records)


def _note(record: Record) -> Note:
    return Note(
        harm_lev=_int(_scalar(record, "harmLev"), "harmLev"),
        harm_alt=_int(_scalar(record, "harmAlt"), "harmAlt"),
        tie_start="tieStart" in record.fields,
        tie_end="tieEnd" in record.fields,
    )


def _scalar(record: Record, name: str) -> str:
    value = record.fields.get(name)
    if not isinstance(value, str):
        raise MalformedEntryError(f"<{record.tag}> field {name!r} is missing or not scalar")
    return value


def _int(value: str | None, name: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MalformedEntryError(f"{name} is not an integer: {value!r}") from exc
