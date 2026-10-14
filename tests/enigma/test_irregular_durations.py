"""Entries whose stored length is no dotted note value reach the IR and MusicXML.

Finale times an entry by its stored `dura` and draws the note value that length
begins with (see `duration_from_edu`). The IR keeps both: `written_duration` is
the drawn value, `duration` the stored length, and the ratio between them is
what lets MusicXML draw the one and time the other.
"""

from __future__ import annotations

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Event, Score

NS = "http://www.makemusic.com/2012/finale"

WHOLE_EDU = 4096


def _next_after(number: int, count: int) -> int:
    return number + 1 if number < count else 0


def _one_measure_of(*durations_edu: int) -> bytes:
    """A 4/4 measure on one staff holding a C4 per given stored length."""
    count = len(durations_edu)
    entries = "".join(
        f'<entry entnum="{number}" prev="{number - 1}" next="{_next_after(number, count)}">'
        f"<numNotes>1</numNotes><dura>{edu}</dura><isNote/>"
        '<note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>'
        for number, edu in enumerate(durations_edu, start=1)
    )
    return f"""<finale version="18.0" xmlns="{NS}">
    <entries>{entries}</entries>
    <others>
      <frameSpec cmper="10" inci="0">
        <startEntry>1</startEntry><endEntry>{count}</endEntry>
      </frameSpec>
      <measSpec cmper="1">
        <keySig><key>0</key></keySig><beats>4</beats><divbeat>1024</divbeat>
      </measSpec>
      <staffSpec cmper="1"><x>a</x></staffSpec>
    </others>
    <details><gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold></details>
</finale>""".encode()


def _events(score: Score) -> list[Event]:
    return [
        event
        for measure in score.parts[0].measures
        for voice in measure.voices
        for event in voice.events
    ]


IRREGULAR_MEASURE = _one_measure_of(576, 448, 1024, 2048)
"""576 + 448 = 1024, a pairing a real score stores (an eighth-plus-a-64th then a
double-dotted 16th); with a quarter and a half the measure is a full 4/4."""


def test_an_irregular_length_is_drawn_as_its_note_value_and_timed_by_its_stored_length() -> None:
    first_event = _events(build_score(parse_enigma(IRREGULAR_MEASURE)))[0]

    assert first_event.written_duration == Fraction(512, WHOLE_EDU), (
        "576 EDU draws as an eighth (512 EDU), so the notehead must be an eighth, "
        f"but the written duration was {first_event.written_duration}"
    )
    assert first_event.duration == Fraction(576, WHOLE_EDU), (
        "the entry is timed by its stored 576 EDU, but the sounded duration was "
        f"{first_event.duration}"
    )
    assert first_event.tuplet_ratio == Fraction(576, 512), (
        "the drawn eighth sounds 576/512 of itself, which is what lets a reader "
        f"reconcile type and duration, but the ratio was {first_event.tuplet_ratio}"
    )


def test_a_measure_of_irregular_lengths_still_fills_its_time_signature() -> None:
    events = _events(build_score(parse_enigma(IRREGULAR_MEASURE)))
    measure_total = sum((event.duration for event in events), Fraction(0))
    assert measure_total == 1, (
        "576 + 448 + 1024 + 2048 EDU is exactly one 4/4 measure, "
        f"but the events sum to {measure_total}"
    )


def test_an_exactly_notated_entry_carries_no_time_modification() -> None:
    quarter_event = _events(build_score(parse_enigma(IRREGULAR_MEASURE)))[2]
    assert quarter_event.tuplet_ratio is None, (
        "a quarter stored as 1024 EDU is drawn as exactly what it sounds, so it needs no "
        f"ratio, but carried {quarter_event.tuplet_ratio}"
    )


def test_musicxml_draws_the_note_value_and_times_the_stored_length() -> None:
    tree = DET.fromstring(to_musicxml(build_score(parse_enigma(IRREGULAR_MEASURE))).decode())
    divisions = int(tree.findtext(".//divisions", default="0"))
    drawn_type = tree.findtext(".//note/type")
    timed_duration = Fraction(int(tree.findtext(".//note/duration", default="0")), divisions * 4)

    assert drawn_type == "eighth", f"576 EDU must be drawn as an eighth, but was {drawn_type!r}"
    assert timed_duration == Fraction(576, WHOLE_EDU), (
        f"576 EDU must be timed as 576/4096 of a whole note, but was {timed_duration}"
    )
